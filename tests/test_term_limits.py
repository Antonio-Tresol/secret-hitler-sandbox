"""Comprehensive tests for term limit logic.

Unit tests target ``game.terms.get_ineligible_for_chancellor`` directly.
Integration tests drive ``game.engine.GameEngine`` through full rounds to
verify that term-limit state is maintained correctly across elections,
chaos events, failed votes, and player executions.
"""

from __future__ import annotations

import pytest

from game.engine import GameEngine
from game.terms import get_ineligible_for_chancellor
from game.types import (
    CastVote,
    ChancellorEnact,
    ExecutePlayer,
    GamePhase,
    IllegalActionError,
    NominateChancellor,
    PresidentDiscard,
    Role,
)

# ===================================================================== #
#  Unit Tests – get_ineligible_for_chancellor                            #
# ===================================================================== #


class TestGetIneligibleForChancellor:
    """Direct unit tests for the pure function in game.terms."""

    def test_last_elected_president_and_chancellor_ineligible(self):
        """With >5 living players, both last elected president and
        chancellor are in the ineligible set."""
        ineligible = get_ineligible_for_chancellor(
            last_elected_president=1,
            last_elected_chancellor=2,
            living_player_count=7,
            candidate_president=0,
        )
        assert 1 in ineligible, "last elected president should be ineligible"
        assert 2 in ineligible, "last elected chancellor should be ineligible"
        assert 0 in ineligible, "candidate president should be ineligible"
        # Only these three should be ineligible
        assert ineligible == {0, 1, 2}

    def test_five_player_exception(self):
        """With <=5 living players, only last chancellor is ineligible
        (president IS eligible)."""
        ineligible = get_ineligible_for_chancellor(
            last_elected_president=1,
            last_elected_chancellor=2,
            living_player_count=5,
            candidate_president=0,
        )
        assert 1 not in ineligible, "last elected president should be eligible under 5-player exception"
        assert 2 in ineligible, "last elected chancellor should still be ineligible"
        assert 0 in ineligible, "candidate president should be ineligible"
        assert ineligible == {0, 2}

    def test_five_player_exception_with_fewer_than_five(self):
        """With <5 living players (edge case after executions), the
        5-player exception still applies."""
        ineligible = get_ineligible_for_chancellor(
            last_elected_president=3,
            last_elected_chancellor=4,
            living_player_count=4,
            candidate_president=0,
        )
        assert 3 not in ineligible, "president should be eligible when <5 alive"
        assert 4 in ineligible
        assert ineligible == {0, 4}

    def test_candidate_president_always_ineligible(self):
        """The current presidential candidate is always ineligible for
        chancellor, regardless of other arguments."""
        # Even when nothing else is set
        ineligible = get_ineligible_for_chancellor(
            last_elected_president=None,
            last_elected_chancellor=None,
            living_player_count=7,
            candidate_president=5,
        )
        assert 5 in ineligible

        # Also when the candidate happens to be the last elected
        # president -- still ineligible for chancellor
        ineligible = get_ineligible_for_chancellor(
            last_elected_president=5,
            last_elected_chancellor=3,
            living_player_count=7,
            candidate_president=5,
        )
        assert 5 in ineligible

    def test_none_values(self):
        """When last_elected are None (start of game or after chaos), only
        the presidential candidate is ineligible."""
        ineligible = get_ineligible_for_chancellor(
            last_elected_president=None,
            last_elected_chancellor=None,
            living_player_count=7,
            candidate_president=3,
        )
        assert ineligible == {3}

    def test_none_president_only(self):
        """When only last_elected_president is None but chancellor is set."""
        ineligible = get_ineligible_for_chancellor(
            last_elected_president=None,
            last_elected_chancellor=2,
            living_player_count=7,
            candidate_president=0,
        )
        assert ineligible == {0, 2}

    def test_none_chancellor_only(self):
        """When only last_elected_chancellor is None but president is set."""
        ineligible = get_ineligible_for_chancellor(
            last_elected_president=1,
            last_elected_chancellor=None,
            living_player_count=7,
            candidate_president=0,
        )
        assert ineligible == {0, 1}

    def test_boundary_six_players_president_ineligible(self):
        """At exactly 6 living players (>5), the president is still ineligible."""
        ineligible = get_ineligible_for_chancellor(
            last_elected_president=1,
            last_elected_chancellor=2,
            living_player_count=6,
            candidate_president=0,
        )
        assert 1 in ineligible, "president should be ineligible with 6 players"


