"""Shared enums, dataclasses, and action types for the Secret Hitler game engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

# ─── Game Constants ───

LIBERAL_POLICIES_TO_WIN: int = 5
FASCIST_POLICIES_TO_WIN: int = 6
ELECTION_TRACKER_CHAOS: int = 3
VETO_UNLOCK_THRESHOLD: int = 5


# ─── Core Enums ───


class Role(Enum):
    LIBERAL = "liberal"
    FASCIST = "fascist"
    HITLER = "hitler"


class Party(Enum):
    LIBERAL = "liberal"
    FASCIST = "fascist"


class PolicyType(Enum):
    LIBERAL = "liberal"
    FASCIST = "fascist"


class ExecutivePower(Enum):
    NONE = "none"
    INVESTIGATE = "investigate_loyalty"
    PEEK = "policy_peek"
    SPECIAL_ELECTION = "special_election"
    EXECUTION = "execution"


class GamePhase(Enum):
    GAME_SETUP = auto()
    CHANCELLOR_NOMINATION = auto()
    ELECTION_VOTE = auto()
    LEGISLATIVE_PRESIDENT = auto()
    LEGISLATIVE_CHANCELLOR = auto()
    VETO_RESPONSE = auto()
    EXECUTIVE_ACTION_INVESTIGATE = auto()
    EXECUTIVE_ACTION_PEEK = auto()
    EXECUTIVE_ACTION_SPECIAL_ELECTION = auto()
    EXECUTIVE_ACTION_EXECUTION = auto()
    GAME_OVER = auto()


class WinCondition(Enum):
    LIBERAL_POLICY_WIN = "five_liberal_policies"
    LIBERAL_HITLER_EXECUTED = "hitler_executed"
    FASCIST_POLICY_WIN = "six_fascist_policies"
    FASCIST_HITLER_CHANCELLOR = "hitler_elected_chancellor"


# ─── State Dataclasses ───


@dataclass(frozen=True)
class GameResult:
    winner: str  # "liberal" or "fascist"
    condition: WinCondition
    final_round: int


@dataclass
class PlayerState:
    player_id: int
    role: Role
    party: Party
    alive: bool = True
    investigated: bool = False


# ─── Action Dataclasses ───


@dataclass(frozen=True)
class NominateChancellor:
    player_id: int
    target_id: int


@dataclass(frozen=True)
class CastVote:
    player_id: int
    vote: bool  # True = Ja, False = Nein


@dataclass(frozen=True)
class PresidentDiscard:
    player_id: int
    discard_index: int  # 0, 1, or 2 (index into the 3 drawn)


@dataclass(frozen=True)
class ChancellorEnact:
    player_id: int
    enact_index: int | None  # 0 or 1 (index into 2 received), or None = request veto


@dataclass(frozen=True)
class VetoResponse:
    player_id: int
    consent: bool


@dataclass(frozen=True)
class InvestigatePlayer:
    player_id: int
    target_id: int


@dataclass(frozen=True)
class PolicyPeekAck:
    player_id: int


@dataclass(frozen=True)
class SpecialElection:
    player_id: int
    target_id: int


@dataclass(frozen=True)
class ExecutePlayer:
    player_id: int
    target_id: int


Action = (
    NominateChancellor
    | CastVote
    | PresidentDiscard
    | ChancellorEnact
    | VetoResponse
    | InvestigatePlayer
    | PolicyPeekAck
    | SpecialElection
    | ExecutePlayer
)


# ─── Pending Action (what the engine expects next) ───


@dataclass(frozen=True)
class PendingAction:
    """Describes what action(s) the engine is waiting for."""

    phase: GamePhase
    expected_action: type  # the Action subclass expected
    required_by: int | list[int]  # player_id, or list for simultaneous votes
    legal_targets: list[Any] | None = None


# ─── Round Record (audit trail) ───


@dataclass
class RoundRecord:
    """Complete record of one round, built incrementally."""

    round_number: int
    presidential_candidate: int
    chancellor_nominee: int | None = None
    votes: dict[int, bool] | None = None
    elected: bool = False
    # Legislative details (ground truth)
    policies_drawn: list[PolicyType] | None = None
    president_discarded: PolicyType | None = None
    policies_to_chancellor: list[PolicyType] | None = None
    chancellor_discarded: PolicyType | None = None
    policy_enacted: PolicyType | None = None
    veto_attempted: bool = False
    veto_consented: bool | None = None
    # Executive action
    executive_power: ExecutivePower | None = None
    executive_target: int | None = None
    investigation_result: Party | None = None
    peek_result: list[PolicyType] | None = None
    # Hitler check
    hitler_check_passed: bool | None = None
    # Chaos
    chaos_policy: PolicyType | None = None


# ─── Exceptions ───


class IllegalActionError(Exception):
    """Raised when an action is invalid for the current game state."""

    def __init__(self, message: str, legal_actions: list | None = None):
        super().__init__(message)
        self.legal_actions = legal_actions


class GameOverError(Exception):
    """Raised when an action is submitted after the game has ended."""

    pass


# ─── Structured Observation / Event Dataclasses ───


@dataclass(frozen=True)
class PlayerInfo:
    """Public info about a player, as seen in observations."""

    id: int
    alive: bool
    confirmed_not_hitler: bool

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "alive": self.alive, "confirmed_not_hitler": self.confirmed_not_hitler}


@dataclass(frozen=True)
class InvestigationResult:
    """Result of an investigation, stored per-president."""

    round: int
    target: int
    party: str

    def to_dict(self) -> dict[str, Any]:
        return {"round": self.round, "target": self.target, "party": self.party}


@dataclass(frozen=True)
class PeekResult:
    """Result of a policy peek, stored per-president."""

    round: int
    policies: list[str]

    def __hash__(self) -> int:
        return hash((self.round, tuple(self.policies)))

    def to_dict(self) -> dict[str, Any]:
        return {"round": self.round, "policies": list(self.policies)}


@dataclass(frozen=True)
class RoundSummary:
    """Public-view summary of a completed round, used in observation history."""

    round: int
    president: int
    chancellor_nominee: int | None
    votes: dict[int, bool] | None
    elected: bool
    policy_enacted: str | None
    executive_power_used: str | None
    executive_target: int | None
    chaos: bool
    chaos_policy: str | None
    hitler_check_passed: bool | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "round": self.round,
            "president": self.president,
            "chancellor_nominee": self.chancellor_nominee,
            "votes": dict(self.votes) if self.votes else None,
            "elected": self.elected,
            "policy_enacted": self.policy_enacted,
            "executive_power_used": self.executive_power_used,
            "executive_target": self.executive_target,
            "chaos": self.chaos,
            "chaos_policy": self.chaos_policy,
            "hitler_check_passed": self.hitler_check_passed,
        }


@dataclass(frozen=True)
class PrivateEvent:
    """A private event visible only to one player."""

    round: int
    type: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"round": self.round, "type": self.type, "details": dict(self.details)}


@dataclass(frozen=True)
class ActionEvent:
    """Result dict returned by action handlers in the engine."""

    event: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"event": self.event}
        result.update(self.data)
        return result
