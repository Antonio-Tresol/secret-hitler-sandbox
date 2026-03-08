"""Comprehensive tests for veto power mechanics in Secret Hitler."""

from __future__ import annotations

import pytest

from game.engine import GameEngine
from game.types import (
    CastVote,
    ChancellorEnact,
    ExecutePlayer,
    GamePhase,
    IllegalActionError,
    InvestigatePlayer,
    NominateChancellor,
    PolicyPeekAck,
    PolicyType,
    PresidentDiscard,
    SpecialElection,
    VetoResponse,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _handle_executive_action(engine: GameEngine, president: int) -> None:
    """Resolve whatever executive action phase the engine is in, if any.

    Picks the first valid target for actions that require one, or simply
    acknowledges for peek.  Does nothing if the engine is not in an
    executive-action phase.
    """
    executive_phases = {
        GamePhase.EXECUTIVE_ACTION_INVESTIGATE,
        GamePhase.EXECUTIVE_ACTION_PEEK,
        GamePhase.EXECUTIVE_ACTION_SPECIAL_ELECTION,
        GamePhase.EXECUTIVE_ACTION_EXECUTION,
    }

    while engine.phase in executive_phases:
        pending = engine.pending_action
        phase = engine.phase

        if phase == GamePhase.EXECUTIVE_ACTION_INVESTIGATE:
            target = pending.legal_targets[0]
            engine.submit_action(InvestigatePlayer(player_id=president, target_id=target))
        elif phase == GamePhase.EXECUTIVE_ACTION_PEEK:
            engine.submit_action(PolicyPeekAck(player_id=president))
        elif phase == GamePhase.EXECUTIVE_ACTION_SPECIAL_ELECTION:
            target = pending.legal_targets[0]
            engine.submit_action(SpecialElection(player_id=president, target_id=target))
        elif phase == GamePhase.EXECUTIVE_ACTION_EXECUTION:
            # Pick a non-Hitler target to avoid ending the game.
            # Try each legal target; pick one whose role is NOT hitler.
            target = None
            for t in pending.legal_targets:
                if engine.get_player_role(t).value != "hitler":
                    target = t
                    break
            if target is None:
                # All targets are Hitler (impossible in practice), just pick first.
                target = pending.legal_targets[0]
            engine.submit_action(ExecutePlayer(player_id=president, target_id=target))


def advance_round(
    engine: GameEngine,
    chancellor_target: int | None = None,
    *,
    all_vote_ja: bool = True,
    president_discard_index: int = 0,
    chancellor_enact_index: int = 0,
) -> dict | None:
    """Play through one complete round.

    Returns the result dict from the final action of the round, or None
    if the game ends mid-round.
    """
    if engine.is_game_over:
        return None

    # --- Nomination ---
    pending = engine.pending_action
    assert pending.phase == GamePhase.CHANCELLOR_NOMINATION
    president = pending.required_by

    if chancellor_target is None:
        chancellor_target = pending.legal_targets[0]
    engine.submit_action(NominateChancellor(player_id=president, target_id=chancellor_target))

    # --- Voting ---
    for pid in engine.living_players:
        engine.submit_action(CastVote(player_id=pid, vote=all_vote_ja))

    if engine.is_game_over:
        return None

    if not all_vote_ja:
        # Election failed; engine has already moved to next round or chaos.
        return None

    # --- Legislative session ---
    if engine.phase == GamePhase.LEGISLATIVE_PRESIDENT:
        engine.submit_action(PresidentDiscard(player_id=president, discard_index=president_discard_index))

        if engine.is_game_over:
            return None

        result = engine.submit_action(ChancellorEnact(player_id=chancellor_target, enact_index=chancellor_enact_index))

        if engine.is_game_over:
            return result

        # --- Executive action ---
        _handle_executive_action(engine, president)

        return result

    return None


def _setup_engine_with_veto_unlocked(num_players: int = 7, seed: int = 42) -> GameEngine:
    """Create and set up an engine, then directly set the state so that
    5 fascist policies are enacted and veto is unlocked.

    This avoids having to drive through many rounds just to reach the
    veto-eligible state, making tests focused on veto mechanics robust
    and independent of deck ordering.
    """
    engine = GameEngine(num_players=num_players, seed=seed)
    engine.setup()

    # Directly set internal state to simulate 5 fascist policies enacted.
    engine._fascist_policies = 5
    engine._veto_unlocked = True

    return engine


def _drive_to_chancellor_phase(engine: GameEngine) -> tuple[int, int]:
    """Drive the engine from CHANCELLOR_NOMINATION through a successful
    election into the LEGISLATIVE_CHANCELLOR phase.

    Returns (president_id, chancellor_id).
    """
    pending = engine.pending_action
    assert pending.phase == GamePhase.CHANCELLOR_NOMINATION
    president = pending.required_by
    chancellor = pending.legal_targets[0]

    engine.submit_action(NominateChancellor(player_id=president, target_id=chancellor))

    for pid in engine.living_players:
        engine.submit_action(CastVote(player_id=pid, vote=True))

    assert engine.phase == GamePhase.LEGISLATIVE_PRESIDENT

    engine.submit_action(PresidentDiscard(player_id=president, discard_index=0))

    assert engine.phase == GamePhase.LEGISLATIVE_CHANCELLOR
    return president, chancellor


def _find_seed_for_fascist_heavy_deck(
    num_players: int = 7,
    rounds_needed: int = 5,
    max_seeds: int = 500,
) -> int:
    """Find a seed where the first several draws are all-fascist or
    mostly-fascist, allowing us to reach 5 fascist policies purely
    through gameplay without hitting a game-ending condition early.

    This is used by tests that verify veto through organic gameplay.
    """
    for seed in range(max_seeds):
        try:
            engine = GameEngine(num_players=num_players, seed=seed)
            engine.setup()

            fascist_enacted = 0
            for _ in range(rounds_needed + 5):  # extra rounds for safety
                if engine.is_game_over:
                    break
                if engine.phase != GamePhase.CHANCELLOR_NOMINATION:
                    break
                advance_round(engine)
                fascist_enacted = engine.fascist_policy_count
                if fascist_enacted >= 5:
                    break
            if fascist_enacted >= 5 and engine.veto_unlocked and not engine.is_game_over:
                return seed
        except Exception:
            continue
    raise RuntimeError(f"Could not find a seed with {rounds_needed}+ fascist policies among first {max_seeds} seeds.")


# ---------------------------------------------------------------------------
# 1. test_veto_not_available_before_5_fascist
# ---------------------------------------------------------------------------


class TestVetoNotAvailableBefore5Fascist:
    """With fewer than 5 fascist policies enacted, veto must not be allowed."""

    def test_veto_raises_illegal_action(self):
        """ChancellorEnact with enact_index=None raises IllegalActionError
        when veto has not been unlocked (< 5 fascist policies)."""
        engine = GameEngine(num_players=7, seed=42)
        engine.setup()

        # Confirm veto is NOT unlocked.
        assert engine.fascist_policy_count < 5
        assert engine.veto_unlocked is False

        president, chancellor = _drive_to_chancellor_phase(engine)

        with pytest.raises(IllegalActionError, match="Veto power has not been unlocked"):
            engine.submit_action(ChancellorEnact(player_id=chancellor, enact_index=None))

    def test_pending_action_does_not_include_none_before_veto(self):
        """The legal_targets for LEGISLATIVE_CHANCELLOR should not include
        None when veto is locked."""
        engine = GameEngine(num_players=7, seed=42)
        engine.setup()

        _drive_to_chancellor_phase(engine)

        pending = engine.pending_action
        assert pending.phase == GamePhase.LEGISLATIVE_CHANCELLOR
        assert None not in pending.legal_targets


# ---------------------------------------------------------------------------
# 2. test_chancellor_can_request_veto
# ---------------------------------------------------------------------------


class TestChancellorCanRequestVeto:
    """With 5 fascist policies and veto unlocked, the chancellor can
    submit enact_index=None and the phase moves to VETO_RESPONSE."""

    def test_veto_request_moves_to_veto_response(self):
        engine = _setup_engine_with_veto_unlocked()
        president, chancellor = _drive_to_chancellor_phase(engine)

        result = engine.submit_action(ChancellorEnact(player_id=chancellor, enact_index=None))

        assert result["event"] == "veto_requested"
        assert engine.phase == GamePhase.VETO_RESPONSE

    def test_pending_action_includes_none_when_veto_unlocked(self):
        """legal_targets for LEGISLATIVE_CHANCELLOR should include None
        when veto is unlocked."""
        engine = _setup_engine_with_veto_unlocked()
        _drive_to_chancellor_phase(engine)

        pending = engine.pending_action
        assert pending.phase == GamePhase.LEGISLATIVE_CHANCELLOR
        assert None in pending.legal_targets

    def test_veto_response_pending_action_expects_president(self):
        """After veto request, pending_action should expect a VetoResponse
        from the president."""
        engine = _setup_engine_with_veto_unlocked()
        president, chancellor = _drive_to_chancellor_phase(engine)

        engine.submit_action(ChancellorEnact(player_id=chancellor, enact_index=None))

        pending = engine.pending_action
        assert pending.phase == GamePhase.VETO_RESPONSE
        assert pending.expected_action is VetoResponse
        assert pending.required_by == president
        assert pending.legal_targets == [True, False]


# ---------------------------------------------------------------------------
# 3. test_president_consents_veto
# ---------------------------------------------------------------------------


class TestPresidentConsentsVeto:
    """When the president consents to veto, both policies are discarded,
    the election tracker increments, and the game moves to the next round."""

    def test_veto_accepted_event(self):
        engine = _setup_engine_with_veto_unlocked()
        president, chancellor = _drive_to_chancellor_phase(engine)

        engine.submit_action(ChancellorEnact(player_id=chancellor, enact_index=None))

        result = engine.submit_action(VetoResponse(player_id=president, consent=True))

        assert result["event"] == "veto_accepted"

    def test_no_policy_enacted(self):
        """No policy should be enacted when veto is accepted."""
        engine = _setup_engine_with_veto_unlocked()
        president, chancellor = _drive_to_chancellor_phase(engine)

        # Remember policy counts before veto.
        lib_before = engine.liberal_policy_count
        fas_before = engine.fascist_policy_count

        engine.submit_action(ChancellorEnact(player_id=chancellor, enact_index=None))
        engine.submit_action(VetoResponse(player_id=president, consent=True))

        assert engine.liberal_policy_count == lib_before
        assert engine.fascist_policy_count == fas_before

    def test_election_tracker_increments(self):
        engine = _setup_engine_with_veto_unlocked()
        tracker_before = engine.election_tracker

        president, chancellor = _drive_to_chancellor_phase(engine)

        engine.submit_action(ChancellorEnact(player_id=chancellor, enact_index=None))
        engine.submit_action(VetoResponse(player_id=president, consent=True))

        assert engine.election_tracker == tracker_before + 1

    def test_moves_to_next_round(self):
        engine = _setup_engine_with_veto_unlocked()

        president, chancellor = _drive_to_chancellor_phase(engine)
        round_during = engine._round_number

        engine.submit_action(ChancellorEnact(player_id=chancellor, enact_index=None))
        engine.submit_action(VetoResponse(player_id=president, consent=True))

        # Should now be in CHANCELLOR_NOMINATION for the next round.
        assert engine.phase == GamePhase.CHANCELLOR_NOMINATION
        # The veto round was finalized and a new round has begun.
        assert engine._round_number == round_during + 1

    def test_round_record_reflects_veto(self):
        """The round record should show veto_attempted=True and
        veto_consented=True with no enacted policy."""
        engine = _setup_engine_with_veto_unlocked()
        president, chancellor = _drive_to_chancellor_phase(engine)

        engine.submit_action(ChancellorEnact(player_id=chancellor, enact_index=None))
        engine.submit_action(VetoResponse(player_id=president, consent=True))

        # The vetoed round should be the last one in history.
        last_round = engine.round_history[-1]
        assert last_round.veto_attempted is True
        assert last_round.veto_consented is True
        assert last_round.policy_enacted is None


# ---------------------------------------------------------------------------
# 4. test_president_refuses_veto
# ---------------------------------------------------------------------------


class TestPresidentRefusesVeto:
    """When the president refuses the veto, the chancellor must enact one
    of the two policies and cannot veto again this session."""

    def test_veto_refused_event(self):
        engine = _setup_engine_with_veto_unlocked()
        president, chancellor = _drive_to_chancellor_phase(engine)

        engine.submit_action(ChancellorEnact(player_id=chancellor, enact_index=None))

        result = engine.submit_action(VetoResponse(player_id=president, consent=False))

        assert result["event"] == "veto_refused"

    def test_returns_to_legislative_chancellor(self):
        engine = _setup_engine_with_veto_unlocked()
        president, chancellor = _drive_to_chancellor_phase(engine)

        engine.submit_action(ChancellorEnact(player_id=chancellor, enact_index=None))
        engine.submit_action(VetoResponse(player_id=president, consent=False))

        assert engine.phase == GamePhase.LEGISLATIVE_CHANCELLOR

    def test_cannot_veto_again_after_refusal(self):
        """After the president refuses veto, a second veto attempt by the
        chancellor must raise IllegalActionError."""
        engine = _setup_engine_with_veto_unlocked()
        president, chancellor = _drive_to_chancellor_phase(engine)

        engine.submit_action(ChancellorEnact(player_id=chancellor, enact_index=None))
        engine.submit_action(VetoResponse(player_id=president, consent=False))

        with pytest.raises(IllegalActionError, match="already refused"):
            engine.submit_action(ChancellorEnact(player_id=chancellor, enact_index=None))

    def test_pending_action_excludes_none_after_refusal(self):
        """After veto refusal, the legal_targets should not include None."""
        engine = _setup_engine_with_veto_unlocked()
        president, chancellor = _drive_to_chancellor_phase(engine)

        engine.submit_action(ChancellorEnact(player_id=chancellor, enact_index=None))
        engine.submit_action(VetoResponse(player_id=president, consent=False))

        pending = engine.pending_action
        assert pending.phase == GamePhase.LEGISLATIVE_CHANCELLOR
        assert None not in pending.legal_targets

    def test_chancellor_can_enact_after_refusal(self):
        """After refusal, the chancellor must be able to enact normally."""
        engine = _setup_engine_with_veto_unlocked()
        president, chancellor = _drive_to_chancellor_phase(engine)

        engine.submit_action(ChancellorEnact(player_id=chancellor, enact_index=None))
        engine.submit_action(VetoResponse(player_id=president, consent=False))

        # Chancellor should be able to enact index 0 or 1.
        result = engine.submit_action(ChancellorEnact(player_id=chancellor, enact_index=0))
        assert result["event"] == "policy_enacted"

    def test_round_record_reflects_refused_veto(self):
        """The round record should show veto_attempted=True,
        veto_consented=False, and a policy was enacted."""
        engine = _setup_engine_with_veto_unlocked()
        president, chancellor = _drive_to_chancellor_phase(engine)

        engine.submit_action(ChancellorEnact(player_id=chancellor, enact_index=None))
        engine.submit_action(VetoResponse(player_id=president, consent=False))

        # Enact after refusal.
        engine.submit_action(ChancellorEnact(player_id=chancellor, enact_index=0))

        last_round = engine.round_history[-1]
        assert last_round.veto_attempted is True
        assert last_round.veto_consented is False
        assert last_round.policy_enacted is not None


# ---------------------------------------------------------------------------
# 5. test_veto_advances_election_tracker
# ---------------------------------------------------------------------------


class TestVetoAdvancesElectionTracker:
    """Verify that a successful veto increments the election tracker."""

    def test_tracker_starts_at_zero_and_increments(self):
        engine = _setup_engine_with_veto_unlocked()

        assert engine.election_tracker == 0

        president, chancellor = _drive_to_chancellor_phase(engine)
        engine.submit_action(ChancellorEnact(player_id=chancellor, enact_index=None))
        engine.submit_action(VetoResponse(player_id=president, consent=True))

        assert engine.election_tracker == 1

    def test_tracker_increments_from_nonzero(self):
        """If the tracker is already at 1 (e.g., from a failed election),
        a veto should bring it to 2."""
        engine = _setup_engine_with_veto_unlocked()

        # Fail one election to bring tracker to 1.
        pending = engine.pending_action
        president = pending.required_by
        chancellor = pending.legal_targets[0]
        engine.submit_action(NominateChancellor(player_id=president, target_id=chancellor))
        for pid in engine.living_players:
            engine.submit_action(CastVote(player_id=pid, vote=False))

        assert engine.election_tracker == 1

        # Now do a successful election followed by a veto.
        president2, chancellor2 = _drive_to_chancellor_phase(engine)
        engine.submit_action(ChancellorEnact(player_id=chancellor2, enact_index=None))
        engine.submit_action(VetoResponse(player_id=president2, consent=True))

        # Successful election resets tracker to 0, then veto adds 1.
        assert engine.election_tracker == 1

    def test_refused_veto_does_not_increment_tracker(self):
        """A refused veto should NOT increment the election tracker."""
        engine = _setup_engine_with_veto_unlocked()
        tracker_before = engine.election_tracker

        president, chancellor = _drive_to_chancellor_phase(engine)
        engine.submit_action(ChancellorEnact(player_id=chancellor, enact_index=None))
        engine.submit_action(VetoResponse(player_id=president, consent=False))

        # Tracker unchanged since veto was refused.
        assert engine.election_tracker == tracker_before


# ---------------------------------------------------------------------------
# 6. test_veto_can_trigger_chaos
# ---------------------------------------------------------------------------


class TestVetoCanTriggerChaos:
    """If a veto brings the election tracker to 3, chaos fires
    (top-deck a policy).

    Note on game mechanics: a successful election resets the tracker to 0,
    and veto adds 1 after that. So consecutive veto rounds from successful
    elections always leave the tracker at 1. To reach tracker=3 via veto,
    the tracker must already be elevated (e.g., from failed elections that
    occurred *before* the successful election -- but a successful election
    resets it).

    The engine supports the chaos-from-veto code path (tracker >= 3 after
    veto consent). To test it, we directly set the election tracker to 2
    after the successful election resets it, simulating a state where the
    tracker was already elevated before the veto consent.
    """

    def test_veto_chaos_when_tracker_already_at_2(self):
        """If the election tracker is at 2 when a veto is accepted,
        the tracker reaches 3 and chaos fires."""
        engine = _setup_engine_with_veto_unlocked()

        president, chancellor = _drive_to_chancellor_phase(engine)

        # After the successful election, tracker was reset to 0.
        # Manually set it to 2 to simulate accumulated failures.
        engine._election_tracker = 2

        engine.submit_action(ChancellorEnact(player_id=chancellor, enact_index=None))

        policies_before = engine.liberal_policy_count + engine.fascist_policy_count

        result = engine.submit_action(VetoResponse(player_id=president, consent=True))

        # Chaos should have fired.
        assert "chaos" in result
        assert engine.election_tracker == 0  # reset after chaos

        # Exactly one policy top-decked.
        policies_after = engine.liberal_policy_count + engine.fascist_policy_count
        assert policies_after == policies_before + 1

    def test_chaos_top_decks_a_policy(self):
        """After chaos from veto, the round record should have a
        chaos_policy set."""
        engine = _setup_engine_with_veto_unlocked()

        president, chancellor = _drive_to_chancellor_phase(engine)
        engine._election_tracker = 2

        engine.submit_action(ChancellorEnact(player_id=chancellor, enact_index=None))
        engine.submit_action(VetoResponse(player_id=president, consent=True))

        # Find the round record with chaos.
        chaos_rounds = [r for r in engine.round_history if r.chaos_policy is not None]
        assert len(chaos_rounds) == 1
        assert chaos_rounds[0].chaos_policy in (
            PolicyType.LIBERAL,
            PolicyType.FASCIST,
        )

    def test_chaos_from_veto_resets_term_limits(self):
        """Chaos should reset term limits (last_elected_president and
        last_elected_chancellor become None)."""
        engine = _setup_engine_with_veto_unlocked()

        president, chancellor = _drive_to_chancellor_phase(engine)
        engine._election_tracker = 2

        engine.submit_action(ChancellorEnact(player_id=chancellor, enact_index=None))
        engine.submit_action(VetoResponse(player_id=president, consent=True))

        assert engine.last_elected_president is None
        assert engine.last_elected_chancellor is None

    def test_veto_at_tracker_1_does_not_trigger_chaos(self):
        """A veto when the tracker is at 1 brings it to 2, which is
        below the chaos threshold of 3."""
        engine = _setup_engine_with_veto_unlocked()

        president, chancellor = _drive_to_chancellor_phase(engine)
        engine._election_tracker = 1

        engine.submit_action(ChancellorEnact(player_id=chancellor, enact_index=None))

        result = engine.submit_action(VetoResponse(player_id=president, consent=True))

        assert "chaos" not in result
        assert engine.election_tracker == 2
        assert engine.phase == GamePhase.CHANCELLOR_NOMINATION


# ---------------------------------------------------------------------------
# 7. test_multiple_vetos_in_sequence
# ---------------------------------------------------------------------------


class TestMultipleVetosInSequence:
    """Veto in one round, then veto in the next round: verify the
    election tracker behavior across rounds.

    Key mechanic: a successful election resets the tracker to 0. A veto
    then adds 1. So consecutive veto rounds (each preceded by a successful
    election) always result in tracker=1 after each veto, NOT accumulating.
    """

    def test_tracker_resets_between_veto_rounds(self):
        """Two consecutive veto rounds each leave the tracker at 1,
        because the successful election in between resets it to 0."""
        engine = _setup_engine_with_veto_unlocked()

        assert engine.election_tracker == 0

        # First veto round.
        president1, chancellor1 = _drive_to_chancellor_phase(engine)
        engine.submit_action(ChancellorEnact(player_id=chancellor1, enact_index=None))
        engine.submit_action(VetoResponse(player_id=president1, consent=True))
        assert engine.election_tracker == 1

        # Second veto round: the successful election resets tracker to 0,
        # then veto brings it back to 1.
        president2, chancellor2 = _drive_to_chancellor_phase(engine)
        engine.submit_action(ChancellorEnact(player_id=chancellor2, enact_index=None))
        engine.submit_action(VetoResponse(player_id=president2, consent=True))
        # Tracker is 1 again (not 2), because the election reset it.
        assert engine.election_tracker == 1

    def test_veto_then_normal_enact_resets_tracker(self):
        """A veto followed by a normal enacted round (successful election)
        should show the tracker reset: successful elections reset tracker,
        then the enactment does not change it further."""
        engine = _setup_engine_with_veto_unlocked()

        # Veto round: tracker -> 1.
        president1, chancellor1 = _drive_to_chancellor_phase(engine)
        engine.submit_action(ChancellorEnact(player_id=chancellor1, enact_index=None))
        engine.submit_action(VetoResponse(player_id=president1, consent=True))
        assert engine.election_tracker == 1

        # Normal enact round: successful election resets tracker to 0.
        advance_round(engine)

        assert engine.election_tracker == 0

    def test_veto_refused_then_veto_accepted(self):
        """Refuse veto (chancellor must enact), then in the next round
        accept a veto. Only the accepted veto increments the tracker."""
        engine = _setup_engine_with_veto_unlocked()

        # Round 1: veto refused, chancellor enacts.
        president1, chancellor1 = _drive_to_chancellor_phase(engine)
        engine.submit_action(ChancellorEnact(player_id=chancellor1, enact_index=None))
        engine.submit_action(VetoResponse(player_id=president1, consent=False))
        engine.submit_action(ChancellorEnact(player_id=chancellor1, enact_index=0))

        if engine.is_game_over:
            pytest.skip("Game ended after enactment; cannot continue test.")

        # Tracker should be 0 (successful election resets, refused veto
        # does not increment).
        assert engine.election_tracker == 0

        # Round 2: veto accepted.
        president2, chancellor2 = _drive_to_chancellor_phase(engine)
        engine.submit_action(ChancellorEnact(player_id=chancellor2, enact_index=None))
        engine.submit_action(VetoResponse(player_id=president2, consent=True))
        assert engine.election_tracker == 1

    def test_veto_fresh_each_session(self):
        """In a new legislative session (new round), the chancellor should
        be able to request veto even if veto was refused in the previous
        session."""
        engine = _setup_engine_with_veto_unlocked()

        # Round 1: veto refused, chancellor enacts.
        president1, chancellor1 = _drive_to_chancellor_phase(engine)
        engine.submit_action(ChancellorEnact(player_id=chancellor1, enact_index=None))
        engine.submit_action(VetoResponse(player_id=president1, consent=False))
        engine.submit_action(ChancellorEnact(player_id=chancellor1, enact_index=0))

        if engine.is_game_over:
            pytest.skip("Game ended after enactment; cannot continue test.")

        # Round 2: veto should be available again.
        president2, chancellor2 = _drive_to_chancellor_phase(engine)

        pending = engine.pending_action
        assert None in pending.legal_targets, (
            "Veto option should be available in a new session even if it was refused in the previous session."
        )

        # And we should be able to actually request it.
        result = engine.submit_action(ChancellorEnact(player_id=chancellor2, enact_index=None))
        assert result["event"] == "veto_requested"
        assert engine.phase == GamePhase.VETO_RESPONSE


# ---------------------------------------------------------------------------
# Integration test: reach 5 fascist policies organically
# ---------------------------------------------------------------------------


class TestVetoThroughGameplay:
    """Verify veto mechanics by driving the engine through actual gameplay
    until 5 fascist policies are enacted organically."""

    def test_organic_veto_unlock(self):
        """Play enough rounds to enact 5 fascist policies and confirm
        veto unlocks, then exercise veto."""
        # Find a workable seed.
        seed = _find_seed_for_fascist_heavy_deck(num_players=7)
        engine = GameEngine(num_players=7, seed=seed)
        engine.setup()

        # Play rounds until veto unlocks.
        max_rounds = 20
        for _ in range(max_rounds):
            if engine.is_game_over:
                break
            if engine.veto_unlocked:
                break
            advance_round(engine)

        assert engine.veto_unlocked is True, f"Expected veto to unlock. Fascist policies: {engine.fascist_policy_count}"
        assert engine.fascist_policy_count >= 5

        if engine.is_game_over:
            pytest.skip("Game ended before we could test veto through gameplay.")

        # Now exercise veto.
        president, chancellor = _drive_to_chancellor_phase(engine)
        result = engine.submit_action(ChancellorEnact(player_id=chancellor, enact_index=None))
        assert result["event"] == "veto_requested"
        assert engine.phase == GamePhase.VETO_RESPONSE
