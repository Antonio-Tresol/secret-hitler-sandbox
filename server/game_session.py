"""GameSession: wraps GameEngine with discussion, skin translation, logging, and auth."""

from __future__ import annotations

import uuid
from typing import Any

from game.engine import GameEngine
from game.skins.base import BaseSkin
from game.types import (
    CastVote,
    ChancellorEnact,
    ExecutePlayer,
    GamePhase,
    IllegalActionError,
    InvestigatePlayer,
    NominateChancellor,
    PolicyPeekAck,
    PresidentDiscard,
    SpecialElection,
    VetoResponse,
)
from server.auth import generate_player_tokens
from server.game_logger import GameLogger
from server.models import GameResultInfo, PendingActionInfo

# ─── Action factory mapping ─────────────────────────────────────────────────

_ACTION_SPECS: dict[str, tuple[type, tuple[str, ...]]] = {
    "nominate": (NominateChancellor, ("target_id",)),
    "vote": (CastVote, ("vote",)),
    "president_discard": (PresidentDiscard, ("discard_index",)),
    "chancellor_enact": (ChancellorEnact, ("enact_index",)),
    "veto_response": (VetoResponse, ("consent",)),
    "investigate": (InvestigatePlayer, ("target_id",)),
    "peek_ack": (PolicyPeekAck, ()),
    "special_election": (SpecialElection, ("target_id",)),
    "execute": (ExecutePlayer, ("target_id",)),
}


def _build_action(player_id: int, action_type: str, payload: dict) -> Any:
    """Translate an action_type string + payload dict into a frozen dataclass."""
    spec = _ACTION_SPECS.get(action_type)
    if spec is None:
        raise IllegalActionError(f"Unknown action type: {action_type!r}")
    cls, fields = spec
    return cls(player_id=player_id, **{f: payload.get(f) for f in fields})


# ─── Discussion Window ───────────────────────────────────────────────────────


class DiscussionWindow:
    """A bounded discussion window (pre-vote or post-legislative)."""

    def __init__(self, round_number: int, window_type: str) -> None:
        self.round = round_number
        self.window_type = window_type  # "pre_vote" or "post_legislative"
        self.is_open = True
        self.messages: list[dict] = []

    def add_message(self, player_id: int, message: str) -> dict:
        if not self.is_open:
            raise IllegalActionError("Discussion window is closed.")
        entry = {
            "player_id": player_id,
            "message": message,
            "seq": len(self.messages),
        }
        self.messages.append(entry)
        return entry

    def close(self) -> None:
        self.is_open = False

    def to_dict(self) -> dict:
        return {
            "round": self.round,
            "window": self.window_type,
            "is_open": self.is_open,
            "messages": list(self.messages),
        }


# ─── Game Session ────────────────────────────────────────────────────────────


