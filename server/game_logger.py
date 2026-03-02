"""JSONL-based game logger.

Each game gets its own directory under ``logs/games/{game_id}/`` containing:
- ``metadata.json``  – static game metadata (players, skin, seed, etc.)
- ``events.jsonl``   – one JSON object per line for every game event
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class GameLogger:
    """Append-only logger that writes structured JSON to disk."""

    def __init__(self, game_id: str, base_dir: str | Path = "logs/games") -> None:
        self._game_id = game_id
        self._dir = Path(base_dir) / game_id
        self._dir.mkdir(parents=True, exist_ok=True)
        self._events_path = self._dir / "events.jsonl"
        self._metadata_path = self._dir / "metadata.json"

    @property
    def log_dir(self) -> Path:
        return self._dir

    # ── writers ───────────────────────────────────────────────────────────

    def log_metadata(self, metadata: dict[str, Any]) -> None:
        """Write (or overwrite) the game metadata file."""
        self._metadata_path.write_text(
            json.dumps(metadata, default=str, indent=2), encoding="utf-8"
        )

    def log_observation(self, player_id: int, observation: dict) -> None:
        self._append_event({
            "type": "observation",
            "player_id": player_id,
            "data": observation,
        })

    def log_action(self, player_id: int, action_type: str, payload: dict, result: dict) -> None:
        self._append_event({
            "type": "action",
            "player_id": player_id,
            "action_type": action_type,
            "payload": payload,
            "result": result,
        })

    def log_discussion(self, player_id: int, window: str, message: str) -> None:
        self._append_event({
            "type": "discussion",
            "player_id": player_id,
            "window": window,
            "message": message,
        })

    def log_game_result(self, result: dict) -> None:
        self._append_event({
            "type": "game_result",
            "data": result,
        })

    # ── internals ────────────────────────────────────────────────────────

    def _append_event(self, event: dict[str, Any]) -> None:
        event["timestamp"] = datetime.now(timezone.utc).isoformat()
        with open(self._events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str) + "\n")
