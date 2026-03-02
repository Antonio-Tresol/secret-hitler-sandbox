"""Game orchestrator: creates lobbies, spawns players, and manages game flow.

Run with::

    uv run python -m agents.orchestrator --bot-mode --players 5 --seed 42
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from typing import Any

import httpx

from agents.claude_code_launcher import build_mcp_config, build_system_prompt, spawn_player


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


class GameOrchestrator:
    """Manages a full game lifecycle: lobby creation, player spawning, game loop."""

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

        self.game_id: str | None = None
        self.tokens: dict[str, int] = {}
        self._bots: list[RandomBot] = []
        self._processes: list = []
        self._file_handles: list = []
        self._rng = random.Random(seed)

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

    def spawn_players(self, client: httpx.Client) -> None:
        """Spawn player agents (bots or Claude Code instances)."""
        if self.bot_mode:
            self._spawn_bots()
        else:
            self._spawn_claude_code_players(client)

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

    def _spawn_claude_code_players(self, client: httpx.Client) -> None:
        """Spawn Claude Code subprocess for each player."""
        # Get the skin's game premise for system prompts
        from game.skins import SKIN_REGISTRY

        skin_cls = SKIN_REGISTRY.get(self.skin)
        premise = skin_cls().game_premise() if skin_cls else None

        for token, player_id in self.tokens.items():
            # Get the player's role from their observation
            resp = client.get(
                f"{self.server_url}/api/games/{self.game_id}/observation",
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            obs = resp.json()
            role = obs["raw"]["your_role"]

            proc, fhs = spawn_player(
                game_id=self.game_id,
                player_id=player_id,
                token=token,
                server_url=self.server_url,
                skin=self.skin,
                role=role,
                num_players=self.num_players,
                game_premise=premise,
                model=self.model,
            )
            self._processes.append(proc)
            self._file_handles.extend(fhs)
            print(f"  Player {player_id} ({role}) spawned [PID {proc.pid}]")

    def run_game_loop(self, client: httpx.Client) -> dict:
        """Poll game status and manage the game until completion.

        In bot mode, bots submit actions directly. With Claude Code, the
        orchestrator polls until actions appear and manages discussion windows.

        Returns the final game result.
        """
        last_phase = None
        while True:
            status = self._get_status(client)

            if status["is_game_over"]:
                break

            pa = status.get("pending_action")
            if pa is None:
                time.sleep(self.poll_interval)
                continue

            current_phase = pa.get("phase")

            # Handle discussion windows (close after discussion_time)
            if pa["expected_action"] == "CastVote" and self.discussion_time > 0:
                if current_phase != last_phase:
                    # New discussion window — give agents time to speak
                    print(f"  [Round {status.get('round', '?')}] Discussion open ({self.discussion_time}s)...")
                    time.sleep(self.discussion_time)
                    self._close_discussion(client)
                    print(f"  [Round {status.get('round', '?')}] Discussion closed.")

            last_phase = current_phase

            if self.bot_mode:
                self._bot_step(client, status)
            else:
                # For Claude Code mode: poll until action submitted or timeout
                self._wait_for_action(client)

            time.sleep(self.poll_interval)

        return self.collect_results(client)

    def _bot_step(self, client: httpx.Client, status: dict) -> None:
        """Have each bot attempt to act."""
        for bot in self._bots:
            try:
                bot.act(client)
            except httpx.HTTPStatusError:
                pass  # Action might fail if it's not this bot's turn

    def _get_status(self, client: httpx.Client) -> dict:
        """Get game status (unauthenticated, uses first token)."""
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

    def _wait_for_action(self, client: httpx.Client) -> None:
        """Poll until the pending action changes (i.e., someone acted) or timeout."""
        initial_status = self._get_status(client)
        initial_pa = json.dumps(initial_status.get("pending_action"), sort_keys=True)
        start = time.time()

        while time.time() - start < self.action_timeout:
            time.sleep(self.poll_interval)
            current = self._get_status(client)
            if current["is_game_over"]:
                return
            current_pa = json.dumps(current.get("pending_action"), sort_keys=True)
            if current_pa != initial_pa:
                return

    def collect_results(self, client: httpx.Client) -> dict:
        """GET /api/games/{id}/result and return the result."""
        resp = client.get(f"{self.server_url}/api/games/{self.game_id}/result")
        resp.raise_for_status()
        return resp.json()

    def run(self) -> dict:
        """Run the full orchestration flow: create, start, spawn, loop, collect."""
        with httpx.Client(timeout=30.0) as client:
            lobby = self.create_lobby(client)
            print(f"Lobby created: game_id={lobby['game_id']}, players={lobby['num_players']}")
            print(f"  Skin: {self.skin}, Seed: {self.seed}")

            self.start_game(client)
            print("Game started.")

            self.spawn_players(client)
            mode = "bot mode" if self.bot_mode else f"Claude Code ({self.model})"
            print(f"Players spawned ({mode}).")
            print()

            try:
                result = self.run_game_loop(client)
            finally:
                # Clean up Claude Code processes
                for proc in self._processes:
                    try:
                        proc.terminate()
                    except OSError:
                        pass
                for fh in self._file_handles:
                    try:
                        fh.close()
                    except OSError:
                        pass

            print(f"\nGame over!")
            print(f"  Winner: {result['result']['winner']}")
            print(f"  Condition: {result['result']['condition']}")
            print(f"  Final round: {result['result']['final_round']}")
            if not self.bot_mode:
                from pathlib import Path
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
    args = parser.parse_args()

    orch = GameOrchestrator(
        server_url=args.server_url,
        num_players=args.players,
        skin=args.skin,
        seed=args.seed,
        bot_mode=args.bot_mode,
        discussion_time=args.discussion_time,
        model=args.model,
    )
    orch.run()


if __name__ == "__main__":
    main()
