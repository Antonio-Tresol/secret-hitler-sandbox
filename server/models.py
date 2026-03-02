"""Pydantic request/response models for the Secret Hitler MCP server."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field


# ─── Structured response helpers ────────────────────────────────────────────


@dataclass(frozen=True)
class PendingActionInfo:
    """Pending action descriptor returned inside game status."""

    phase: str
    expected_action: str
    required_by: int | list[int]
    legal_targets: list[int] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "expected_action": self.expected_action,
            "required_by": self.required_by,
            "legal_targets": self.legal_targets,
        }


@dataclass(frozen=True)
class GameResultInfo:
    """Game result descriptor returned inside game status."""

    winner: str
    condition: str
    final_round: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "winner": self.winner,
            "condition": self.condition,
            "final_round": self.final_round,
        }


@dataclass(frozen=True)
class NoChangeResponse:
    """Returned by MCP diff handlers when nothing has changed."""

    phase: str | None = None
    round: int | None = None
    message_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"no_change": True}
        if self.phase is not None:
            d["phase"] = self.phase
        if self.round is not None:
            d["round"] = self.round
        if self.message_count is not None:
            d["message_count"] = self.message_count
        return d


# ─── Requests ───


class CreateLobbyRequest(BaseModel):
    num_players: int = Field(ge=5, le=10)
    skin: str = "secret_hitler"
    seed: int | None = None


class ActionRequest(BaseModel):
    action_type: str
    payload: dict = Field(default_factory=dict)


class SpeakRequest(BaseModel):
    message: str


# ─── Responses ───


class LobbyResponse(BaseModel):
    game_id: str
    num_players: int
    skin: str
    tokens: dict[str, int]  # {token: player_id}


class GameStatusResponse(BaseModel):
    game_id: str
    phase: str
    round: int
    liberal_policies: int
    fascist_policies: int
    election_tracker: int
    is_game_over: bool
    result: dict | None = None
    pending_action: dict | None = None


class ObservationResponse(BaseModel):
    raw: dict
    skinned: dict


class DiscussionResponse(BaseModel):
    round: int
    window: str  # "pre_vote" or "post_legislative"
    is_open: bool
    messages: list[dict]
