"""Game orchestrator: creates lobbies, sets up player sessions, drives turn-by-turn play.

Run with::

    uv run python -m agents.orchestrator --bot-mode --players 5 --seed 42
"""

from __future__ import annotations

import argparse
import json
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import httpx

from agents.claude_code_launcher import PlayerSession


# ─── Bot player (random-action, for testing) ────────────────────────────────


class RandomBot:
    """A simple bot that picks random legal actions via the REST API."""

    def __init__(self, game_id: str, player_id: int, token: str, base_url: str, rng: random.Random) -> None:
        self.game_id = game_id
        self.player_id = player_id
        self.token = token
        self.base_url = base_url
        self._rng = rng
        self._headers = {"Authorization": f"Bearer {token}"}

    def act(self, client: httpx.Client) -> dict | None:
        """Check if it is this bot's turn and submit a random legal action.

        Returns the action result dict, or None if it was not this bot's turn.
        """
        resp = client.get(
            f"{self.base_url}/api/games/{self.game_id}/status",
            headers=self._headers,
        )
        resp.raise_for_status()
        status = resp.json()

        if status["is_game_over"]:
            return None

        pa = status.get("pending_action")
        if pa is None:
            return None

        required = pa["required_by"]
        # required_by is either an int or a list of ints (for voting)
        if isinstance(required, list):
            if self.player_id not in required:
                return None
        else:
            if self.player_id != required:
                return None

        action_type, payload = self._pick_action(pa)
        resp = client.post(
            f"{self.base_url}/api/games/{self.game_id}/action",
            json={"action_type": action_type, "payload": payload},
            headers=self._headers,
        )
        resp.raise_for_status()
        return resp.json()

    def _pick_action(self, pending_action: dict) -> tuple[str, dict]:
        """Choose a random legal action based on the pending action info."""
        expected = pending_action["expected_action"]
        targets = pending_action.get("legal_targets")

        if expected == "NominateChancellor":
            target = self._rng.choice(targets)
            return "nominate", {"target_id": target}

        if expected == "CastVote":
            return "vote", {"vote": self._rng.choice([True, False])}

        if expected == "PresidentDiscard":
            return "president_discard", {"discard_index": self._rng.choice(targets)}

        if expected == "ChancellorEnact":
            # Filter out None (veto) for simplicity; bots don't veto
            non_veto = [t for t in targets if t is not None]
            return "chancellor_enact", {"enact_index": self._rng.choice(non_veto)}

        if expected == "VetoResponse":
            return "veto_response", {"consent": self._rng.choice([True, False])}

        if expected == "InvestigatePlayer":
            return "investigate", {"target_id": self._rng.choice(targets)}

        if expected == "PolicyPeekAck":
            return "peek_ack", {}

        if expected == "SpecialElection":
            return "special_election", {"target_id": self._rng.choice(targets)}

        if expected == "ExecutePlayer":
            return "execute", {"target_id": self._rng.choice(targets)}

        raise ValueError(f"Unknown expected action: {expected}")


# ─── Orchestrator ────────────────────────────────────────────────────────────

_MAX_RETRIES = 3  # retries per turn if agent fails to submit action