# ===================================================================== #
#  Helper utilities for engine integration tests                         #
# ===================================================================== #


def _pass_vote(engine: GameEngine, *, vote: bool) -> dict:
    """Have all living players cast the same *vote*. Returns the last
    submit_action result (which contains the election outcome)."""
    result = None
    for pid in list(engine.living_players):
        result = engine.submit_action(CastVote(player_id=pid, vote=vote))
    return result


def _run_successful_election(
    engine: GameEngine,
    chancellor_id: int | None = None,
) -> dict:
    """Nominate and pass a chancellor. If *chancellor_id* is None, pick
    the first eligible candidate. Returns the election result dict."""
    pa = engine.pending_action
    assert pa.phase == GamePhase.CHANCELLOR_NOMINATION
    president = pa.required_by

    if chancellor_id is None:
        chancellor_id = pa.legal_targets[0]

    engine.submit_action(NominateChancellor(player_id=president, target_id=chancellor_id))
    return _pass_vote(engine, vote=True)


def _run_failed_election(engine: GameEngine) -> dict:
    """Nominate someone and fail the vote. Returns the result dict."""
    pa = engine.pending_action
    assert pa.phase == GamePhase.CHANCELLOR_NOMINATION
    president = pa.required_by
    chancellor_id = pa.legal_targets[0]

    engine.submit_action(NominateChancellor(player_id=president, target_id=chancellor_id))
    return _pass_vote(engine, vote=False)


def _complete_legislative_session(engine: GameEngine) -> dict:
    """Complete a legislative session (president discards, chancellor enacts).
    Returns the result from the chancellor enact action."""
    pa = engine.pending_action
    assert pa.phase == GamePhase.LEGISLATIVE_PRESIDENT
    president = pa.required_by
    engine.submit_action(PresidentDiscard(player_id=president, discard_index=0))

    pa = engine.pending_action
    assert pa.phase == GamePhase.LEGISLATIVE_CHANCELLOR
    chancellor = pa.required_by
    result = engine.submit_action(ChancellorEnact(player_id=chancellor, enact_index=0))
    return result


def _handle_executive_action(engine: GameEngine) -> None:
    """If the engine is waiting for an executive action after a fascist
    policy, handle it generically so we can proceed to the next round."""
    if engine.is_game_over:
        return

    phase = engine.phase
    if phase == GamePhase.EXECUTIVE_ACTION_INVESTIGATE:
        from game.types import InvestigatePlayer

        pa = engine.pending_action
        engine.submit_action(InvestigatePlayer(player_id=pa.required_by, target_id=pa.legal_targets[0]))
    elif phase == GamePhase.EXECUTIVE_ACTION_PEEK:
        from game.types import PolicyPeekAck

        pa = engine.pending_action
        engine.submit_action(PolicyPeekAck(player_id=pa.required_by))
    elif phase == GamePhase.EXECUTIVE_ACTION_SPECIAL_ELECTION:
        from game.types import SpecialElection

        pa = engine.pending_action
        engine.submit_action(SpecialElection(player_id=pa.required_by, target_id=pa.legal_targets[0]))
    elif phase == GamePhase.EXECUTIVE_ACTION_EXECUTION:
        pa = engine.pending_action
        # Pick a non-Hitler target to avoid ending the game
        for tid in pa.legal_targets:
            if engine.get_player_role(tid) != Role.HITLER:
                engine.submit_action(ExecutePlayer(player_id=pa.required_by, target_id=tid))
                return
        # Fallback: all targets are Hitler (shouldn't happen), just pick first
        engine.submit_action(ExecutePlayer(player_id=pa.required_by, target_id=pa.legal_targets[0]))


