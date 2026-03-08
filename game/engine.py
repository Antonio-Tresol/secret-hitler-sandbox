"""Core game engine: deterministic state machine for Secret Hitler."""

from __future__ import annotations

import random as _random
from typing import Any

from game.policies import PolicyDeck
from game.powers import get_executive_power
from game.roles import assign_roles, get_knowledge
from game.terms import get_ineligible_for_chancellor
from game.types import (
    ELECTION_TRACKER_CHAOS,
    FASCIST_POLICIES_TO_WIN,
    LIBERAL_POLICIES_TO_WIN,
    VETO_UNLOCK_THRESHOLD,
    Action,
    ActionEvent,
    CastVote,
    ChancellorEnact,
    ExecutePlayer,
    ExecutivePower,
    GameOverError,
    GamePhase,
    GameResult,
    IllegalActionError,
    InvestigatePlayer,
    InvestigationResult,
    NominateChancellor,
    Party,
    PeekResult,
    PendingAction,
    PlayerInfo,
    PlayerState,
    PolicyPeekAck,
    PolicyType,
    PresidentDiscard,
    PrivateEvent,
    Role,
    RoundRecord,
    RoundSummary,
    SpecialElection,
    VetoResponse,
    WinCondition,
)


class GameEngine:
    """Deterministic state-machine engine for Secret Hitler.

    All randomness flows through a seeded ``random.Random`` instance so that
    games are fully reproducible given the same seed.  The single entry point
    for player interaction is :meth:`submit_action`.  Between actions the
    ``pending_action`` property describes exactly what the engine expects
    next.
    """

    # ------------------------------------------------------------------ #
    #  Construction & Setup                                                #
    # ------------------------------------------------------------------ #

    def __init__(self, num_players: int = 7, seed: int | None = None) -> None:
        if num_players < 5 or num_players > 10:
            raise ValueError(f"Player count must be 5-10, got {num_players}")

        self._num_players = num_players
        self._rng = _random.Random(seed)

        # Phase & result
        self._phase: GamePhase = GamePhase.GAME_SETUP
        self._result: GameResult | None = None

        # Players
        self._players: list[PlayerState] = []

        # Policy board
        self._liberal_policies = 0
        self._fascist_policies = 0

        # Deck
        self._deck: PolicyDeck | None = None

        # Election tracker
        self._election_tracker = 0

        # Veto power
        self._veto_unlocked = False

        # Presidency rotation
        self._president_idx: int = -1  # index into _players list (seat order)
        self._current_president: int | None = None
        self._chancellor_nominee: int | None = None
        self._special_election_return_idx: int | None = None

        # Term-limit tracking
        self._last_elected_president: int | None = None
        self._last_elected_chancellor: int | None = None

        # Votes collected during ELECTION_VOTE
        self._votes: dict[int, bool] = {}

        # Legislative session working state
        self._drawn_policies: list[PolicyType] = []
        self._chancellor_hand: list[PolicyType] = []
        self._veto_refused_this_session: bool = False

        # Round tracking
        self._round_number: int = 0
        self._current_round: RoundRecord | None = None
        self._round_history: list[RoundRecord] = []

        # Additional tracking
        self._confirmed_not_hitler: set[int] = set()
        self._investigated_players: set[int] = set()  # player_ids already investigated
        self._investigation_results: dict[int, InvestigationResult] = {}  # president_id -> result
        self._peek_results: dict[int, PeekResult] = {}  # president_id -> result
        self._private_events: dict[int, list[PrivateEvent]] = {}  # player_id -> events

    def setup(self) -> None:
        """Assign roles, shuffle deck, and begin the first round."""
        if self._phase != GamePhase.GAME_SETUP:
            raise IllegalActionError("Game has already been set up.")

        # Assign roles
        self._players = assign_roles(self._num_players, self._rng)

        # Initialise per-player private event lists
        for p in self._players:
            self._private_events[p.player_id] = []

        # Create & shuffle deck
        self._deck = PolicyDeck(self._rng)

        # Begin first round
        self._begin_round()

    # ------------------------------------------------------------------ #
    #  Properties                                                          #
    # ------------------------------------------------------------------ #

    @property
    def phase(self) -> GamePhase:
        return self._phase

    @property
    def is_game_over(self) -> bool:
        return self._phase == GamePhase.GAME_OVER

    @property
    def result(self) -> GameResult | None:
        return self._result

    @property
    def pending_action(self) -> PendingAction:
        """Describe what action(s) the engine is waiting for."""
        if self._phase == GamePhase.GAME_SETUP:
            raise IllegalActionError("Call setup() first.")
        if self._phase == GamePhase.GAME_OVER:
            raise GameOverError("The game is over.")

        if self._phase == GamePhase.CHANCELLOR_NOMINATION:
            ineligible = get_ineligible_for_chancellor(
                self._last_elected_president,
                self._last_elected_chancellor,
                len(self.living_players),
                self._current_president,
            )
            eligible = [pid for pid in self.living_players if pid not in ineligible]
            return PendingAction(
                phase=self._phase,
                expected_action=NominateChancellor,
                required_by=self._current_president,
                legal_targets=eligible,
            )

        if self._phase == GamePhase.ELECTION_VOTE:
            still_needed = [pid for pid in self.living_players if pid not in self._votes]
            return PendingAction(
                phase=self._phase,
                expected_action=CastVote,
                required_by=still_needed,
                legal_targets=[True, False],
            )

        if self._phase == GamePhase.LEGISLATIVE_PRESIDENT:
            return PendingAction(
                phase=self._phase,
                expected_action=PresidentDiscard,
                required_by=self._current_president,
                legal_targets=list(range(len(self._drawn_policies))),
            )

        if self._phase == GamePhase.LEGISLATIVE_CHANCELLOR:
            targets: list[Any] = list(range(len(self._chancellor_hand)))
            if self._veto_unlocked and not self._veto_refused_this_session:
                targets.append(None)  # veto option
            return PendingAction(
                phase=self._phase,
                expected_action=ChancellorEnact,
                required_by=self._chancellor_nominee,
                legal_targets=targets,
            )

        if self._phase == GamePhase.VETO_RESPONSE:
            return PendingAction(
                phase=self._phase,
                expected_action=VetoResponse,
                required_by=self._current_president,
                legal_targets=[True, False],
            )

        if self._phase == GamePhase.EXECUTIVE_ACTION_INVESTIGATE:
            valid = [
                pid
                for pid in self.living_players
                if pid != self._current_president and pid not in self._investigated_players
            ]
            return PendingAction(
                phase=self._phase,
                expected_action=InvestigatePlayer,
                required_by=self._current_president,
                legal_targets=valid,
            )

        if self._phase == GamePhase.EXECUTIVE_ACTION_PEEK:
            return PendingAction(
                phase=self._phase,
                expected_action=PolicyPeekAck,
                required_by=self._current_president,
                legal_targets=None,
            )

        if self._phase == GamePhase.EXECUTIVE_ACTION_SPECIAL_ELECTION:
            valid = [pid for pid in self.living_players if pid != self._current_president]
            return PendingAction(
                phase=self._phase,
                expected_action=SpecialElection,
                required_by=self._current_president,
                legal_targets=valid,
            )

        if self._phase == GamePhase.EXECUTIVE_ACTION_EXECUTION:
            valid = [pid for pid in self.living_players if pid != self._current_president]
            return PendingAction(
                phase=self._phase,
                expected_action=ExecutePlayer,
                required_by=self._current_president,
                legal_targets=valid,
            )

        raise RuntimeError(f"Unexpected phase: {self._phase}")  # pragma: no cover

    @property
    def num_players(self) -> int:
        return self._num_players

    @property
    def living_players(self) -> list[int]:
        return [p.player_id for p in self._players if p.alive]

    @property
    def liberal_policy_count(self) -> int:
        return self._liberal_policies

    @property
    def fascist_policy_count(self) -> int:
        return self._fascist_policies

    @property
    def election_tracker(self) -> int:
        return self._election_tracker

    @property
    def veto_unlocked(self) -> bool:
        return self._veto_unlocked

    @property
    def current_president(self) -> int | None:
        return self._current_president

    @property
    def chancellor_nominee(self) -> int | None:
        return self._chancellor_nominee

    @property
    def last_elected_president(self) -> int | None:
        return self._last_elected_president

    @property
    def last_elected_chancellor(self) -> int | None:
        return self._last_elected_chancellor

    @property
    def round_history(self) -> list[RoundRecord]:
        return list(self._round_history)

    # ------------------------------------------------------------------ #
    #  Player Queries                                                      #
    # ------------------------------------------------------------------ #

    def get_player_role(self, player_id: int) -> Role:
        """Return the role for a player (god-mode / testing)."""
        return self._players[player_id].role

    def get_player_party(self, player_id: int) -> Party:
        return self._players[player_id].party

    def is_alive(self, player_id: int) -> bool:
        return self._players[player_id].alive

    # ------------------------------------------------------------------ #
    #  Observation (information hiding)                                    #
    # ------------------------------------------------------------------ #

    def get_observation(self, player_id: int) -> dict:
        """Return the game state visible to *player_id*."""
        obs: dict[str, Any] = {}

        # --- public info ---
        obs["phase"] = self._phase.name
        obs["round"] = self._round_number
        obs["liberal_policies"] = self._liberal_policies
        obs["fascist_policies"] = self._fascist_policies
        obs["election_tracker"] = self._election_tracker
        obs["veto_unlocked"] = self._veto_unlocked
        obs["draw_pile_size"] = self._deck.draw_size if self._deck else 0
        obs["discard_pile_size"] = self._deck.discard_size if self._deck else 0

        obs["players"] = [
            PlayerInfo(
                id=p.player_id,
                alive=p.alive,
                confirmed_not_hitler=p.player_id in self._confirmed_not_hitler,
            ).to_dict()
            for p in self._players
        ]

        obs["current_president"] = self._current_president
        obs["chancellor_nominee"] = self._chancellor_nominee
        obs["last_elected_president"] = self._last_elected_president
        obs["last_elected_chancellor"] = self._last_elected_chancellor

        # --- history (public view of rounds) ---
        history: list[dict] = []
        for r in self._round_history:
            summary = RoundSummary(
                round=r.round_number,
                president=r.presidential_candidate,
                chancellor_nominee=r.chancellor_nominee,
                votes=dict(r.votes) if r.votes else None,
                elected=r.elected,
                policy_enacted=r.policy_enacted.value if r.policy_enacted else None,
                executive_power_used=(
                    r.executive_power.value if r.executive_power and r.executive_power != ExecutivePower.NONE else None
                ),
                executive_target=r.executive_target,
                chaos=r.chaos_policy is not None,
                chaos_policy=(r.chaos_policy.value if r.chaos_policy else None),
                hitler_check_passed=r.hitler_check_passed,
            )
            history.append(summary.to_dict())
        obs["history"] = history

        # --- role-based info ---
        player_state = self._players[player_id]
        obs["your_id"] = player_id
        obs["your_role"] = player_state.role.value
        obs["your_party"] = player_state.party.value

        knowledge = get_knowledge(player_id, self._players, self._num_players)
        obs["known_fascists"] = knowledge["known_fascists"]
        obs["known_hitler"] = knowledge["known_hitler"]

        # --- phase-specific info ---
        if self._phase == GamePhase.CHANCELLOR_NOMINATION and player_id == self._current_president:
            ineligible = get_ineligible_for_chancellor(
                self._last_elected_president,
                self._last_elected_chancellor,
                len(self.living_players),
                self._current_president,
            )
            obs["eligible_chancellors"] = [pid for pid in self.living_players if pid not in ineligible]

        if self._phase == GamePhase.LEGISLATIVE_PRESIDENT and player_id == self._current_president:
            obs["drawn_policies"] = [p.value for p in self._drawn_policies]

        if self._phase == GamePhase.LEGISLATIVE_CHANCELLOR and player_id == self._chancellor_nominee:
            obs["received_policies"] = [p.value for p in self._chancellor_hand]

        if player_id in self._investigation_results:
            obs["investigation_result"] = self._investigation_results[player_id].to_dict()

        if (
            self._phase == GamePhase.EXECUTIVE_ACTION_PEEK
            and player_id == self._current_president
            and player_id in self._peek_results
        ):
            obs["peeked_policies"] = self._peek_results[player_id].policies

        # --- private history ---
        obs["private_history"] = [e.to_dict() for e in self._private_events.get(player_id, [])]

        return obs

    # ------------------------------------------------------------------ #
    #  Action Dispatch                                                     #
    # ------------------------------------------------------------------ #

    def submit_action(self, action: Action) -> dict:
        """Validate *action* for the current state and advance the game.

        Returns a dict summarising what happened (varies by action type).
        """
        if self._phase == GamePhase.GAME_OVER:
            raise GameOverError("The game is over.")
        if self._phase == GamePhase.GAME_SETUP:
            raise IllegalActionError("Call setup() before submitting actions.")

        if isinstance(action, NominateChancellor):
            return self._handle_nomination(action)
        if isinstance(action, CastVote):
            return self._handle_vote(action)
        if isinstance(action, PresidentDiscard):
            return self._handle_president_discard(action)
        if isinstance(action, ChancellorEnact):
            return self._handle_chancellor_enact(action)
        if isinstance(action, VetoResponse):
            return self._handle_veto_response(action)
        if isinstance(action, InvestigatePlayer):
            return self._handle_investigate(action)
        if isinstance(action, PolicyPeekAck):
            return self._handle_peek(action)
        if isinstance(action, SpecialElection):
            return self._handle_special_election(action)
        if isinstance(action, ExecutePlayer):
            return self._handle_execution(action)

        raise IllegalActionError(f"Unknown action type: {type(action).__name__}")

    # ------------------------------------------------------------------ #
    #  Round Management                                                    #
    # ------------------------------------------------------------------ #

    def _begin_round(self) -> None:
        """Start a new round: advance the presidency and set CHANCELLOR_NOMINATION."""
        self._advance_presidency()
        self._round_number += 1
        self._current_round = RoundRecord(
            round_number=self._round_number,
            presidential_candidate=self._current_president,
        )
        self._chancellor_nominee = None
        self._votes = {}
        self._drawn_policies = []
        self._chancellor_hand = []
        self._veto_refused_this_session = False
        self._phase = GamePhase.CHANCELLOR_NOMINATION

    def _advance_presidency(self) -> None:
        """Move the presidency to the next living player in seat order.

        If returning from a special election, restore rotation first.
        """
        if self._special_election_return_idx is not None:
            self._president_idx = self._special_election_return_idx
            self._special_election_return_idx = None

        # Move forward to the next living player
        n = len(self._players)
        idx = self._president_idx
        for _ in range(n):
            idx = (idx + 1) % n
            if self._players[idx].alive:
                self._president_idx = idx
                self._current_president = self._players[idx].player_id
                return

        raise RuntimeError("No living players found.")  # pragma: no cover

    def _finalize_round(self) -> None:
        """Append the current round record to history."""
        if self._current_round is not None:
            self._round_history.append(self._current_round)

    # ------------------------------------------------------------------ #
    #  Nomination                                                          #
    # ------------------------------------------------------------------ #

    def _handle_nomination(self, action: NominateChancellor) -> dict:
        if self._phase != GamePhase.CHANCELLOR_NOMINATION:
            raise IllegalActionError(f"Cannot nominate chancellor during {self._phase.name}.")
        if action.player_id != self._current_president:
            raise IllegalActionError(f"Only the president (player {self._current_president}) can nominate.")

        ineligible = get_ineligible_for_chancellor(
            self._last_elected_president,
            self._last_elected_chancellor,
            len(self.living_players),
            self._current_president,
        )

        if action.target_id in ineligible:
            raise IllegalActionError(
                f"Player {action.target_id} is ineligible for chancellor.",
                legal_actions=[pid for pid in self.living_players if pid not in ineligible],
            )
        if not self.is_alive(action.target_id):
            raise IllegalActionError(f"Player {action.target_id} is dead and cannot be nominated.")

        self._chancellor_nominee = action.target_id
        self._current_round.chancellor_nominee = action.target_id
        self._phase = GamePhase.ELECTION_VOTE
        self._votes = {}

        return ActionEvent(event="chancellor_nominated", data={"nominee": action.target_id}).to_dict()

    # ------------------------------------------------------------------ #
    #  Voting                                                              #
    # ------------------------------------------------------------------ #

    def _handle_vote(self, action: CastVote) -> dict:
        if self._phase != GamePhase.ELECTION_VOTE:
            raise IllegalActionError(f"Cannot vote during {self._phase.name}.")
        if action.player_id not in self.living_players:
            raise IllegalActionError(f"Player {action.player_id} is not alive.")
        if action.player_id in self._votes:
            raise IllegalActionError(f"Player {action.player_id} has already voted.")

        self._votes[action.player_id] = action.vote

        # Check if all living players have voted
        if len(self._votes) < len(self.living_players):
            return ActionEvent(event="vote_cast", data={"player": action.player_id, "all_voted": False}).to_dict()

        # All votes in -- resolve election
        return self._resolve_election()

    def _resolve_election(self) -> dict:
        """Resolve the election once all votes are in."""
        self._current_round.votes = dict(self._votes)

        ja_count = sum(1 for v in self._votes.values() if v)
        nein_count = sum(1 for v in self._votes.values() if not v)
        elected = ja_count > nein_count  # strict majority

        result: dict[str, Any] = ActionEvent(
            event="election_result",
            data={"ja": ja_count, "nein": nein_count, "elected": elected},
        ).to_dict()

        if elected:
            self._current_round.elected = True
            self._last_elected_president = self._current_president
            self._last_elected_chancellor = self._chancellor_nominee
            self._election_tracker = 0

            # Hitler check when 3+ fascist policies
            if self._fascist_policies >= 3:
                chancellor_state = self._players[self._chancellor_nominee]
                if chancellor_state.role == Role.HITLER:
                    # Fascist victory
                    self._current_round.hitler_check_passed = False
                    self._finalize_round()
                    self._end_game("fascist", WinCondition.FASCIST_HITLER_CHANCELLOR)
                    result["hitler_elected"] = True
                    return result
                else:
                    self._current_round.hitler_check_passed = True
                    self._confirmed_not_hitler.add(self._chancellor_nominee)

            # Move to legislative session
            self._drawn_policies = self._deck.draw(3)
            self._current_round.policies_drawn = list(self._drawn_policies)
            self._veto_refused_this_session = False
            self._phase = GamePhase.LEGISLATIVE_PRESIDENT
            return result
        else:
            # Election failed
            self._current_round.elected = False
            self._election_tracker += 1
            result["election_tracker"] = self._election_tracker

            if self._election_tracker >= ELECTION_TRACKER_CHAOS:
                self._finalize_round()
                chaos_result = self._handle_chaos()
                result["chaos"] = chaos_result
                return result
            else:
                self._finalize_round()
                if not self.is_game_over:
                    self._begin_round()
                return result

    # ------------------------------------------------------------------ #
    #  Chaos                                                               #
    # ------------------------------------------------------------------ #

    def _handle_chaos(self) -> dict:
        """Top-deck a policy, reset tracker and term limits."""
        self._election_tracker = 0

        # Reset term limits
        self._last_elected_president = None
        self._last_elected_chancellor = None

        # Top-deck
        self._deck.reshuffle_if_needed()
        top_policy = self._deck.draw(1)[0]

        # Record chaos in the LAST finalized round
        self._round_history[-1].chaos_policy = top_policy

        chaos_result: dict[str, Any] = ActionEvent(event="chaos", data={"policy": top_policy.value}).to_dict()

        # Enact the policy (from_chaos=True: no executive power)
        self._enact_policy(top_policy, from_chaos=True)

        if self.is_game_over:
            chaos_result["game_over"] = True
        return chaos_result

    # ------------------------------------------------------------------ #
    #  Legislative Session                                                 #
    # ------------------------------------------------------------------ #

    def _handle_president_discard(self, action: PresidentDiscard) -> dict:
        if self._phase != GamePhase.LEGISLATIVE_PRESIDENT:
            raise IllegalActionError(f"Cannot discard during {self._phase.name}.")
        if action.player_id != self._current_president:
            raise IllegalActionError(f"Only the president (player {self._current_president}) can discard.")
        if action.discard_index not in (0, 1, 2):
            raise IllegalActionError(f"discard_index must be 0, 1, or 2, got {action.discard_index}.")
        if action.discard_index >= len(self._drawn_policies):
            raise IllegalActionError(f"discard_index {action.discard_index} out of range.")

        discarded = self._drawn_policies.pop(action.discard_index)
        self._deck.discard(discarded)
        self._chancellor_hand = list(self._drawn_policies)

        # Record ground truth
        self._current_round.president_discarded = discarded
        self._current_round.policies_to_chancellor = list(self._chancellor_hand)

        # Record private event for president
        self._private_events[self._current_president].append(
            PrivateEvent(
                round=self._round_number,
                type="legislative_president",
                details={
                    "drawn": [p.value for p in self._current_round.policies_drawn],
                    "discarded": discarded.value,
                    "passed_to_chancellor": [p.value for p in self._chancellor_hand],
                },
            ),
        )

        self._phase = GamePhase.LEGISLATIVE_CHANCELLOR
        return ActionEvent(event="president_discarded", data={"discard_index": action.discard_index}).to_dict()

    def _handle_chancellor_enact(self, action: ChancellorEnact) -> dict:
        if self._phase != GamePhase.LEGISLATIVE_CHANCELLOR:
            raise IllegalActionError(f"Cannot enact during {self._phase.name}.")
        if action.player_id != self._chancellor_nominee:
            raise IllegalActionError(f"Only the chancellor (player {self._chancellor_nominee}) can enact.")

        # Veto request
        if action.enact_index is None:
            if not self._veto_unlocked:
                raise IllegalActionError("Veto power has not been unlocked.")
            if self._veto_refused_this_session:
                raise IllegalActionError("The president already refused a veto this session.")
            self._current_round.veto_attempted = True
            self._phase = GamePhase.VETO_RESPONSE
            return ActionEvent(event="veto_requested").to_dict()

        if action.enact_index not in (0, 1):
            raise IllegalActionError(f"enact_index must be 0 or 1, got {action.enact_index}.")
        if action.enact_index >= len(self._chancellor_hand):
            raise IllegalActionError(f"enact_index {action.enact_index} out of range.")

        enacted = self._chancellor_hand[action.enact_index]
        discarded_idx = 1 - action.enact_index
        discarded = self._chancellor_hand[discarded_idx]
        self._deck.discard(discarded)

        # Record ground truth
        self._current_round.chancellor_discarded = discarded
        self._current_round.policy_enacted = enacted

        # Record private event for chancellor
        self._private_events[self._chancellor_nominee].append(
            PrivateEvent(
                round=self._round_number,
                type="legislative_chancellor",
                details={
                    "received": [p.value for p in self._chancellor_hand],
                    "enacted": enacted.value,
                    "discarded": discarded.value,
                },
            ),
        )

        self._finalize_round()
        self._enact_policy(enacted, from_chaos=False)

        return ActionEvent(event="policy_enacted", data={"policy": enacted.value}).to_dict()

    # ------------------------------------------------------------------ #
    #  Veto                                                                #
    # ------------------------------------------------------------------ #

    def _handle_veto_response(self, action: VetoResponse) -> dict:
        if self._phase != GamePhase.VETO_RESPONSE:
            raise IllegalActionError(f"Cannot respond to veto during {self._phase.name}.")
        if action.player_id != self._current_president:
            raise IllegalActionError(f"Only the president (player {self._current_president}) can respond to veto.")

        if action.consent:
            # Veto succeeds: discard both remaining policies
            self._current_round.veto_consented = True
            for p in self._chancellor_hand:
                self._deck.discard(p)

            self._current_round.policy_enacted = None
            self._finalize_round()

            self._election_tracker += 1

            if self._election_tracker >= ELECTION_TRACKER_CHAOS:
                chaos_result = self._handle_chaos()
                return ActionEvent(event="veto_accepted", data={"chaos": chaos_result}).to_dict()
            else:
                self._deck.reshuffle_if_needed()
                if not self.is_game_over:
                    self._begin_round()
                return ActionEvent(event="veto_accepted").to_dict()
        else:
            # Veto refused: chancellor must choose again (no veto option)
            self._current_round.veto_consented = False
            self._veto_refused_this_session = True
            self._phase = GamePhase.LEGISLATIVE_CHANCELLOR
            return ActionEvent(event="veto_refused").to_dict()

    # ------------------------------------------------------------------ #
    #  Policy Enactment                                                    #
    # ------------------------------------------------------------------ #

    def _enact_policy(self, policy: PolicyType, *, from_chaos: bool = False) -> None:
        """Enact a policy: update board, check win, check executive power."""
        if policy == PolicyType.LIBERAL:
            self._liberal_policies += 1
        else:
            self._fascist_policies += 1

        # Win conditions
        if self._liberal_policies >= LIBERAL_POLICIES_TO_WIN:
            self._end_game("liberal", WinCondition.LIBERAL_POLICY_WIN)
            return
        if self._fascist_policies >= FASCIST_POLICIES_TO_WIN:
            self._end_game("fascist", WinCondition.FASCIST_POLICY_WIN)
            return

        # Veto unlock at 5 fascist policies
        if self._fascist_policies == VETO_UNLOCK_THRESHOLD:
            self._veto_unlocked = True

        # Executive power (only for fascist, non-chaos)
        if not from_chaos and policy == PolicyType.FASCIST:
            power = get_executive_power(self._num_players, self._fascist_policies)
            if power != ExecutivePower.NONE:
                self._round_history[-1].executive_power = power
                self._phase = self._power_to_phase(power)

                # For PEEK, eagerly read the top 3 cards so they are
                # visible via get_observation before the ack is submitted.
                if power == ExecutivePower.PEEK:
                    self._prepare_peek()
                return

        # No executive power or chaos/liberal: reshuffle and next round
        self._deck.reshuffle_if_needed()
        if not self.is_game_over:
            self._begin_round()

    @staticmethod
    def _power_to_phase(power: ExecutivePower) -> GamePhase:
        """Map an executive power to the corresponding game phase."""
        mapping = {
            ExecutivePower.INVESTIGATE: GamePhase.EXECUTIVE_ACTION_INVESTIGATE,
            ExecutivePower.PEEK: GamePhase.EXECUTIVE_ACTION_PEEK,
            ExecutivePower.SPECIAL_ELECTION: GamePhase.EXECUTIVE_ACTION_SPECIAL_ELECTION,
            ExecutivePower.EXECUTION: GamePhase.EXECUTIVE_ACTION_EXECUTION,
        }
        return mapping[power]

    # ------------------------------------------------------------------ #
    #  Executive Actions                                                   #
    # ------------------------------------------------------------------ #

    def _handle_investigate(self, action: InvestigatePlayer) -> dict:
        if self._phase != GamePhase.EXECUTIVE_ACTION_INVESTIGATE:
            raise IllegalActionError(f"Cannot investigate during {self._phase.name}.")
        if action.player_id != self._current_president:
            raise IllegalActionError(f"Only the president (player {self._current_president}) can investigate.")
        if action.target_id == self._current_president:
            raise IllegalActionError("The president cannot investigate themselves.")
        if not self.is_alive(action.target_id):
            raise IllegalActionError(f"Player {action.target_id} is dead.")
        if action.target_id in self._investigated_players:
            raise IllegalActionError(f"Player {action.target_id} has already been investigated.")

        target_party = self._players[action.target_id].party
        self._investigated_players.add(action.target_id)

        # Record in round
        self._round_history[-1].executive_target = action.target_id
        self._round_history[-1].investigation_result = target_party

        # Store investigation result for observation
        inv_result = InvestigationResult(
            round=self._round_number,
            target=action.target_id,
            party=target_party.value,
        )
        self._investigation_results[self._current_president] = inv_result

        # Private event
        self._private_events[self._current_president].append(
            PrivateEvent(
                round=self._round_number,
                type="investigation",
                details={
                    "target": action.target_id,
                    "party": target_party.value,
                },
            ),
        )

        self._deck.reshuffle_if_needed()
        self._begin_round()

        return ActionEvent(
            event="investigation",
            data={"target": action.target_id, "party": target_party.value},
        ).to_dict()

    def _prepare_peek(self) -> None:
        """Eagerly peek at the top 3 cards when entering the PEEK phase.

        This makes the peeked policies available via ``get_observation``
        before the president submits their acknowledgement.
        """
        self._deck.reshuffle_if_needed()
        top_3 = self._deck.peek(3)

        # Record in round
        self._round_history[-1].executive_target = None
        self._round_history[-1].peek_result = list(top_3)

        # Store peek result for observation
        self._peek_results[self._current_president] = PeekResult(
            round=self._round_number,
            policies=[p.value for p in top_3],
        )

        # Private event
        self._private_events[self._current_president].append(
            PrivateEvent(
                round=self._round_number,
                type="policy_peek",
                details={
                    "policies": [p.value for p in top_3],
                },
            ),
        )

    def _handle_peek(self, action: PolicyPeekAck) -> dict:
        if self._phase != GamePhase.EXECUTIVE_ACTION_PEEK:
            raise IllegalActionError(f"Cannot peek during {self._phase.name}.")
        if action.player_id != self._current_president:
            raise IllegalActionError(f"Only the president (player {self._current_president}) can acknowledge peek.")

        # The actual peek was already performed in _prepare_peek when the
        # phase was entered.  Retrieve the stored result for the return value.
        policies = self._peek_results[self._current_president].policies

        self._deck.reshuffle_if_needed()
        self._begin_round()

        return ActionEvent(event="policy_peek", data={"policies": policies}).to_dict()

    def _handle_special_election(self, action: SpecialElection) -> dict:
        if self._phase != GamePhase.EXECUTIVE_ACTION_SPECIAL_ELECTION:
            raise IllegalActionError(f"Cannot call special election during {self._phase.name}.")
        if action.player_id != self._current_president:
            raise IllegalActionError(
                f"Only the president (player {self._current_president}) can call a special election.",
            )
        if action.target_id == self._current_president:
            raise IllegalActionError("The president cannot designate themselves for special election.")
        if not self.is_alive(action.target_id):
            raise IllegalActionError(f"Player {action.target_id} is dead.")

        # Record in round
        self._round_history[-1].executive_target = action.target_id

        # Save current rotation position so that AFTER the special election
        # round completes, _advance_presidency restores the normal rotation.
        saved_return_idx = self._president_idx

        # Set _president_idx so that _advance_presidency() (called inside
        # _begin_round) lands on the target.  _advance_presidency walks
        # forward from _president_idx to the next living player, so we
        # position one step before the target's seat.
        target_seat = action.target_id  # player_id == seat index
        self._president_idx = (target_seat - 1) % len(self._players)

        self._deck.reshuffle_if_needed()

        # _begin_round -> _advance_presidency will NOT see
        # _special_election_return_idx yet (it is still None), so it
        # simply advances from the position we just set and lands on
        # the target.
        self._begin_round()

        # NOW store the return index so the NEXT call to
        # _advance_presidency (after the special-election round
        # resolves) restores the normal rotation.
        self._special_election_return_idx = saved_return_idx

        return ActionEvent(event="special_election", data={"target": action.target_id}).to_dict()

    def _handle_execution(self, action: ExecutePlayer) -> dict:
        if self._phase != GamePhase.EXECUTIVE_ACTION_EXECUTION:
            raise IllegalActionError(f"Cannot execute during {self._phase.name}.")
        if action.player_id != self._current_president:
            raise IllegalActionError(f"Only the president (player {self._current_president}) can execute.")
        if action.target_id == self._current_president:
            raise IllegalActionError("The president cannot execute themselves.")
        if not self.is_alive(action.target_id):
            raise IllegalActionError(f"Player {action.target_id} is already dead.")

        # Kill the target
        self._players[action.target_id].alive = False

        # Record in round
        self._round_history[-1].executive_target = action.target_id

        # Check if target is Hitler
        if self._players[action.target_id].role == Role.HITLER:
            self._end_game("liberal", WinCondition.LIBERAL_HITLER_EXECUTED)
            return ActionEvent(event="execution", data={"target": action.target_id, "hitler": True}).to_dict()

        self._deck.reshuffle_if_needed()
        self._begin_round()

        return ActionEvent(event="execution", data={"target": action.target_id, "hitler": False}).to_dict()

    # ------------------------------------------------------------------ #
    #  Game End                                                            #
    # ------------------------------------------------------------------ #

    def _end_game(self, winner: str, condition: WinCondition) -> None:
        """Transition to GAME_OVER."""
        self._phase = GamePhase.GAME_OVER
        self._result = GameResult(
            winner=winner,
            condition=condition,
            final_round=self._round_number,
        )