class GameSession:
    """Wraps a GameEngine with discussion state, skin translation, logging, and token auth.

    Lifecycle::

        session = GameSession(num_players=5, skin=some_skin, seed=42)
        session.setup()
        # ... players interact via get_observation / submit_action / speak ...
    """

    def __init__(
        self,
        num_players: int = 7,
        skin: BaseSkin | None = None,
        seed: int | None = None,
        game_id: str | None = None,
        log_base_dir: str = "logs/games",
    ) -> None:
        self.game_id = game_id or uuid.uuid4().hex[:12]
        self._engine = GameEngine(num_players=num_players, seed=seed)
        self._skin = skin
        self._seed = seed
        self._tokens: dict[str, int] = {}
        self._logger = GameLogger(self.game_id, base_dir=log_base_dir)

        # Discussion state
        self._current_discussion: DiscussionWindow | None = None
        self._discussion_history: list[DiscussionWindow] = []

    # ── setup ────────────────────────────────────────────────────────────

    def setup(self) -> dict[str, int]:
        """Initialize the engine, generate tokens, and log metadata.

        Returns the token -> player_id mapping.
        """
        self._engine.setup()
        self._tokens = generate_player_tokens(self._engine.num_players)

        self._logger.log_metadata(
            {
                "game_id": self.game_id,
                "num_players": self._engine.num_players,
                "skin": self._skin.name if self._skin else None,
                "seed": self._seed,
            },
        )

        return dict(self._tokens)

    # ── auth ─────────────────────────────────────────────────────────────

    def get_player_id(self, token: str) -> int:
        """Resolve a token to a player_id. Raises ValueError for invalid tokens."""
        if token not in self._tokens:
            raise ValueError("Invalid token")
        return self._tokens[token]

    # ── observation ──────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Return public game status (no private information)."""
        engine = self._engine
        status: dict[str, Any] = {
            "game_id": self.game_id,
            "phase": engine.phase.name,
            "round": engine._round_number,
            "liberal_policies": engine.liberal_policy_count,
            "fascist_policies": engine.fascist_policy_count,
            "election_tracker": engine.election_tracker,
            "is_game_over": engine.is_game_over,
            "result": None,
            "pending_action": None,
        }
        if engine.result:
            status["result"] = GameResultInfo(
                winner=engine.result.winner,
                condition=engine.result.condition.value,
                final_round=engine.result.final_round,
            ).to_dict()
        if not engine.is_game_over and engine.phase != GamePhase.GAME_SETUP:
            pa = engine.pending_action
            status["pending_action"] = PendingActionInfo(
                phase=pa.phase.name,
                expected_action=pa.expected_action.__name__,
                required_by=pa.required_by,
                legal_targets=pa.legal_targets,
            ).to_dict()
        return status

    def get_observation(self, player_id: int) -> dict:
        """Return raw and skin-translated observations for a player."""
        raw = self._engine.get_observation(player_id)
        skinned = self._skin.translate_observation(raw) if self._skin else raw
        self._logger.log_observation(player_id, raw)
        return {"raw": raw, "skinned": skinned}

    # ── actions ──────────────────────────────────────────────────────────

    def submit_action(self, player_id: int, action_type: str, payload: dict) -> dict:
        """Build an action from the type string + payload, submit it to the engine.

        Automatically manages discussion windows:
        - Opens a "pre_vote" window after nomination (enters ELECTION_VOTE).
        - Opens a "post_legislative" window after policy enactment.
        """
        # Close any open discussion before processing the action
        if self._current_discussion and self._current_discussion.is_open:
            self._current_discussion.close()
            self._discussion_history.append(self._current_discussion)
            self._current_discussion = None

        action = _build_action(player_id, action_type, payload)
        result = self._engine.submit_action(action)

        self._logger.log_action(player_id, action_type, payload, result)

        # Open discussion windows at natural pauses
        phase = self._engine.phase
        if phase == GamePhase.ELECTION_VOTE and action_type == "nominate":
            self._current_discussion = DiscussionWindow(self._engine._round_number, "pre_vote")
        elif result.get("event") == "policy_enacted":
            self._current_discussion = DiscussionWindow(self._engine._round_number, "post_legislative")

        # Log game result if the game just ended
        if self._engine.is_game_over and self._engine.result:
            self._logger.log_game_result(
                {
                    "winner": self._engine.result.winner,
                    "condition": self._engine.result.condition.value,
                    "final_round": self._engine.result.final_round,
                },
            )

        return result

    # ── discussion ───────────────────────────────────────────────────────

    def speak(self, player_id: int, message: str) -> dict:
        """Add a message to the current discussion window."""
        if self._current_discussion is None or not self._current_discussion.is_open:
            raise IllegalActionError("No discussion window is currently open.")
        entry = self._current_discussion.add_message(player_id, message)
        self._logger.log_discussion(player_id, self._current_discussion.window_type, message)
        return entry

    def get_discussion(self) -> dict | None:
        """Return the current discussion window state, or None if no window is active."""
        if self._current_discussion is None:
            return None
        return self._current_discussion.to_dict()

    def close_discussion(self) -> None:
        """Close the current discussion window."""
        if self._current_discussion and self._current_discussion.is_open:
            self._current_discussion.close()
            self._discussion_history.append(self._current_discussion)
            self._current_discussion = None