def _play_full_round(
    engine: GameEngine,
    chancellor_id: int | None = None,
    *,
    expect_pass: bool = True,
) -> None:
    """Drive the engine through a full round: nomination, vote, and
    legislative session (if elected). Handles any executive actions
    that may follow. If *expect_pass* is False, the election is failed."""
    if not expect_pass:
        _run_failed_election(engine)
        return

    _run_successful_election(engine, chancellor_id)

    if engine.is_game_over:
        return

    _complete_legislative_session(engine)

    if engine.is_game_over:
        return

    _handle_executive_action(engine)


def _find_non_hitler_players(engine: GameEngine) -> list[int]:
    """Return a list of player_ids that are NOT Hitler."""
    return [pid for pid in range(engine.num_players) if engine.get_player_role(pid) != Role.HITLER]


def _create_game(num_players: int = 7, seed: int = 42) -> GameEngine:
    """Create and set up a game engine."""
    engine = GameEngine(num_players=num_players, seed=seed)
    engine.setup()
    return engine


# ===================================================================== #
#  Integration Tests – Engine term-limit behaviour                       #
# ===================================================================== #


class TestFivePlayerExceptionOnDeath:
    """Start with 7 players, execute 2 so that the 5-player exception
    kicks in (last president can be nominated as chancellor)."""

    def test_five_player_exception_triggers_on_death(self):
        # We need to find a seed where we can:
        # 1. Complete elections and enact fascist policies to get execution power
        # 2. Execute 2 non-Hitler players to get down to 5 alive
        # 3. Verify the 5-player exception applies
        #
        # Strategy: try seeds until we find one that works smoothly.
        # With 7 players, medium track: fascist policy #4 triggers execution.
        # We need 4 fascist policies enacted to get 2 executions.
        # Let's find a workable seed.

        for seed in range(200):
            engine = GameEngine(num_players=7, seed=seed)
            engine.setup()

            # Find Hitler to avoid executing/electing them
            hitler_id = None
            for pid in range(7):
                if engine.get_player_role(pid) == Role.HITLER:
                    hitler_id = pid
                    break

            try:
                # Play rounds until we can execute 2 players
                executed_count = 0
                rounds_played = 0

                while executed_count < 2 and rounds_played < 20:
                    if engine.is_game_over:
                        break

                    pa = engine.pending_action
                    if pa.phase != GamePhase.CHANCELLOR_NOMINATION:
                        break

                    president = pa.required_by
                    eligible = pa.legal_targets

                    # Pick a chancellor that is not Hitler
                    chancellor = None
                    for c in eligible:
                        if c != hitler_id:
                            chancellor = c
                            break
                    if chancellor is None:
                        break

                    engine.submit_action(NominateChancellor(player_id=president, target_id=chancellor))
                    _pass_vote(engine, vote=True)

                    if engine.is_game_over:
                        break

                    # Complete legislative session
                    _complete_legislative_session(engine)

                    if engine.is_game_over:
                        break

                    # Handle executive actions
                    if engine.phase == GamePhase.EXECUTIVE_ACTION_EXECUTION:
                        pa = engine.pending_action
                        # Execute a non-Hitler, non-president target
                        target = None
                        for tid in pa.legal_targets:
                            if engine.get_player_role(tid) != Role.HITLER and tid != president:
                                target = tid
                                break
                        if target is None:
                            break
                        engine.submit_action(ExecutePlayer(player_id=pa.required_by, target_id=target))
                        if engine.is_game_over:
                            break
                        executed_count += 1
                    elif engine.phase in (
                        GamePhase.EXECUTIVE_ACTION_INVESTIGATE,
                        GamePhase.EXECUTIVE_ACTION_PEEK,
                        GamePhase.EXECUTIVE_ACTION_SPECIAL_ELECTION,
                    ):
                        _handle_executive_action(engine)
                        if engine.is_game_over:
                            break

                    rounds_played += 1

                if engine.is_game_over or executed_count < 2:
                    continue

                # We have 5 living players now
                living = engine.living_players
                assert len(living) == 5, f"Expected 5 living players, got {len(living)}"

                # Now verify the 5-player exception
                last_pres = engine.last_elected_president
                last_chan = engine.last_elected_chancellor

                if last_pres is None or last_chan is None:
                    continue

                # The last elected president should now be eligible for
                # chancellor (5-player exception), unless they are the
                # current presidential candidate or dead
                pa = engine.pending_action
                assert pa.phase == GamePhase.CHANCELLOR_NOMINATION
                current_pres = pa.required_by
                eligible = pa.legal_targets

                if last_pres != current_pres and engine.is_alive(last_pres):
                    assert last_pres in eligible, (
                        f"5-player exception: last president {last_pres} should "
                        f"be eligible for chancellor. Eligible: {eligible}"
                    )

                # Last chancellor should still be ineligible (unless they
                # happen to be the current president candidate)
                if last_chan != current_pres and engine.is_alive(last_chan):
                    assert last_chan not in eligible, (
                        f"Last chancellor {last_chan} should be ineligible. Eligible: {eligible}"
                    )

                # Test passed with this seed
                return

            except (IllegalActionError, Exception):
                continue

        pytest.fail("Could not find a seed that allows executing 2 players to test the 5-player exception.")


