"""Game orchestrator: creates lobbies, sets up player sessions, drives turn-by-turn play.

Run with::

    uv run python -m orchestration --bot-mode --players 5 --seed 42
    uv run python -m orchestration --config examples/game_config.yaml
    uv run python -m orchestration --status          # live game dashboard
    uv run python -m orchestration --status GAME_ID  # specific game
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
from agents.types import AgentConfig
from dotenv import load_dotenv

from orchestration.backends import BasePlayerSession, create_session, parse_model_spec

# ─── Bot player (random-action, for testing) ────────────────────────────────


class RandomBot:
    """A simple bot that picks random legal actions via the REST API."""

    def __init__(
        self,
        game_id: str,
        player_id: int,
        token: str,
        base_url: str,
        rng: random.Random,
    ) -> None:
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
_MAX_SKIP_CYCLES = 5  # max consecutive skip-retry cycles for the same pending action


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
        *,
        bot_mode: bool = False,
        discussion_rounds: int = 2,
        poll_interval: float = 0.5,
        action_timeout: float = 300.0,
        model: str = "claude-sonnet-4-6",
        models: list[str] | None = None,
        max_turns_action: int = 10,
        max_turns_discussion: int = 5,
        discussion_timeout: int = 60,
        agent_config: AgentConfig | None = None,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.num_players = num_players
        self.skin = skin
        self.seed = seed
        self.bot_mode = bot_mode
        self.discussion_rounds = discussion_rounds
        self.poll_interval = poll_interval
        self.action_timeout = action_timeout
        self.model = model
        self.models = models
        self.max_turns_action = max_turns_action
        self.max_turns_discussion = max_turns_discussion
        self.discussion_timeout = discussion_timeout
        self.agent_config = agent_config

        self.game_id: str | None = None
        self.tokens: dict[str, int] = {}
        self._bots: list[RandomBot] = []
        self._sessions: dict[int, BasePlayerSession] = {}
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
        """Set up player agents (bots or CLI sessions)."""
        if self.bot_mode:
            self._spawn_bots()
        else:
            self._setup_agent_sessions(client)

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

    def _setup_agent_sessions(self, client: httpx.Client) -> None:
        """Create a session per player using the appropriate backend."""
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

            player_model_spec = self.models[player_id] if self.models else self.model
            backend, model_name = parse_model_spec(player_model_spec)

            session = create_session(
                backend=backend,
                game_id=self.game_id,
                player_id=player_id,
                token=token,
                server_url=self.server_url,
                skin=self.skin,
                role=role,
                num_players=self.num_players,
                game_premise=premise,
                model=model_name,
                agent_config=self.agent_config,
            )
            session.setup()
            self._sessions[player_id] = session
            print(
                f"  Player {player_id} ({role}) session ready  backend={backend}  model={model_name}",
            )

    # ── turn-driven game loop ────────────────────────────────────────────

    def run_game_loop(self, client: httpx.Client) -> dict:
        """Drive the game by invoking the correct player(s) each turn.

        In bot mode, bots submit actions directly (unchanged).
        In Claude mode, the orchestrator detects whose turn it is, builds a
        context-rich prompt, and invokes only the relevant player(s).
        """
        retries = 0
        skip_cycles = 0
        last_pa_hash: str | None = None
        skipped_pa_hash: str | None = None  # tracks the PA that keeps failing
        discussion_run_for_round: int | None = None  # prevent re-running discussion as voters trickle in

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
                self._write_status("bot_step", f"Round {status.get('round', '?')}")
                time.sleep(self.poll_interval)
                continue

            # Retry tracking: if pending_action hasn't changed, agent failed
            pa_hash = json.dumps(pa, sort_keys=True)
            if pa_hash == last_pa_hash:
                retries += 1
                if retries >= _MAX_RETRIES:
                    # Track how many times we've skipped for the same underlying PA
                    if pa_hash == skipped_pa_hash:
                        skip_cycles += 1
                    else:
                        skipped_pa_hash = pa_hash
                        skip_cycles = 1

                    if skip_cycles >= _MAX_SKIP_CYCLES:
                        player_info = pa.get("required_by", "unknown")
                        action_info = pa.get("expected_action", "unknown")
                        raise RuntimeError(
                            f"Player {player_info} failed to submit {action_info} "
                            f"after {_MAX_SKIP_CYCLES * _MAX_RETRIES} total attempts. "
                            f"Aborting game to prevent infinite loop.",
                        )

                    print(
                        f"  WARNING: Action not submitted after {_MAX_RETRIES} retries, skipping turn",
                    )
                    retries = 0
                    last_pa_hash = None
                    time.sleep(self.poll_interval)
                    continue
            else:
                retries = 0
                skipped_pa_hash = None
                skip_cycles = 0
            last_pa_hash = pa_hash

            expected = pa["expected_action"]
            required = pa["required_by"]
            round_num = status.get("round", "?")

            if expected == "CastVote":
                # Discussion phase (optional) — run at most once per game round
                if self.discussion_rounds > 0 and round_num != discussion_run_for_round:
                    self._write_status("discussion", f"Round {round_num} pre-vote")
                    self._run_discussion_phase(client, status, required)
                    discussion_run_for_round = round_num

                # Parallel voting
                print(f"  [Round {round_num}] Voting: players {required}")
                self._write_status("voting", f"Round {round_num}")
                self._invoke_voters(required, status, pa)
                self._write_status("voted", f"Round {round_num}")
            else:
                # Single-player action
                print(f"  [Round {round_num}] {expected} -> Player {required}")
                self._write_status(expected, f"Round {round_num} Player {required}")
                self._invoke_single_player(required, status, pa)
                self._write_status("action_done", f"{expected} by Player {required}")

                # Check for post-action discussion (e.g., pre_vote after
                # nomination, post_legislative after policy enactment).
                # If it ran, mark this round so the CastVote branch doesn't
                # try to open a second discussion on the same round.
                if self._try_run_discussion(client, status):
                    discussion_run_for_round = round_num

            time.sleep(self.poll_interval)

        return self.collect_results(client)

    # ── invocation helpers ───────────────────────────────────────────────

    def _invoke_single_player(
        self,
        player_id: int,
        status: dict,
        pa: dict,
    ) -> None:
        """Invoke one player to take their action."""
        session = self._sessions.get(player_id)
        if session is None:
            print(f"    WARNING: No session for player {player_id}")
            return

        prompt = self._build_turn_prompt(status, pa, pa["expected_action"])
        result = session.invoke_turn(
            prompt,
            self.max_turns_action,
            int(self.action_timeout),
        )
        if result.timed_out:
            print(f"    Player {player_id} timed out")

    def _invoke_players_in_parallel(
        self,
        player_ids: list[int],
        prompt: str,
        max_turns: int,
        timeout: int,
        label: str = "action",
    ) -> None:
        """Invoke multiple players in parallel with consistent error handling."""
        with ThreadPoolExecutor(max_workers=len(player_ids)) as pool:
            futures = {}
            for pid in player_ids:
                session = self._sessions.get(pid)
                if session is None:
                    continue
                future = pool.submit(session.invoke_turn, prompt, max_turns, timeout)
                futures[future] = pid
            for future in as_completed(futures):
                pid = futures[future]
                try:
                    result = future.result()
                    if result.timed_out:
                        print(f"    Player {pid} {label} timed out")
                except Exception as exc:
                    print(f"    Player {pid} {label} error: {exc}")

    def _invoke_voters(
        self,
        voter_ids: list[int],
        status: dict,
        pa: dict,
    ) -> None:
        """Invoke all voters in parallel."""
        prompt = self._build_turn_prompt(status, pa, "CastVote")
        self._invoke_players_in_parallel(
            voter_ids,
            prompt,
            self.max_turns_action,
            int(self.action_timeout),
            "vote",
        )

    def _run_discussion_phase(
        self,
        client: httpx.Client,
        status: dict,
        alive_ids: list[int],
    ) -> None:
        """Run multiple discussion rounds so players can read and respond.

        Each round invokes all alive players in parallel. Between rounds,
        players see what others said in earlier rounds via get_discussion().
        """
        round_num = status.get("round", "?")
        print(
            f"  [Round {round_num}] Discussion open ({self.discussion_rounds} rounds)...",
        )

        for disc_round in range(1, self.discussion_rounds + 1):
            disc = self._get_discussion(client)
            prompt = self._build_discussion_prompt(status, disc)

            print(f"    Discussion round {disc_round}/{self.discussion_rounds}")
            self._invoke_players_in_parallel(
                alive_ids,
                prompt,
                self.max_turns_discussion,
                self.discussion_timeout,
                "discussion",
            )

        self._close_discussion(client)
        print(f"  [Round {round_num}] Discussion closed.")

    def _try_run_discussion(
        self,
        client: httpx.Client,
        status: dict,
    ) -> bool:
        """If a discussion window is open, run it and return True."""
        if self.discussion_rounds <= 0:
            return False
        disc = self._get_discussion(client)
        if disc is None or not disc.get("is_open"):
            return False

        alive_ids = list(self._sessions.keys())
        self._run_discussion_phase(client, status, alive_ids)
        return True

    # ── prompt builders ──────────────────────────────────────────────────

    def _build_turn_prompt(
        self,
        status: dict,
        pa: dict,
        action_type: str,
    ) -> str:
        """Build a context-rich prompt for a specific turn action."""
        round_num = status.get("round", "?")
        phase = pa.get("phase", "")
        targets = pa.get("legal_targets")

        parts = [
            f"=== TURN: Round {round_num}, Phase {phase} ===",
            f"You have {int(self.action_timeout)} seconds to act.",
        ]

        if action_type == "NominateChancellor":
            parts.append(
                f"You are President. Nominate a Chancellor from: {targets}\n"
                "Call get_observation() to review the game state, think about "
                "strategy, then submit_action('nominate', {\"target_id\": <id>}).",
            )
        elif action_type == "CastVote":
            parts.append(
                "Vote on the proposed government. Call get_observation() to "
                "see the nominee, optionally get_discussion() for context, "
                "then submit_action('vote', {\"vote\": true}) for Ja "
                "or submit_action('vote', {\"vote\": false}) for Nein.",
            )
        elif action_type == "PresidentDiscard":
            parts.append(
                "You are President. You drew 3 policy tiles. "
                "Call get_observation() to see drawn_policies, then "
                "submit_action('president_discard', {\"discard_index\": <0|1|2>}).",
            )
        elif action_type == "ChancellorEnact":
            veto_note = ""
            if targets and None in targets:
                veto_note = " Veto power is unlocked — you may propose a veto with enact_index=null."
            parts.append(
                f"You are Chancellor. You received 2 policy tiles.{veto_note} "
                "Call get_observation() to see received_policies, then "
                "submit_action('chancellor_enact', {\"enact_index\": <0|1>}).",
            )
        elif action_type == "VetoResponse":
            parts.append(
                "The Chancellor proposed a veto. As President, consent (true) "
                "or refuse (false). Call get_observation(), then "
                "submit_action('veto_response', {\"consent\": true|false}).",
            )
        elif action_type == "InvestigatePlayer":
            parts.append(
                f"You must investigate a player's loyalty. Targets: {targets}\n"
                "Call get_observation(), then "
                "submit_action('investigate', {\"target_id\": <id>}).",
            )
        elif action_type == "PolicyPeekAck":
            parts.append(
                "You may peek at the top 3 policies. Call get_observation() "
                "to see peeked_policies, then "
                "submit_action('peek_ack', {}) to acknowledge.",
            )
        elif action_type == "SpecialElection":
            parts.append(
                f"You must call a Special Election. Targets: {targets}\n"
                "Call get_observation(), then "
                "submit_action('special_election', {\"target_id\": <id>}).",
            )
        elif action_type == "ExecutePlayer":
            parts.append(
                f"You must execute a player. Targets: {targets}\n"
                "Call get_observation(), then "
                "submit_action('execute', {\"target_id\": <id>}).",
            )
        else:
            parts.append(
                f"Action required: {action_type}. Call get_game_status() and get_observation() to decide.",
            )

        return "\n".join(parts)

    def _build_discussion_prompt(
        self,
        status: dict,
        discussion: dict | None,
    ) -> str:
        """Build a prompt for the discussion phase."""
        round_num = status.get("round", "?")
        parts = [
            f"=== DISCUSSION: Round {round_num} ===",
            f"You have {self.discussion_timeout} seconds for this discussion turn.",
            "A discussion window is open before the vote. Share your "
            "thoughts, accuse other players, defend yourself, or strategize.",
            "",
            "Call get_discussion() to read what others have said, then speak('your message') to contribute.",
            "Call get_observation() if you need to review the game state.",
            "",
            "IMPORTANT: Do NOT call submit_action during discussion. "
            "Only use speak() and observation tools. Be concise and act quickly.",
        ]
        if discussion and discussion.get("messages"):
            parts.append(f"\n{len(discussion['messages'])} messages already posted.")
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
            f"{self.server_url}/api/games/{self.game_id}/close-discussion",
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

    def _write_status(self, phase: str, detail: str = "") -> None:
        """Write a status.json snapshot to the game log directory."""
        if self.game_id is None:
            return
        log_dir = Path("logs") / "games" / self.game_id
        if not log_dir.exists():
            return

        # Parse events.jsonl for board state
        events_path = log_dir / "events.jsonl"
        policies: list[str] = []
        elections: list[dict] = []
        disc_count = 0
        action_count = 0
        last_ts = ""
        if events_path.exists():
            for line in events_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                ev = json.loads(line)
                last_ts = ev.get("timestamp", last_ts)
                if ev["type"] == "action":
                    action_count += 1
                    result = ev.get("result", {})
                    if result.get("event") == "policy_enacted":
                        policies.append(result["policy"])
                    elif result.get("event") == "election_result":
                        elections.append(result)
                elif ev["type"] == "discussion":
                    disc_count += 1

        liberal = sum(1 for p in policies if p == "liberal")
        fascist = sum(1 for p in policies if p == "fascist")

        status = {
            "game_id": self.game_id,
            "phase": phase,
            "detail": detail,
            "board": {"liberal": liberal, "fascist": fascist},
            "elections": len(elections),
            "actions": action_count,
            "discussion_messages": disc_count,
            "policies": policies,
            "last_timestamp": last_ts,
        }
        (log_dir / "status.json").write_text(
            json.dumps(status, indent=2),
            encoding="utf-8",
        )

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
            print(
                f"Lobby created: game_id={lobby['game_id']}, players={lobby['num_players']}",
            )
            print(f"  Skin: {self.skin}, Seed: {self.seed}")

            self.start_game(client)
            print("Game started.")

            self._write_status("setup", "Setting up players")
            self.setup_players(client)
            if self.bot_mode:
                mode = "bot mode"
            elif self.models:
                backends = {parse_model_spec(m)[0] for m in self.models}
                if len(backends) > 1:
                    mode = "Mixed backends (" + ", ".join(self.models) + ")"
                else:
                    mode = f"{backends.pop()} (" + ", ".join(self.models) + ")"
            else:
                backend, model_name = parse_model_spec(self.model)
                mode = f"{backend} ({model_name})"
            print(f"Players ready ({mode}).")
            print()

            result = self.run_game_loop(client)

            self._write_status("game_over", f"{result['result']['winner']} wins")
            print("\nGame over!")
            print(f"  Winner: {result['result']['winner']}")
            print(f"  Condition: {result['result']['condition']}")
            print(f"  Final round: {result['result']['final_round']}")
            if not self.bot_mode:
                log_dir = Path("logs") / "games" / self.game_id
                print(f"  Transcripts: {log_dir}")

            return result


# ─── Config loading ──────────────────────────────────────────────────────────


def load_config(path: str | Path) -> dict[str, Any]:
    """Load a YAML game configuration file.

    Returns a dict with keys matching CLI argument names (snake_case).
    """
    import yaml

    config_path = Path(path)
    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(
            f"Config file must be a YAML mapping, got {type(data).__name__}",
        )
    return data


# ─── Status dashboard ────────────────────────────────────────────────────────


def print_game_status(game_id: str | None = None) -> None:
    """Print a dashboard for a game by reading its events.jsonl.

    If *game_id* is None, uses the most recently modified game directory.
    """
    games_dir = Path("logs") / "games"
    if not games_dir.exists():
        print("No games found in logs/games/")
        return

    if game_id:
        game_dir = games_dir / game_id
    else:
        # Most recently modified game directory
        candidates = sorted(
            games_dir.iterdir(),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            print("No games found in logs/games/")
            return
        game_dir = candidates[0]
        game_id = game_dir.name

    events_path = game_dir / "events.jsonl"
    status_path = game_dir / "status.json"

    # Quick status from status.json if available
    if status_path.exists():
        st = json.loads(status_path.read_text(encoding="utf-8"))
        print(f"Game:  {st['game_id']}")
        print(f"Phase: {st['phase']} — {st['detail']}")
        print(f"Board: {st['board']['liberal']}L / {st['board']['fascist']}F")
        print(
            f"Elections: {st['elections']}  Actions: {st['actions']}  Discussion: {st['discussion_messages']} msgs",
        )
        if st.get("last_timestamp"):
            print(f"Last activity: {st['last_timestamp']}")
        print()

    if not events_path.exists():
        print(f"No events.jsonl in {game_dir}")
        return

    # Full parse for detailed dashboard
    events = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))

    policies: list[str] = []
    elections: list[dict] = []
    disc_msgs: list[dict] = []
    actions: list[dict] = []
    for ev in events:
        if ev["type"] == "action":
            actions.append(ev)
            result = ev.get("result", {})
            if result.get("event") == "policy_enacted":
                policies.append(result["policy"])
            elif result.get("event") == "election_result":
                elections.append(ev)
        elif ev["type"] == "discussion":
            disc_msgs.append(ev)

    lib = sum(1 for p in policies if p == "liberal")
    fas = sum(1 for p in policies if p == "fascist")

    print(f"=== Game {game_id} ===")
    print(
        f"Events: {len(events)}  |  Actions: {len(actions)}  |  Discussion: {len(disc_msgs)} msgs",
    )
    print()

    # Board
    lib_bar = "L" * lib + "." * (5 - lib)
    fas_bar = "F" * fas + "." * (6 - fas)
    print(f"Liberal:  [{lib_bar}]  {lib}/5")
    print(f"Fascist:  [{fas_bar}]  {fas}/6")
    print()

    # Elections
    if elections:
        print("Elections:")
        for i, el in enumerate(elections, 1):
            r = el["result"]
            outcome = "PASSED" if r["elected"] else "FAILED"
            print(f"  R{i}: Ja={r['ja']} Nein={r['nein']}  {outcome}")
        print()

    # Policy history
    if policies:
        print("Policy track: " + " -> ".join(p[0].upper() for p in policies))
        print()

    # Discussion summary
    if disc_msgs:
        print(f"Discussion ({len(disc_msgs)} messages):")
        for msg in disc_msgs[-5:]:  # last 5 messages
            text = msg["message"][:100]
            if len(msg["message"]) > 100:
                text += "..."
            print(f"  P{msg['player_id']} [{msg.get('window', '')}]: {text}")
        if len(disc_msgs) > 5:
            print(f"  ... ({len(disc_msgs) - 5} earlier messages)")
        print()

    # Timestamps
    if events:
        t0 = events[0]["timestamp"]
        t1 = events[-1]["timestamp"]
        print(f"Started:  {t0}")
        print(f"Last:     {t1}")


# ─── CLI ─────────────────────────────────────────────────────────────────────


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Secret Hitler game orchestrator",
        prog="python -m orchestration",
    )
    parser.add_argument(
        "--server-url",
        default="http://127.0.0.1:8000",
        help="Base URL of the game server (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--players",
        type=int,
        default=None,
        help="Number of players (5-10, default: 5)",
    )
    parser.add_argument(
        "--skin",
        default=None,
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
        "--discussion-rounds",
        type=int,
        default=None,
        help="Number of discussion rounds before each vote (default: 2, 0 to disable)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model spec for all agents, e.g. claudecode:claude-sonnet-4-6 (default: claude-sonnet-4-6)",
    )
    parser.add_argument(
        "--models",
        default=None,
        help=(
            "Comma-separated model specs, one per player. "
            "Format: backend:model (e.g. claudecode:claude-sonnet-4-6,opencode:openai/gpt-4-turbo)"
        ),
    )
    parser.add_argument(
        "--discussion-timeout",
        type=int,
        default=None,
        help="Timeout in seconds per discussion invocation (default: 60)",
    )
    parser.add_argument(
        "--max-turns-action",
        type=int,
        default=None,
        help="Max tool-use rounds per action invocation (default: 10)",
    )
    parser.add_argument(
        "--max-turns-discussion",
        type=int,
        default=None,
        help="Max tool-use rounds per discussion invocation (default: 5)",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="Temperature for OpenRouter models (default: 1.0)",
    )
    parser.add_argument(
        "--compaction-ratio",
        type=float,
        default=None,
        help="Compact context at this fraction of model's context window (default: 0.75)",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to a YAML game config file (CLI args override config values)",
    )
    parser.add_argument(
        "--status",
        nargs="?",
        const="__latest__",
        default=None,
        metavar="GAME_ID",
        help="Show game status dashboard (latest game if no ID given)",
    )
    args = parser.parse_args()

    # Status mode — print dashboard and exit
    if args.status is not None:
        gid = None if args.status == "__latest__" else args.status
        print_game_status(gid)
        return

    # Defaults
    cfg: dict[str, Any] = {
        "server_url": "http://127.0.0.1:8000",
        "players": 5,
        "skin": "secret_hitler",
        "seed": None,
        "bot_mode": False,
        "discussion_rounds": 2,
        "discussion_timeout": 60,
        "model": "claude-sonnet-4-6",
        "models": None,
        "max_turns_action": 10,
        "max_turns_discussion": 5,
        "agent": {},
    }

    # Layer 1: config file
    if args.config:
        file_cfg = load_config(args.config)
        for key, value in file_cfg.items():
            if key in cfg:
                cfg[key] = value

    # Layer 2: CLI args override config (only if explicitly provided)
    if args.server_url != "http://127.0.0.1:8000":
        cfg["server_url"] = args.server_url
    if args.players is not None:
        cfg["players"] = args.players
    if args.skin is not None:
        cfg["skin"] = args.skin
    if args.seed is not None:
        cfg["seed"] = args.seed
    if args.bot_mode:
        cfg["bot_mode"] = True
    if args.discussion_rounds is not None:
        cfg["discussion_rounds"] = args.discussion_rounds
    if args.discussion_timeout is not None:
        cfg["discussion_timeout"] = args.discussion_timeout
    if args.model is not None:
        cfg["model"] = args.model
    if args.models is not None:
        cfg["models"] = [m.strip() for m in args.models.split(",")]
    if args.max_turns_action is not None:
        cfg["max_turns_action"] = args.max_turns_action
    if args.max_turns_discussion is not None:
        cfg["max_turns_discussion"] = args.max_turns_discussion

    # Build agent config from YAML + CLI overrides
    agent_dict = dict(cfg.get("agent", {}))
    if args.temperature is not None:
        agent_dict["temperature"] = args.temperature
    if args.compaction_ratio is not None:
        agent_dict["compaction_ratio"] = args.compaction_ratio
    agent_cfg = AgentConfig(**agent_dict)

    # Validate models length
    models = cfg["models"]
    if models is not None and len(models) != cfg["players"]:
        parser.error(
            f"--models has {len(models)} entries but --players is {cfg['players']}",
        )

    orch = GameOrchestrator(
        server_url=cfg["server_url"],
        num_players=cfg["players"],
        skin=cfg["skin"],
        seed=cfg["seed"],
        bot_mode=cfg["bot_mode"],
        discussion_rounds=cfg["discussion_rounds"],
        discussion_timeout=cfg["discussion_timeout"],
        model=cfg["model"],
        models=models,
        max_turns_action=cfg["max_turns_action"],
        max_turns_discussion=cfg["max_turns_discussion"],
        agent_config=agent_cfg,
    )
    orch.run()


if __name__ == "__main__":
    main()