class GameOrchestrator:
    """Manages a full game lifecycle with turn-driven agent invocation.

    In Claude Code mode, instead of spawning long-lived subprocesses that poll
    autonomously, the orchestrator detects whose turn it is and invokes only the
    relevant player(s) via ``claude --print --resume``.  Each invocation is
    short (1-5 tool calls), and ``--resume`` preserves the agent's full memory
    across turns.
    """

    def __init__(
        self,
        server_url: str = "http://127.0.0.1:8000",
        num_players: int = 5,
        skin: str = "secret_hitler",
        seed: int | None = None,
        bot_mode: bool = False,
        discussion_time: float = 0.0,
        poll_interval: float = 0.5,
        action_timeout: float = 300.0,
        model: str = "claude-sonnet-4-6",
        models: list[str] | None = None,
        max_turns_action: int = 10,
        max_turns_discussion: int = 5,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.num_players = num_players
        self.skin = skin
        self.seed = seed
        self.bot_mode = bot_mode
        self.discussion_time = discussion_time
        self.poll_interval = poll_interval
        self.action_timeout = action_timeout
        self.model = model
        self.models = models
        self.max_turns_action = max_turns_action
        self.max_turns_discussion = max_turns_discussion

        self.game_id: str | None = None
        self.tokens: dict[str, int] = {}
        self._bots: list[RandomBot] = []
        self._sessions: dict[int, PlayerSession] = {}
        self._rng = random.Random(seed)

    # ── lobby / start ────────────────────────────────────────────────────

    def create_lobby(self, client: httpx.Client) -> dict:
        """POST /api/lobbies to create a new game lobby."""
        body: dict[str, Any] = {
            "num_players": self.num_players,
            "skin": self.skin,
        }
        if self.seed is not None:
            body["seed"] = self.seed

        resp = client.post(f"{self.server_url}/api/lobbies", json=body)
        resp.raise_for_status()
        data = resp.json()
        self.game_id = data["game_id"]
        self.tokens = data["tokens"]
        return data

    def start_game(self, client: httpx.Client) -> dict:
        """POST /api/games/{id}/start."""
        resp = client.post(f"{self.server_url}/api/games/{self.game_id}/start")
        resp.raise_for_status()
        return resp.json()

    # ── player setup ─────────────────────────────────────────────────────

    def setup_players(self, client: httpx.Client) -> None:
        """Set up player agents (bots or Claude Code sessions)."""
        if self.bot_mode:
            self._spawn_bots()
        else:
            self._setup_claude_sessions(client)

    def _spawn_bots(self) -> None:
        """Create RandomBot instances for each player."""
        for token, player_id in self.tokens.items():
            bot = RandomBot(
                game_id=self.game_id,
                player_id=player_id,
                token=token,
                base_url=self.server_url,
                rng=random.Random(self._rng.randint(0, 2**32)),
            )
            self._bots.append(bot)

    def _setup_claude_sessions(self, client: httpx.Client) -> None:
        """Create a PlayerSession per player (no long-lived processes)."""
        from game.skins import SKIN_REGISTRY

        skin_cls = SKIN_REGISTRY.get(self.skin)
        premise = skin_cls().game_premise() if skin_cls else None

        for token, player_id in self.tokens.items():
            resp = client.get(
                f"{self.server_url}/api/games/{self.game_id}/observation",
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            obs = resp.json()
            role = obs["raw"]["your_role"]

            player_model = self.models[player_id] if self.models else self.model
            session = PlayerSession(
                game_id=self.game_id,
                player_id=player_id,
                token=token,
                server_url=self.server_url,
                skin=self.skin,
                role=role,
                num_players=self.num_players,
                game_premise=premise,
                model=player_model,
            )
            session.setup()
            self._sessions[player_id] = session
            print(f"  Player {player_id} ({role}) session ready  model={player_model}")

    # ── turn-driven game loop ────────────────────────────────────────────

    def run_game_loop(self, client: httpx.Client) -> dict:
        """Drive the game by invoking the correct player(s) each turn.

        In bot mode, bots submit actions directly (unchanged).
        In Claude mode, the orchestrator detects whose turn it is, builds a
        context-rich prompt, and invokes only the relevant player(s).
        """
        retries = 0
        last_pa_hash: str | None = None

        while True:
            status = self._get_status(client)

            if status["is_game_over"]:
                break

            pa = status.get("pending_action")
            if pa is None:
                time.sleep(self.poll_interval)
                continue

            # Bot mode — unchanged
            if self.bot_mode:
                self._bot_step(client, status)
                time.sleep(self.poll_interval)
                continue

            # Retry tracking: if pending_action hasn't changed, agent failed
            pa_hash = json.dumps(pa, sort_keys=True)
            if pa_hash == last_pa_hash:
                retries += 1
                if retries >= _MAX_RETRIES:
                    print(f"  WARNING: Action not submitted after {_MAX_RETRIES} retries, skipping turn")
                    retries = 0
                    last_pa_hash = None
                    time.sleep(self.poll_interval)
                    continue
            else:
                retries = 0
            last_pa_hash = pa_hash

            expected = pa["expected_action"]
            required = pa["required_by"]
            round_num = status.get("round", "?")

            if expected == "CastVote":
                # Discussion phase (optional)
                if self.discussion_time > 0:
                    self._run_discussion_phase(client, status, required)

                # Parallel voting
                print(f"  [Round {round_num}] Voting: players {required}")
                self._invoke_voters(required, status, pa)
            else:
                # Single-player action
                print(f"  [Round {round_num}] {expected} -> Player {required}")
                self._invoke_single_player(required, status, pa)

                # Check for post-legislative discussion
                self._maybe_run_discussion(client, status)

            time.sleep(self.poll_interval)

        return self.collect_results(client)

    # ── invocation helpers ───────────────────────────────────────────────

    def _invoke_single_player(
        self, player_id: int, status: dict, pa: dict,
    ) -> None:
        """Invoke one player to take their action."""
        session = self._sessions.get(player_id)
        if session is None:
            print(f"    WARNING: No session for player {player_id}")
            return

        prompt = self._build_turn_prompt(status, pa, pa["expected_action"])
        result = session.invoke_turn(
            prompt, self.max_turns_action, int(self.action_timeout),
        )
        if result.timed_out:
            print(f"    Player {player_id} timed out")

    def _invoke_voters(
        self, voter_ids: list[int], status: dict, pa: dict,
    ) -> None:
        """Invoke all voters in parallel."""
        prompt = self._build_turn_prompt(status, pa, "CastVote")

        with ThreadPoolExecutor(max_workers=len(voter_ids)) as pool:
            futures = {}
            for pid in voter_ids:
                session = self._sessions.get(pid)
                if session is None:
                    continue
                future = pool.submit(
                    session.invoke_turn,
                    prompt, self.max_turns_action, int(self.action_timeout),
                )
                futures[future] = pid

            for future in as_completed(futures):
                pid = futures[future]
                try:
                    result = future.result()
                    if result.timed_out:
                        print(f"    Player {pid} vote timed out")
                except Exception as exc:
                    print(f"    Player {pid} vote error: {exc}")

    def _run_discussion_phase(
        self, client: httpx.Client, status: dict, alive_ids: list[int],
    ) -> None:
        """Invoke all alive players in parallel for discussion, then close."""
        round_num = status.get("round", "?")
        print(f"  [Round {round_num}] Discussion open...")

        disc = self._get_discussion(client)
        prompt = self._build_discussion_prompt(status, disc)

        with ThreadPoolExecutor(max_workers=len(alive_ids)) as pool:
            futures = {}
            for pid in alive_ids:
                session = self._sessions.get(pid)
                if session is None:
                    continue
                future = pool.submit(
                    session.invoke_turn,
                    prompt, self.max_turns_discussion, int(self.action_timeout),
                )
                futures[future] = pid

            for future in as_completed(futures):
                pid = futures[future]
                try:
                    result = future.result()
                    if result.timed_out:
                        print(f"    Player {pid} discussion timed out")
                except Exception as exc:
                    print(f"    Player {pid} discussion error: {exc}")

        self._close_discussion(client)
        print(f"  [Round {round_num}] Discussion closed.")

    def _maybe_run_discussion(
        self, client: httpx.Client, status: dict,
    ) -> None:
        """If a post-legislative discussion opened, run it."""
        if self.discussion_time <= 0:
            return
        disc = self._get_discussion(client)
        if disc is None or not disc.get("is_open"):
            return

        alive_ids = list(self._sessions.keys())
        self._run_discussion_phase(client, status, alive_ids)

    # ── prompt builders ──────────────────────────────────────────────────

    def _build_turn_prompt(
        self, status: dict, pa: dict, action_type: str,
    ) -> str:
        """Build a context-rich prompt for a specific turn action."""
        round_num = status.get("round", "?")
        phase = pa.get("phase", "")
        targets = pa.get("legal_targets")

        parts = [f"=== TURN: Round {round_num}, Phase {phase} ==="]

        if action_type == "NominateChancellor":
            parts.append(
                f"You are President. Nominate a Chancellor from: {targets}\n"
                "Call get_observation() to review the game state, think about "
                "strategy, then submit_action('nominate', '{\"target_id\": <id>}')."
            )
        elif action_type == "CastVote":
            parts.append(
                "Vote on the proposed government. Call get_observation() to "
                "see the nominee, optionally get_discussion() for context, "
                "then submit_action('vote', '{\"vote\": true}') for Ja "
                "or submit_action('vote', '{\"vote\": false}') for Nein."
            )
        elif action_type == "PresidentDiscard":
            parts.append(
                "You are President. You drew 3 policy tiles. "
                "Call get_observation() to see drawn_policies, then "
                "submit_action('president_discard', '{\"discard_index\": <0|1|2>}')."
            )
        elif action_type == "ChancellorEnact":
            veto_note = ""
            if targets and None in targets:
                veto_note = (
                    " Veto power is unlocked — you may propose a veto "
                    "with enact_index=null."
                )
            parts.append(
                f"You are Chancellor. You received 2 policy tiles.{veto_note} "
                "Call get_observation() to see received_policies, then "
                "submit_action('chancellor_enact', '{\"enact_index\": <0|1>}')."
            )
        elif action_type == "VetoResponse":
            parts.append(
                "The Chancellor proposed a veto. As President, consent (true) "
                "or refuse (false). Call get_observation(), then "
                "submit_action('veto_response', '{\"consent\": true|false}')."
            )
        elif action_type == "InvestigatePlayer":
            parts.append(
                f"You must investigate a player's loyalty. Targets: {targets}\n"
                "Call get_observation(), then "
                "submit_action('investigate', '{\"target_id\": <id>}')."
            )
        elif action_type == "PolicyPeekAck":
            parts.append(
                "You may peek at the top 3 policies. Call get_observation() "
                "to see peeked_policies, then "
                "submit_action('peek_ack', '{}') to acknowledge."
            )
        elif action_type == "SpecialElection":
            parts.append(
                f"You must call a Special Election. Targets: {targets}\n"
                "Call get_observation(), then "
                "submit_action('special_election', '{\"target_id\": <id>}')."
            )
        elif action_type == "ExecutePlayer":
            parts.append(
                f"You must execute a player. Targets: {targets}\n"
                "Call get_observation(), then "
                "submit_action('execute', '{\"target_id\": <id>}')."
            )
        else:
            parts.append(
                f"Action required: {action_type}. "
                "Call get_game_status() and get_observation() to decide."
            )

        return "\n".join(parts)

    def _build_discussion_prompt(
        self, status: dict, discussion: dict | None,
    ) -> str:
        """Build a prompt for the discussion phase."""
        round_num = status.get("round", "?")
        parts = [
            f"=== DISCUSSION: Round {round_num} ===",
            "A discussion window is open before the vote. Share your "
            "thoughts, accuse other players, defend yourself, or strategize.",
            "",
            "Call get_discussion() to read what others have said, "
            "then speak('your message') to contribute.",
            "Call get_observation() if you need to review the game state.",
            "",
            "IMPORTANT: Do NOT call submit_action during discussion. "
            "Only use speak() and observation tools.",
        ]
        if discussion and discussion.get("messages"):
            parts.append(
                f"\n{len(discussion['messages'])} messages already posted."
            )
        return "\n".join(parts)

    # ── server helpers ───────────────────────────────────────────────────

    def _bot_step(self, client: httpx.Client, status: dict) -> None:
        """Have each bot attempt to act."""
        for bot in self._bots:
            try:
                bot.act(client)
            except httpx.HTTPStatusError:
                pass

    def _get_status(self, client: httpx.Client) -> dict:
        """Get game status using the first available token."""
        if not self.tokens:
            raise RuntimeError("No tokens available")
        token = next(iter(self.tokens))
        resp = client.get(
            f"{self.server_url}/api/games/{self.game_id}/status",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        return resp.json()

    def _close_discussion(self, client: httpx.Client) -> None:
        """Close the current discussion window."""
        resp = client.post(
            f"{self.server_url}/api/games/{self.game_id}/close-discussion"
        )
        resp.raise_for_status()

    def _get_discussion(self, client: httpx.Client) -> dict | None:
        """Fetch the current discussion state."""
        if not self.tokens:
            return None
        token = next(iter(self.tokens))
        resp = client.get(
            f"{self.server_url}/api/games/{self.game_id}/discussion",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        data = resp.json()
        return data if data.get("is_open") else None

    def collect_results(self, client: httpx.Client) -> dict:
        """GET /api/games/{id}/result and return the result."""
        resp = client.get(f"{self.server_url}/api/games/{self.game_id}/result")
        resp.raise_for_status()
        return resp.json()

    # ── full lifecycle ───────────────────────────────────────────────────

    def run(self) -> dict:
        """Run the full orchestration flow: create, start, setup, loop, collect."""
        with httpx.Client(timeout=30.0) as client:
            lobby = self.create_lobby(client)
            print(f"Lobby created: game_id={lobby['game_id']}, players={lobby['num_players']}")
            print(f"  Skin: {self.skin}, Seed: {self.seed}")

            self.start_game(client)
            print("Game started.")

            self.setup_players(client)
            if self.bot_mode:
                mode = "bot mode"
            elif self.models:
                mode = "Claude Code (mixed: " + ", ".join(self.models) + ")"
            else:
                mode = f"Claude Code ({self.model})"
            print(f"Players ready ({mode}).")
            print()

            result = self.run_game_loop(client)

            print(f"\nGame over!")
            print(f"  Winner: {result['result']['winner']}")
            print(f"  Condition: {result['result']['condition']}")
            print(f"  Final round: {result['result']['final_round']}")
            if not self.bot_mode:
                log_dir = Path("logs") / "games" / self.game_id
                print(f"  Transcripts: {log_dir}")

            return result


# ─── CLI ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Secret Hitler game orchestrator",
        prog="python -m agents.orchestrator",
    )
    parser.add_argument(
        "--server-url",
        default="http://127.0.0.1:8000",
        help="Base URL of the game server (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--players",
        type=int,
        default=5,
        help="Number of players (5-10, default: 5)",
    )
    parser.add_argument(
        "--skin",
        default="secret_hitler",
        choices=["secret_hitler", "corporate_board"],
        help="Narrative skin (default: secret_hitler)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility",
    )
    parser.add_argument(
        "--bot-mode",
        action="store_true",
        help="Use random-action bots instead of Claude Code",
    )
    parser.add_argument(
        "--discussion-time",
        type=float,
        default=30.0,
        help="Seconds to wait for discussion before closing (default: 30)",
    )
    parser.add_argument(
        "--model",
        default="claude-sonnet-4-6",
        help="Claude model for agents (default: claude-sonnet-4-6)",
    )
    parser.add_argument(
        "--max-turns-action",
        type=int,
        default=10,
        help="Max tool-use rounds per action invocation (default: 10)",
    )
    parser.add_argument(
        "--max-turns-discussion",
        type=int,
        default=5,
        help="Max tool-use rounds per discussion invocation (default: 5)",
    )
    args = parser.parse_args()

    orch = GameOrchestrator(
        server_url=args.server_url,
        num_players=args.players,
        skin=args.skin,
        seed=args.seed,
        bot_mode=args.bot_mode,
        discussion_time=args.discussion_time,
        model=args.model,
        max_turns_action=args.max_turns_action,
        max_turns_discussion=args.max_turns_discussion,
    )
    orch.run()


if __name__ == "__main__":
    main()