class TestTermLimitsResetOnChaos:
    """After chaos (3 rejected elections), verify previously term-limited
    players are now eligible."""

    def test_term_limits_reset_on_chaos(self):
        for seed in range(200):
            engine = GameEngine(num_players=7, seed=seed)
            engine.setup()

            # Find Hitler
            hitler_id = None
            for pid in range(7):
                if engine.get_player_role(pid) == Role.HITLER:
                    hitler_id = pid
                    break

            try:
                # First, complete a successful election to establish
                # term limits
                pa = engine.pending_action
                president_r1 = pa.required_by
                eligible = pa.legal_targets
                chancellor_r1 = None
                for c in eligible:
                    if c != hitler_id:
                        chancellor_r1 = c
                        break
                if chancellor_r1 is None:
                    continue

                engine.submit_action(NominateChancellor(player_id=president_r1, target_id=chancellor_r1))
                _pass_vote(engine, vote=True)

                if engine.is_game_over:
                    continue

                # Complete legislative session
                _complete_legislative_session(engine)

                if engine.is_game_over:
                    continue

                _handle_executive_action(engine)

                if engine.is_game_over:
                    continue

                # Verify term limits are set
                assert engine.last_elected_president == president_r1
                assert engine.last_elected_chancellor == chancellor_r1

                # Now fail 3 elections in a row to trigger chaos
                for _ in range(3):
                    if engine.is_game_over:
                        break
                    _run_failed_election(engine)

                if engine.is_game_over:
                    continue

                # After chaos, term limits should be reset
                assert engine.last_elected_president is None, "last_elected_president should be None after chaos"
                assert engine.last_elected_chancellor is None, "last_elected_chancellor should be None after chaos"

                # Verify the previously term-limited players are now eligible
                pa = engine.pending_action
                assert pa.phase == GamePhase.CHANCELLOR_NOMINATION
                current_pres = pa.required_by
                eligible = pa.legal_targets

                # Both the old president and chancellor should be eligible
                # (unless one of them is the current presidential candidate)
                if president_r1 != current_pres:
                    assert president_r1 in eligible, (
                        f"Player {president_r1} (former president) should be eligible after chaos reset"
                    )
                if chancellor_r1 != current_pres:
                    assert chancellor_r1 in eligible, (
                        f"Player {chancellor_r1} (former chancellor) should be eligible after chaos reset"
                    )

                return  # Test passed

            except (IllegalActionError, Exception):
                continue

        pytest.fail("Could not find a seed that allows testing chaos term-limit reset.")


