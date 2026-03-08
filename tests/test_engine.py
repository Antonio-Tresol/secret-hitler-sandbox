"""Comprehensive integration tests for the Secret Hitler GameEngine."""

from __future__ import annotations

import pytest

from game.engine import GameEngine
from game.roles import ROLE_DISTRIBUTION
from game.types import (
    CastVote,
    ChancellorEnact,
    ExecutePlayer,
    GameOverError,
    GamePhase,
    IllegalActionError,
    InvestigatePlayer,
    NominateChancellor,
    PolicyPeekAck,
    PresidentDiscard,
    Role,
    SpecialElection,
    WinCondition,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def handle_executive_action(engine: GameEngine) -> None:
    """Handle any executive action phase by choosing the first valid target or ack."""
    if engine.is_game_over:
        return

    phase = engine.phase
    if phase == GamePhase.EXECUTIVE_ACTION_INVESTIGATE:
        pending = engine.pending_action
        target = pending.legal_targets[0]
        engine.submit_action(InvestigatePlayer(player_id=pending.required_by, target_id=target))
    elif phase == GamePhase.EXECUTIVE_ACTION_PEEK:
        pending = engine.pending_action
        engine.submit_action(PolicyPeekAck(player_id=pending.required_by))
    elif phase == GamePhase.EXECUTIVE_ACTION_SPECIAL_ELECTION:
        pending = engine.pending_action
        target = pending.legal_targets[0]
        engine.submit_action(SpecialElection(player_id=pending.required_by, target_id=target))
    elif phase == GamePhase.EXECUTIVE_ACTION_EXECUTION:
        pending = engine.pending_action
        target = pending.legal_targets[0]
        engine.submit_action(ExecutePlayer(player_id=pending.required_by, target_id=target))


def advance_round(
    engine: GameEngine,
    chancellor_target: int | None = None,
    votes: dict[int, bool] | None = None,
    president_discard: int = 0,
    chancellor_enact: int = 0,
) -> None:
    """Drive engine through one complete round.

    If chancellor_target is None, the first eligible player is chosen.
    If votes is None, all living players vote Ja.
    """
    if engine.is_game_over:
        return

    pending = engine.pending_action
    president = pending.required_by

    if chancellor_target is None:
        chancellor_target = pending.legal_targets[0]
    engine.submit_action(NominateChancellor(player_id=president, target_id=chancellor_target))

    # Vote
    if votes is None:
        votes = {pid: True for pid in engine.living_players}
    for pid in engine.living_players:
        engine.submit_action(CastVote(player_id=pid, vote=votes.get(pid, True)))

    # Check if election failed or game ended
    if engine.is_game_over:
        return
    if engine.phase == GamePhase.CHANCELLOR_NOMINATION:
        return

    # Legislative session
    if engine.phase == GamePhase.LEGISLATIVE_PRESIDENT:
        engine.submit_action(PresidentDiscard(player_id=president, discard_index=president_discard))
    if engine.is_game_over:
        return
    if engine.phase == GamePhase.LEGISLATIVE_CHANCELLOR:
        engine.submit_action(ChancellorEnact(player_id=chancellor_target, enact_index=chancellor_enact))

    if engine.is_game_over:
        return

    # Handle executive actions
    handle_executive_action(engine)


def fail_election(engine: GameEngine) -> None:
    """Fail one election by having all living players vote Nein."""
    pending = engine.pending_action
    president = pending.required_by
    chancellor_target = pending.legal_targets[0]
    engine.submit_action(NominateChancellor(player_id=president, target_id=chancellor_target))
    for pid in engine.living_players:
        engine.submit_action(CastVote(player_id=pid, vote=False))


def find_hitler(engine: GameEngine) -> int:
    """Return the player_id of Hitler."""
    for pid in range(engine.num_players):
        if engine.get_player_role(pid) == Role.HITLER:
            return pid
    raise RuntimeError("No Hitler found")


def find_non_hitler(engine: GameEngine, exclude: set[int] | None = None) -> int:
    """Return a living non-Hitler player_id, excluding given ids."""
    if exclude is None:
        exclude = set()
    for pid in engine.living_players:
        if engine.get_player_role(pid) != Role.HITLER and pid not in exclude:
            return pid
    raise RuntimeError("No eligible non-Hitler player found")


# ---------------------------------------------------------------------------
# 1. test_setup_assigns_correct_roles
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("num_players", range(5, 11))
def test_setup_assigns_correct_roles(num_players: int):
    """Verify correct number of liberals, fascists, and exactly 1 Hitler."""
    engine = GameEngine(num_players=num_players, seed=42)
    engine.setup()

    expected_liberals, expected_fascists = ROLE_DISTRIBUTION[num_players]

    roles = [engine.get_player_role(pid) for pid in range(num_players)]
    assert roles.count(Role.LIBERAL) == expected_liberals
    assert roles.count(Role.FASCIST) == expected_fascists
    assert roles.count(Role.HITLER) == 1


# ---------------------------------------------------------------------------
# 2. test_setup_creates_shuffled_deck
# ---------------------------------------------------------------------------


def test_setup_creates_shuffled_deck():
    """After setup, the engine has 17 total policy tiles."""
    engine = GameEngine(num_players=7, seed=42)
    engine.setup()

    obs = engine.get_observation(0)
    total_tiles = obs["draw_pile_size"] + obs["discard_pile_size"]
    assert total_tiles == 17


# ---------------------------------------------------------------------------
# 3. test_full_game_liberal_policy_win
# ---------------------------------------------------------------------------


def test_full_game_liberal_policy_win():
    """Script a game where liberals enact 5 liberal policies."""
    # We need to find draws with liberal policies and select them.
    # Strategy: play many rounds, always trying to enact liberal when possible.
    # Use 5 players (smallest) with a seed that works.
    engine = GameEngine(num_players=5, seed=42)
    engine.setup()

    rounds = 0
    max_rounds = 100  # safety valve

    while not engine.is_game_over and rounds < max_rounds:
        rounds += 1
        pending = engine.pending_action
        president = pending.required_by
        chancellor_target = pending.legal_targets[0]

        # Avoid nominating Hitler as chancellor when >= 3 fascist policies
        hitler_id = find_hitler(engine)
        if chancellor_target == hitler_id and engine.fascist_policy_count >= 3:
            for alt in pending.legal_targets:
                if alt != hitler_id:
                    chancellor_target = alt
                    break

        engine.submit_action(NominateChancellor(player_id=president, target_id=chancellor_target))

        # Everyone votes Ja
        for pid in engine.living_players:
            engine.submit_action(CastVote(player_id=pid, vote=True))

        if engine.is_game_over:
            break
        if engine.phase == GamePhase.CHANCELLOR_NOMINATION:
            continue

        # Legislative: president examines 3 cards, tries to find liberal
        if engine.phase == GamePhase.LEGISLATIVE_PRESIDENT:
            obs = engine.get_observation(president)
            drawn = obs["drawn_policies"]
            # Find a fascist to discard (keep liberals)
            discard_idx = 0
            for i, p in enumerate(drawn):
                if p == "fascist":
                    discard_idx = i
                    break
            engine.submit_action(PresidentDiscard(player_id=president, discard_index=discard_idx))

        if engine.is_game_over:
            break

        if engine.phase == GamePhase.LEGISLATIVE_CHANCELLOR:
            obs = engine.get_observation(chancellor_target)
            received = obs["received_policies"]
            # Enact liberal if available
            enact_idx = 0
            for i, p in enumerate(received):
                if p == "liberal":
                    enact_idx = i
                    break
            engine.submit_action(ChancellorEnact(player_id=chancellor_target, enact_index=enact_idx))

        if engine.is_game_over:
            break

        handle_executive_action(engine)

    assert engine.is_game_over
    result = engine.result
    assert result.condition == WinCondition.LIBERAL_POLICY_WIN
    assert result.winner == "liberal"
    assert engine.liberal_policy_count == 5


# ---------------------------------------------------------------------------
# 4. test_full_game_fascist_policy_win
# ---------------------------------------------------------------------------


def test_full_game_fascist_policy_win():
    """Script a game where 6 fascist policies are enacted."""
    engine = GameEngine(num_players=5, seed=42)
    engine.setup()

    rounds = 0
    max_rounds = 100

    while not engine.is_game_over and rounds < max_rounds:
        rounds += 1
        pending = engine.pending_action
        president = pending.required_by
        chancellor_target = pending.legal_targets[0]

        # Avoid Hitler as chancellor when >= 3 fascist policies
        hitler_id = find_hitler(engine)
        if chancellor_target == hitler_id and engine.fascist_policy_count >= 3:
            for alt in pending.legal_targets:
                if alt != hitler_id:
                    chancellor_target = alt
                    break

        engine.submit_action(NominateChancellor(player_id=president, target_id=chancellor_target))

        for pid in engine.living_players:
            engine.submit_action(CastVote(player_id=pid, vote=True))

        if engine.is_game_over:
            break
        if engine.phase == GamePhase.CHANCELLOR_NOMINATION:
            continue

        # Legislative: always try to enact fascist
        if engine.phase == GamePhase.LEGISLATIVE_PRESIDENT:
            obs = engine.get_observation(president)
            drawn = obs["drawn_policies"]
            # Discard a liberal if possible
            discard_idx = 0
            for i, p in enumerate(drawn):
                if p == "liberal":
                    discard_idx = i
                    break
            engine.submit_action(PresidentDiscard(player_id=president, discard_index=discard_idx))

        if engine.is_game_over:
            break

        if engine.phase == GamePhase.LEGISLATIVE_CHANCELLOR:
            obs = engine.get_observation(chancellor_target)
            received = obs["received_policies"]
            enact_idx = 0
            for i, p in enumerate(received):
                if p == "fascist":
                    enact_idx = i
                    break
            engine.submit_action(ChancellorEnact(player_id=chancellor_target, enact_index=enact_idx))

        if engine.is_game_over:
            break

        handle_executive_action(engine)

    assert engine.is_game_over
    result = engine.result
    assert result.condition == WinCondition.FASCIST_POLICY_WIN
    assert result.winner == "fascist"
    assert engine.fascist_policy_count == 6


# ---------------------------------------------------------------------------
# 5. test_full_game_hitler_executed
# ---------------------------------------------------------------------------


def test_full_game_hitler_executed():
    """Script a game where Hitler is executed, verifying LIBERAL_HITLER_EXECUTED."""
    # Use 7 players (medium track: 4th fascist => EXECUTION power)
    # We need 4 fascist policies enacted to get execution power.
    engine = GameEngine(num_players=7, seed=42)
    engine.setup()

    hitler_id = find_hitler(engine)
    rounds = 0
    max_rounds = 100

    while not engine.is_game_over and rounds < max_rounds:
        rounds += 1

        if engine.fascist_policy_count >= 4:
            # We should now be at or eventually reach EXECUTION phase
            pass

        pending = engine.pending_action
        president = pending.required_by

        # Avoid Hitler as chancellor when >= 3 fascist
        chancellor_target = pending.legal_targets[0]
        if engine.fascist_policy_count >= 3:
            for alt in pending.legal_targets:
                if alt != hitler_id:
                    chancellor_target = alt
                    break

        engine.submit_action(NominateChancellor(player_id=president, target_id=chancellor_target))

        for pid in engine.living_players:
            engine.submit_action(CastVote(player_id=pid, vote=True))

        if engine.is_game_over:
            break
        if engine.phase == GamePhase.CHANCELLOR_NOMINATION:
            continue

        # Legislative: try to enact fascist to reach execution power
        if engine.phase == GamePhase.LEGISLATIVE_PRESIDENT:
            obs = engine.get_observation(president)
            drawn = obs["drawn_policies"]
            discard_idx = 0
            for i, p in enumerate(drawn):
                if p == "liberal":
                    discard_idx = i
                    break
            engine.submit_action(PresidentDiscard(player_id=president, discard_index=discard_idx))

        if engine.is_game_over:
            break

        if engine.phase == GamePhase.LEGISLATIVE_CHANCELLOR:
            obs = engine.get_observation(chancellor_target)
            received = obs["received_policies"]
            enact_idx = 0
            for i, p in enumerate(received):
                if p == "fascist":
                    enact_idx = i
                    break
            engine.submit_action(ChancellorEnact(player_id=chancellor_target, enact_index=enact_idx))

        if engine.is_game_over:
            break

        # Handle executive actions, but if it is execution, target Hitler
        phase = engine.phase
        if phase == GamePhase.EXECUTIVE_ACTION_EXECUTION:
            exec_pending = engine.pending_action
            if hitler_id in exec_pending.legal_targets:
                engine.submit_action(ExecutePlayer(player_id=exec_pending.required_by, target_id=hitler_id))
                break
            else:
                # Hitler is not a legal target (is the president); pick someone else
                engine.submit_action(
                    ExecutePlayer(
                        player_id=exec_pending.required_by,
                        target_id=exec_pending.legal_targets[0],
                    ),
                )
        else:
            handle_executive_action(engine)

    assert engine.is_game_over
    result = engine.result
    assert result.condition == WinCondition.LIBERAL_HITLER_EXECUTED
    assert result.winner == "liberal"


# ---------------------------------------------------------------------------
# 6. test_full_game_hitler_elected_chancellor
# ---------------------------------------------------------------------------


def test_full_game_hitler_elected_chancellor():
    """3+ fascist policies, then Hitler elected chancellor => FASCIST_HITLER_CHANCELLOR."""
    engine = GameEngine(num_players=7, seed=42)
    engine.setup()

    hitler_id = find_hitler(engine)
    rounds = 0
    max_rounds = 100

    while not engine.is_game_over and rounds < max_rounds:
        rounds += 1
        pending = engine.pending_action
        president = pending.required_by

        # If 3+ fascist policies, try to elect Hitler
        if engine.fascist_policy_count >= 3 and hitler_id in pending.legal_targets:
            engine.submit_action(NominateChancellor(player_id=president, target_id=hitler_id))
            for pid in engine.living_players:
                engine.submit_action(CastVote(player_id=pid, vote=True))
            break

        # Otherwise, keep enacting fascist policies
        chancellor_target = pending.legal_targets[0]
        if chancellor_target == hitler_id:
            # Pick someone else to avoid accidentally winning via Hitler chancellor
            # before we have 3 fascist
            for alt in pending.legal_targets:
                if alt != hitler_id:
                    chancellor_target = alt
                    break

        engine.submit_action(NominateChancellor(player_id=president, target_id=chancellor_target))

        for pid in engine.living_players:
            engine.submit_action(CastVote(player_id=pid, vote=True))

        if engine.is_game_over:
            break
        if engine.phase == GamePhase.CHANCELLOR_NOMINATION:
            continue

        # Enact fascist
        if engine.phase == GamePhase.LEGISLATIVE_PRESIDENT:
            obs = engine.get_observation(president)
            drawn = obs["drawn_policies"]
            discard_idx = 0
            for i, p in enumerate(drawn):
                if p == "liberal":
                    discard_idx = i
                    break
            engine.submit_action(PresidentDiscard(player_id=president, discard_index=discard_idx))

        if engine.is_game_over:
            break

        if engine.phase == GamePhase.LEGISLATIVE_CHANCELLOR:
            obs = engine.get_observation(chancellor_target)
            received = obs["received_policies"]
            enact_idx = 0
            for i, p in enumerate(received):
                if p == "fascist":
                    enact_idx = i
                    break
            engine.submit_action(ChancellorEnact(player_id=chancellor_target, enact_index=enact_idx))

        if engine.is_game_over:
            break

        handle_executive_action(engine)

    assert engine.is_game_over
    result = engine.result
    assert result.condition == WinCondition.FASCIST_HITLER_CHANCELLOR
    assert result.winner == "fascist"


# ---------------------------------------------------------------------------
# 7. test_hitler_chancellor_check_before_3_fascist
# ---------------------------------------------------------------------------


def test_hitler_chancellor_check_before_3_fascist():
    """Hitler elected as chancellor with < 3 fascist policies; game continues."""
    engine = GameEngine(num_players=5, seed=42)
    engine.setup()

    hitler_id = find_hitler(engine)

    assert engine.fascist_policy_count < 3

    pending = engine.pending_action
    president = pending.required_by

    # Ensure Hitler is eligible
    if hitler_id not in pending.legal_targets:
        # Just advance one round to change president
        advance_round(engine)
        pending = engine.pending_action
        president = pending.required_by

    # If Hitler is still not eligible (e.g. is the president), keep going
    attempts = 0
    while hitler_id not in pending.legal_targets and attempts < 10:
        advance_round(engine)
        if engine.is_game_over:
            break
        pending = engine.pending_action
        president = pending.required_by
        attempts += 1

    assert not engine.is_game_over
    assert engine.fascist_policy_count < 3
    assert hitler_id in pending.legal_targets

    # Nominate Hitler
    engine.submit_action(NominateChancellor(player_id=president, target_id=hitler_id))

    # Vote Ja
    for pid in engine.living_players:
        engine.submit_action(CastVote(player_id=pid, vote=True))

    # Game should NOT be over (< 3 fascist policies)
    assert not engine.is_game_over
    # Should be in legislative session
    assert engine.phase in (
        GamePhase.LEGISLATIVE_PRESIDENT,
        GamePhase.LEGISLATIVE_CHANCELLOR,
    )


# ---------------------------------------------------------------------------
# 8. test_election_failure_advances_tracker
# ---------------------------------------------------------------------------


def test_election_failure_advances_tracker():
    """Reject a government, verify tracker increments by 1."""
    engine = GameEngine(num_players=5, seed=42)
    engine.setup()

    assert engine.election_tracker == 0

    fail_election(engine)

    assert engine.election_tracker == 1


# ---------------------------------------------------------------------------
# 9. test_chaos_top_deck_at_3_rejections
# ---------------------------------------------------------------------------


def test_chaos_top_deck_at_3_rejections():
    """Reject 3 governments in a row, verify chaos enacts top policy and resets."""
    engine = GameEngine(num_players=5, seed=42)
    engine.setup()

    lib_before = engine.liberal_policy_count
    fas_before = engine.fascist_policy_count

    fail_election(engine)
    assert engine.election_tracker == 1

    fail_election(engine)
    assert engine.election_tracker == 2

    fail_election(engine)

    # After 3 rejections: chaos should have enacted a policy
    total_enacted = (engine.liberal_policy_count - lib_before) + (engine.fascist_policy_count - fas_before)
    assert total_enacted == 1

    # Tracker resets to 0
    if not engine.is_game_over:
        assert engine.election_tracker == 0

    # Term limits are reset (last_elected_president and last_elected_chancellor)
    if not engine.is_game_over:
        assert engine.last_elected_president is None
        assert engine.last_elected_chancellor is None


# ---------------------------------------------------------------------------
# 10. test_chaos_ignores_executive_power
# ---------------------------------------------------------------------------


def test_chaos_ignores_executive_power():
    """Chaos enacts a fascist policy that would normally trigger a power;
    verify no executive action phase occurs."""
    # Use 7 players (medium track). 2nd fascist => INVESTIGATE.
    # We need exactly 1 fascist policy already enacted, then chaos top-decks
    # a fascist. We must ensure the top of deck is fascist at chaos time.
    #
    # Strategy: enact 1 fascist policy normally, then fail 3 elections to
    # trigger chaos. We try many seeds to find one where chaos yields fascist.

    found_seed = None
    for seed in range(200):
        engine = GameEngine(num_players=7, seed=seed)
        engine.setup()

        # First: enact exactly 1 fascist policy
        # Play one round enacting fascist
        pending = engine.pending_action
        president = pending.required_by
        chancellor_target = pending.legal_targets[0]

        # Avoid Hitler
        hitler_id = find_hitler(engine)
        if chancellor_target == hitler_id:
            for alt in pending.legal_targets:
                if alt != hitler_id:
                    chancellor_target = alt
                    break

        engine.submit_action(NominateChancellor(player_id=president, target_id=chancellor_target))
        for pid in engine.living_players:
            engine.submit_action(CastVote(player_id=pid, vote=True))

        if engine.is_game_over:
            continue
        if engine.phase != GamePhase.LEGISLATIVE_PRESIDENT:
            continue

        obs = engine.get_observation(president)
        drawn = obs["drawn_policies"]

        # Need at least one fascist in the draw
        if "fascist" not in drawn:
            continue

        # Discard a liberal to keep fascists
        discard_idx = 0
        for i, p in enumerate(drawn):
            if p == "liberal":
                discard_idx = i
                break
        engine.submit_action(PresidentDiscard(player_id=president, discard_index=discard_idx))
        if engine.is_game_over:
            continue

        obs2 = engine.get_observation(chancellor_target)
        received = obs2["received_policies"]
        enact_idx = 0
        for i, p in enumerate(received):
            if p == "fascist":
                enact_idx = i
                break
        engine.submit_action(ChancellorEnact(player_id=chancellor_target, enact_index=enact_idx))

        if engine.is_game_over:
            continue

        # Handle any executive action from the 1st fascist (medium: NONE for 1st)
        handle_executive_action(engine)

        if engine.is_game_over:
            continue

        if engine.fascist_policy_count != 1:
            continue

        # Now fail 3 elections to trigger chaos
        fas_before = engine.fascist_policy_count
        fail_election(engine)
        if engine.is_game_over:
            continue
        fail_election(engine)
        if engine.is_game_over:
            continue
        fail_election(engine)

        # Check: did chaos enact a fascist policy?
        if engine.fascist_policy_count == fas_before + 1:
            # Fascist count is now 2. For medium track, 2nd fascist normally
            # triggers INVESTIGATE. But since it was chaos, no executive action.
            if not engine.is_game_over:
                # The engine should be at CHANCELLOR_NOMINATION, not any executive phase
                assert engine.phase == GamePhase.CHANCELLOR_NOMINATION
                assert engine.fascist_policy_count == 2
                found_seed = seed
                break

    assert found_seed is not None, (
        "Could not find a seed where chaos top-decks a fascist "
        "at the right moment. Consider expanding the search range."
    )


# ---------------------------------------------------------------------------
# 11. test_election_tracker_resets_on_successful_legislation
# ---------------------------------------------------------------------------


def test_election_tracker_resets_on_successful_legislation():
    """Fail one election, then pass one; verify tracker is 0."""
    engine = GameEngine(num_players=5, seed=42)
    engine.setup()

    # Fail one election
    fail_election(engine)
    assert engine.election_tracker == 1

    # Now pass one
    advance_round(engine)

    if not engine.is_game_over:
        assert engine.election_tracker == 0


# ---------------------------------------------------------------------------
# 12. test_presidential_rotation_skips_dead_players
# ---------------------------------------------------------------------------


def test_presidential_rotation_skips_dead_players():
    """Execute a player and verify presidency skips them."""
    # Use 7 players, medium track: 4th fascist => execution
    # We need to enact 4 fascist policies to get execution power.
    # After executing someone, check that they are skipped in rotation.

    engine = GameEngine(num_players=7, seed=42)
    engine.setup()

    hitler_id = find_hitler(engine)
    rounds = 0
    max_rounds = 100
    executed_player = None

    while not engine.is_game_over and rounds < max_rounds:
        rounds += 1

        pending = engine.pending_action
        president = pending.required_by
        chancellor_target = pending.legal_targets[0]

        if engine.fascist_policy_count >= 3 and chancellor_target == hitler_id:
            for alt in pending.legal_targets:
                if alt != hitler_id:
                    chancellor_target = alt
                    break

        engine.submit_action(NominateChancellor(player_id=president, target_id=chancellor_target))
        for pid in engine.living_players:
            engine.submit_action(CastVote(player_id=pid, vote=True))

        if engine.is_game_over:
            break
        if engine.phase == GamePhase.CHANCELLOR_NOMINATION:
            continue

        # Enact fascist to get to execution power
        if engine.phase == GamePhase.LEGISLATIVE_PRESIDENT:
            obs = engine.get_observation(president)
            drawn = obs["drawn_policies"]
            discard_idx = 0
            for i, p in enumerate(drawn):
                if p == "liberal":
                    discard_idx = i
                    break
            engine.submit_action(PresidentDiscard(player_id=president, discard_index=discard_idx))

        if engine.is_game_over:
            break

        if engine.phase == GamePhase.LEGISLATIVE_CHANCELLOR:
            obs = engine.get_observation(chancellor_target)
            received = obs["received_policies"]
            enact_idx = 0
            for i, p in enumerate(received):
                if p == "fascist":
                    enact_idx = i
                    break
            engine.submit_action(ChancellorEnact(player_id=chancellor_target, enact_index=enact_idx))

        if engine.is_game_over:
            break

        phase = engine.phase
        if phase == GamePhase.EXECUTIVE_ACTION_EXECUTION:
            exec_pending = engine.pending_action
            # Execute a non-Hitler player
            target = None
            for t in exec_pending.legal_targets:
                if t != hitler_id:
                    target = t
                    break
            if target is None:
                target = exec_pending.legal_targets[0]

            executed_player = target
            engine.submit_action(ExecutePlayer(player_id=exec_pending.required_by, target_id=target))

            if engine.is_game_over:
                break

            # Now verify: the dead player is not president
            assert executed_player not in engine.living_players

            # Track several rounds to confirm dead player is always skipped
            for _ in range(len(engine.living_players) + 1):
                if engine.is_game_over:
                    break
                assert engine.current_president != executed_player
                advance_round(engine)

            break
        else:
            handle_executive_action(engine)

    assert executed_player is not None, "Never reached execution phase"


# ---------------------------------------------------------------------------
# 13. test_pending_action_correct_at_each_phase
# ---------------------------------------------------------------------------


def test_pending_action_correct_at_each_phase():
    """Walk through a complete round verifying pending_action at each step."""
    engine = GameEngine(num_players=5, seed=42)
    engine.setup()

    # Phase 1: CHANCELLOR_NOMINATION
    pending = engine.pending_action
    assert pending.phase == GamePhase.CHANCELLOR_NOMINATION
    assert pending.expected_action == NominateChancellor
    assert isinstance(pending.required_by, int)
    assert len(pending.legal_targets) > 0

    president = pending.required_by
    chancellor_target = pending.legal_targets[0]

    engine.submit_action(NominateChancellor(player_id=president, target_id=chancellor_target))

    # Phase 2: ELECTION_VOTE
    pending = engine.pending_action
    assert pending.phase == GamePhase.ELECTION_VOTE
    assert pending.expected_action == CastVote
    assert isinstance(pending.required_by, list)
    assert set(pending.required_by) == set(engine.living_players)

    for pid in engine.living_players:
        engine.submit_action(CastVote(player_id=pid, vote=True))

    if engine.is_game_over:
        return

    # Phase 3: LEGISLATIVE_PRESIDENT
    pending = engine.pending_action
    assert pending.phase == GamePhase.LEGISLATIVE_PRESIDENT
    assert pending.expected_action == PresidentDiscard
    assert pending.required_by == president
    assert 0 in pending.legal_targets

    engine.submit_action(PresidentDiscard(player_id=president, discard_index=0))

    # Phase 4: LEGISLATIVE_CHANCELLOR
    pending = engine.pending_action
    assert pending.phase == GamePhase.LEGISLATIVE_CHANCELLOR
    assert pending.expected_action == ChancellorEnact
    assert pending.required_by == chancellor_target
    assert 0 in pending.legal_targets

    engine.submit_action(ChancellorEnact(player_id=chancellor_target, enact_index=0))

    # After enacting, should be either executive action or next nomination
    if not engine.is_game_over:
        pending = engine.pending_action
        assert pending.phase in (
            GamePhase.CHANCELLOR_NOMINATION,
            GamePhase.EXECUTIVE_ACTION_INVESTIGATE,
            GamePhase.EXECUTIVE_ACTION_PEEK,
            GamePhase.EXECUTIVE_ACTION_SPECIAL_ELECTION,
            GamePhase.EXECUTIVE_ACTION_EXECUTION,
        )


# ---------------------------------------------------------------------------
# 14. test_illegal_action_raises
# ---------------------------------------------------------------------------


class TestIllegalActionRaises:
    """Submit wrong action type for current phase, or from wrong player."""

    def test_wrong_action_type_for_phase(self):
        """Submit CastVote during CHANCELLOR_NOMINATION."""
        engine = GameEngine(num_players=5, seed=42)
        engine.setup()

        assert engine.phase == GamePhase.CHANCELLOR_NOMINATION
        with pytest.raises(IllegalActionError):
            engine.submit_action(CastVote(player_id=0, vote=True))

    def test_wrong_player_for_nomination(self):
        """A non-president tries to nominate."""
        engine = GameEngine(num_players=5, seed=42)
        engine.setup()

        pending = engine.pending_action
        president = pending.required_by
        # Pick a different player
        wrong_player = [pid for pid in engine.living_players if pid != president][0]

        with pytest.raises(IllegalActionError):
            engine.submit_action(NominateChancellor(player_id=wrong_player, target_id=0))

    def test_nominate_ineligible_player(self):
        """Nominate the president as chancellor (always ineligible)."""
        engine = GameEngine(num_players=5, seed=42)
        engine.setup()

        pending = engine.pending_action
        president = pending.required_by

        with pytest.raises(IllegalActionError):
            engine.submit_action(NominateChancellor(player_id=president, target_id=president))

    def test_wrong_player_for_discard(self):
        """A non-president tries to discard during legislative session."""
        engine = GameEngine(num_players=5, seed=42)
        engine.setup()

        pending = engine.pending_action
        president = pending.required_by
        chancellor_target = pending.legal_targets[0]

        engine.submit_action(NominateChancellor(player_id=president, target_id=chancellor_target))
        for pid in engine.living_players:
            engine.submit_action(CastVote(player_id=pid, vote=True))

        assert engine.phase == GamePhase.LEGISLATIVE_PRESIDENT
        with pytest.raises(IllegalActionError):
            engine.submit_action(PresidentDiscard(player_id=chancellor_target, discard_index=0))

    def test_wrong_player_for_enact(self):
        """A non-chancellor tries to enact during legislative session."""
        engine = GameEngine(num_players=5, seed=42)
        engine.setup()

        pending = engine.pending_action
        president = pending.required_by
        chancellor_target = pending.legal_targets[0]

        engine.submit_action(NominateChancellor(player_id=president, target_id=chancellor_target))
        for pid in engine.living_players:
            engine.submit_action(CastVote(player_id=pid, vote=True))

        engine.submit_action(PresidentDiscard(player_id=president, discard_index=0))
        assert engine.phase == GamePhase.LEGISLATIVE_CHANCELLOR
        with pytest.raises(IllegalActionError):
            engine.submit_action(ChancellorEnact(player_id=president, enact_index=0))

    def test_vote_during_nomination_phase(self):
        """Submit a vote when we are in nomination phase."""
        engine = GameEngine(num_players=5, seed=42)
        engine.setup()

        with pytest.raises(IllegalActionError):
            engine.submit_action(CastVote(player_id=0, vote=True))

    def test_invalid_discard_index(self):
        """Submit an out-of-range discard index."""
        engine = GameEngine(num_players=5, seed=42)
        engine.setup()

        pending = engine.pending_action
        president = pending.required_by
        chancellor_target = pending.legal_targets[0]

        engine.submit_action(NominateChancellor(player_id=president, target_id=chancellor_target))
        for pid in engine.living_players:
            engine.submit_action(CastVote(player_id=pid, vote=True))

        assert engine.phase == GamePhase.LEGISLATIVE_PRESIDENT
        with pytest.raises(IllegalActionError):
            engine.submit_action(PresidentDiscard(player_id=president, discard_index=5))

    def test_action_before_setup(self):
        """Submit an action before calling setup()."""
        engine = GameEngine(num_players=5, seed=42)
        with pytest.raises(IllegalActionError):
            engine.submit_action(CastVote(player_id=0, vote=True))


# ---------------------------------------------------------------------------
# 15. test_game_over_rejects_actions
# ---------------------------------------------------------------------------


def test_game_over_rejects_actions():
    """After game ends, submitting any action raises GameOverError."""
    engine = GameEngine(num_players=5, seed=42)
    engine.setup()

    # Play until game over
    rounds = 0
    while not engine.is_game_over and rounds < 200:
        rounds += 1
        advance_round(engine)

    assert engine.is_game_over

    with pytest.raises(GameOverError):
        engine.submit_action(CastVote(player_id=0, vote=True))

    with pytest.raises(GameOverError):
        engine.submit_action(NominateChancellor(player_id=0, target_id=1))

    with pytest.raises(GameOverError):
        engine.submit_action(PresidentDiscard(player_id=0, discard_index=0))

    # pending_action should also raise
    with pytest.raises(GameOverError):
        _ = engine.pending_action


# ---------------------------------------------------------------------------
# 16. test_deterministic_with_same_seed
# ---------------------------------------------------------------------------


def test_deterministic_with_same_seed():
    """Two engines with same seed + same actions produce identical outcomes."""

    def play_game(seed: int) -> tuple:
        """Play a full game with deterministic choices, return the result and history."""
        engine = GameEngine(num_players=7, seed=seed)
        engine.setup()

        roles = tuple(engine.get_player_role(pid) for pid in range(7))

        rounds = 0
        while not engine.is_game_over and rounds < 100:
            rounds += 1
            advance_round(engine)

        return (
            roles,
            engine.result,
            engine.liberal_policy_count,
            engine.fascist_policy_count,
            len(engine.round_history),
            [(r.round_number, r.elected, r.policy_enacted, r.chaos_policy) for r in engine.round_history],
        )

    result_a = play_game(seed=12345)
    result_b = play_game(seed=12345)

    assert result_a == result_b

    # Also verify different seed gives different outcome (with high probability)
    result_c = play_game(seed=99999)
    # Roles should differ (astronomically unlikely to be the same)
    assert result_a[0] != result_c[0]