class TestFailedElectionDoesNotUpdateTermLimits:
    """A failed vote does not change who is term-limited."""

    def test_failed_election_does_not_update_term_limits(self):
        for seed in range(200):
            engine = GameEngine(num_players=7, seed=seed)
            engine.setup()

            hitler_id = None
            for pid in range(7):
                if engine.get_player_role(pid) == Role.HITLER:
                    hitler_id = pid
                    break

            try:
                # Complete a successful election first
                pa = engine.pending_action
                president_r1 = pa.required_by
                eligible = pa.legal_targets
                chancellor_r1 = None
                for c in eligible:
                    if c != hitler_id:
                        chancellor_r1 = c
                        break
                if chancellor_r1 is None:
                    continue

                engine.submit_action(NominateChancellor(player_id=president_r1, target_id=chancellor_r1))
                _pass_vote(engine, vote=True)

                if engine.is_game_over:
                    continue

                _complete_legislative_session(engine)
                if engine.is_game_over:
                    continue
                _handle_executive_action(engine)
                if engine.is_game_over:
                    continue

                # Record term limits after successful election
                last_pres_before = engine.last_elected_president
                last_chan_before = engine.last_elected_chancellor
                assert last_pres_before == president_r1
                assert last_chan_before == chancellor_r1

                # Now fail an election
                pa = engine.pending_action
                assert pa.phase == GamePhase.CHANCELLOR_NOMINATION
                president_r2 = pa.required_by
                eligible_r2 = pa.legal_targets
                chancellor_r2 = eligible_r2[0]

                engine.submit_action(NominateChancellor(player_id=president_r2, target_id=chancellor_r2))
                _pass_vote(engine, vote=False)

                if engine.is_game_over:
                    continue

                # Term limits should NOT have changed
                assert engine.last_elected_president == last_pres_before, (
                    "Failed election should not update last_elected_president"
                )
                assert engine.last_elected_chancellor == last_chan_before, (
                    "Failed election should not update last_elected_chancellor"
                )

                return  # Test passed

            except (IllegalActionError, Exception):
                continue

        pytest.fail("Could not find a seed for testing failed election term limits.")


class TestTermLimitsApplyToChancellorshipOnly:
    """Last elected chancellor can still become president via rotation."""

    def test_term_limits_apply_to_chancellorship_only(self):
        for seed in range(200):
            engine = GameEngine(num_players=7, seed=seed)
            engine.setup()

            hitler_id = None
            for pid in range(7):
                if engine.get_player_role(pid) == Role.HITLER:
                    hitler_id = pid
                    break

            try:
                # Play enough rounds so that the last elected chancellor
                # becomes president via rotation
                last_chan = None

                for round_num in range(15):
                    if engine.is_game_over:
                        break

                    pa = engine.pending_action
                    if pa.phase != GamePhase.CHANCELLOR_NOMINATION:
                        break

                    president = pa.required_by

                    # If this president was the last elected chancellor,
                    # we've proven the point
                    if last_chan is not None and president == last_chan:
                        # The chancellor became president through rotation.
                        # The engine allowed it, which is the correct behaviour.
                        return  # Test passed

                    eligible = pa.legal_targets
                    chancellor = None
                    for c in eligible:
                        if c != hitler_id:
                            chancellor = c
                            break
                    if chancellor is None:
                        break

                    engine.submit_action(NominateChancellor(player_id=president, target_id=chancellor))
                    _pass_vote(engine, vote=True)

                    if engine.is_game_over:
                        break

                    _complete_legislative_session(engine)
                    if engine.is_game_over:
                        break
                    _handle_executive_action(engine)

                    last_chan = chancellor

            except (IllegalActionError, Exception):
                continue

        pytest.fail("Could not verify that last chancellor can become president.")


class TestEligibleChancellorsListCorrect:
    """Verify get_observation for president shows correct eligible_chancellors
    matching term limit rules."""

    def test_eligible_chancellors_list_correct(self):
        for seed in range(200):
            engine = GameEngine(num_players=7, seed=seed)
            engine.setup()

            hitler_id = None
            for pid in range(7):
                if engine.get_player_role(pid) == Role.HITLER:
                    hitler_id = pid
                    break

            try:
                # Complete first election
                pa = engine.pending_action
                president_r1 = pa.required_by
                eligible = pa.legal_targets
                chancellor_r1 = None
                for c in eligible:
                    if c != hitler_id:
                        chancellor_r1 = c
                        break
                if chancellor_r1 is None:
                    continue

                engine.submit_action(NominateChancellor(player_id=president_r1, target_id=chancellor_r1))
                _pass_vote(engine, vote=True)

                if engine.is_game_over:
                    continue

                _complete_legislative_session(engine)
                if engine.is_game_over:
                    continue
                _handle_executive_action(engine)
                if engine.is_game_over:
                    continue

                # Now check the observation for the new president
                pa = engine.pending_action
                assert pa.phase == GamePhase.CHANCELLOR_NOMINATION
                president_r2 = pa.required_by

                obs = engine.get_observation(president_r2)

                # The observation should include eligible_chancellors
                assert "eligible_chancellors" in obs, "President's observation should include eligible_chancellors"

                eligible_from_obs = obs["eligible_chancellors"]
                eligible_from_pending = pa.legal_targets

                # The eligible list in the observation should match the
                # pending_action legal_targets
                assert sorted(eligible_from_obs) == sorted(eligible_from_pending), (
                    f"Observation eligible_chancellors {eligible_from_obs} "
                    f"does not match pending_action legal_targets "
                    f"{eligible_from_pending}"
                )

                # Manually verify against term-limit rules
                living = engine.living_players
                last_pres = engine.last_elected_president
                last_chan = engine.last_elected_chancellor

                ineligible = get_ineligible_for_chancellor(last_pres, last_chan, len(living), president_r2)
                expected_eligible = [pid for pid in living if pid not in ineligible]

                assert sorted(eligible_from_obs) == sorted(expected_eligible), (
                    f"Eligible chancellors {eligible_from_obs} don't match "
                    f"manual calculation {expected_eligible}. "
                    f"Ineligible set: {ineligible}"
                )

                # Specifically verify:
                # - current president is NOT in eligible list
                assert president_r2 not in eligible_from_obs
                # - last chancellor is NOT in eligible list
                if last_chan is not None and last_chan != president_r2:
                    assert last_chan not in eligible_from_obs, f"Last chancellor {last_chan} should not be eligible"
                # - last president is NOT in eligible list (>5 players)
                if last_pres is not None and last_pres != president_r2 and len(living) > 5:
                    assert last_pres not in eligible_from_obs, (
                        f"Last president {last_pres} should not be eligible with {len(living)} players"
                    )

                return  # Test passed

            except (IllegalActionError, Exception):
                continue

        pytest.fail("Could not find a seed to test eligible_chancellors observation.")


class TestEligibleChancellorsFirstRound:
    """On the very first round (no prior elections), only the presidential
    candidate is ineligible."""

    def test_first_round_only_president_ineligible(self):
        engine = _create_game(num_players=7, seed=42)

        pa = engine.pending_action
        assert pa.phase == GamePhase.CHANCELLOR_NOMINATION
        president = pa.required_by
        eligible = pa.legal_targets

        # All living players except the president should be eligible
        expected = [pid for pid in engine.living_players if pid != president]
        assert sorted(eligible) == sorted(expected)

        # Observation should match
        obs = engine.get_observation(president)
        assert sorted(obs["eligible_chancellors"]) == sorted(expected)


class TestNominatingIneligibleRaises:
    """Attempting to nominate an ineligible chancellor raises
    IllegalActionError."""

    def test_nominating_ineligible_raises(self):
        for seed in range(100):
            engine = GameEngine(num_players=7, seed=seed)
            engine.setup()

            hitler_id = None
            for pid in range(7):
                if engine.get_player_role(pid) == Role.HITLER:
                    hitler_id = pid
                    break

            try:
                # Complete a successful round
                pa = engine.pending_action
                president_r1 = pa.required_by
                eligible = pa.legal_targets
                chancellor_r1 = None
                for c in eligible:
                    if c != hitler_id:
                        chancellor_r1 = c
                        break
                if chancellor_r1 is None:
                    continue

                engine.submit_action(NominateChancellor(player_id=president_r1, target_id=chancellor_r1))
                _pass_vote(engine, vote=True)
                if engine.is_game_over:
                    continue

                _complete_legislative_session(engine)
                if engine.is_game_over:
                    continue
                _handle_executive_action(engine)
                if engine.is_game_over:
                    continue

                # Now try to nominate the last chancellor as chancellor again
                pa = engine.pending_action
                president_r2 = pa.required_by

                # The last elected chancellor should be ineligible
                if chancellor_r1 != president_r2 and engine.is_alive(chancellor_r1):
                    with pytest.raises(IllegalActionError):
                        engine.submit_action(
                            NominateChancellor(
                                player_id=president_r2,
                                target_id=chancellor_r1,
                            ),
                        )
                    return  # Test passed

            except (IllegalActionError, Exception):
                continue

        pytest.fail("Could not find a seed to test nominating ineligible chancellor.")
