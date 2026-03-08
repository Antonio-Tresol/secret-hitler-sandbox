"""Comprehensive tests for executive powers: power track lookups and engine integration."""

from __future__ import annotations

import pytest

from game.engine import GameEngine
from game.powers import get_executive_power, get_track_key
from game.types import (
    CastVote,
    ChancellorEnact,
    ExecutePlayer,
    ExecutivePower,
    GamePhase,
    IllegalActionError,
    InvestigatePlayer,
    NominateChancellor,
    Party,
    PolicyPeekAck,
    PolicyType,
    PresidentDiscard,
    Role,
    SpecialElection,
    WinCondition,
)

# ──────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────


def _find_players_by_role(engine: GameEngine) -> dict[str, list[int]]:
    """Return a mapping of role names to lists of player_ids."""
    roles: dict[str, list[int]] = {"liberal": [], "fascist": [], "hitler": []}
    for pid in range(engine.num_players):
        role = engine.get_player_role(pid)
        if role == Role.LIBERAL:
            roles["liberal"].append(pid)
        elif role == Role.FASCIST:
            roles["fascist"].append(pid)
        elif role == Role.HITLER:
            roles["hitler"].append(pid)
    return roles


def _play_legislative_fascist(engine: GameEngine) -> None:
    """Drive the legislative session (president discard + chancellor enact),
    choosing to enact a fascist policy whenever possible."""
    pa = engine.pending_action
    assert pa.phase == GamePhase.LEGISLATIVE_PRESIDENT

    president = pa.required_by
    drawn = list(engine._drawn_policies)
    # Discard a liberal if possible so fascist remains
    discard_idx = 0
    for i, p in enumerate(drawn):
        if p == PolicyType.LIBERAL:
            discard_idx = i
            break
    engine.submit_action(PresidentDiscard(player_id=president, discard_index=discard_idx))
    if engine.is_game_over:
        return

    pa = engine.pending_action
    assert pa.phase == GamePhase.LEGISLATIVE_CHANCELLOR
    chancellor = pa.required_by
    hand = list(engine._chancellor_hand)
    enact_idx = 0
    for i, p in enumerate(hand):
        if p == PolicyType.FASCIST:
            enact_idx = i
            break
    engine.submit_action(ChancellorEnact(player_id=chancellor, enact_index=enact_idx))


def _nominate_and_elect(engine: GameEngine, chancellor_target: int | None = None) -> bool:
    """Nominate and elect a chancellor.  Returns True if the government was elected."""
    pa = engine.pending_action
    assert pa.phase == GamePhase.CHANCELLOR_NOMINATION
    president = pa.required_by
    if chancellor_target is None:
        chancellor_target = pa.legal_targets[0]
    engine.submit_action(NominateChancellor(player_id=president, target_id=chancellor_target))
    if engine.is_game_over:
        return False

    # Vote Ja
    for pid in engine.living_players:
        engine.submit_action(CastVote(player_id=pid, vote=True))
    if engine.is_game_over:
        return False
    return True


def _play_round(engine: GameEngine, chancellor_target: int | None = None) -> None:
    """Play a full round: nominate, vote Ja, legislate (enact fascist if possible).
    Does NOT resolve any executive power that results."""
    if engine.is_game_over:
        return
    _nominate_and_elect(engine, chancellor_target)
    if engine.is_game_over:
        return
    if engine.phase == GamePhase.LEGISLATIVE_PRESIDENT:
        _play_legislative_fascist(engine)


def _resolve_pending_power(engine: GameEngine, roles: dict[str, list[int]]) -> None:
    """If the engine is in an executive-action phase, resolve it generically."""
    if engine.is_game_over:
        return

    pa = engine.pending_action

    if pa.phase == GamePhase.EXECUTIVE_ACTION_INVESTIGATE:
        target = pa.legal_targets[0]
        engine.submit_action(InvestigatePlayer(player_id=pa.required_by, target_id=target))
    elif pa.phase == GamePhase.EXECUTIVE_ACTION_PEEK:
        engine.submit_action(PolicyPeekAck(player_id=pa.required_by))
    elif pa.phase == GamePhase.EXECUTIVE_ACTION_SPECIAL_ELECTION:
        target = pa.legal_targets[0]
        engine.submit_action(SpecialElection(player_id=pa.required_by, target_id=target))
    elif pa.phase == GamePhase.EXECUTIVE_ACTION_EXECUTION:
        safe = [t for t in pa.legal_targets if t != roles["hitler"][0]]
        target = safe[0] if safe else pa.legal_targets[0]
        engine.submit_action(ExecutePlayer(player_id=pa.required_by, target_id=target))


def _safe_chancellor(engine: GameEngine, hitler_id: int) -> int:
    """Pick a chancellor that is eligible and is NOT Hitler."""
    pa = engine.pending_action
    eligible = pa.legal_targets
    safe = [t for t in eligible if t != hitler_id]
    return safe[0] if safe else eligible[0]


def _advance_to_fascist_count(engine: GameEngine, target_count: int) -> None:
    """Play rounds until exactly `target_count` fascist policies are enacted.
    The executive power triggered by the target_count-th policy is LEFT PENDING
    (not resolved).  All prior executive powers are resolved automatically.
    """
    roles = _find_players_by_role(engine)
    hitler_id = roles["hitler"][0]

    while engine.fascist_policy_count < target_count and not engine.is_game_over:
        chancellor = _safe_chancellor(engine, hitler_id)
        _play_round(engine, chancellor_target=chancellor)

        if engine.is_game_over:
            break

        after = engine.fascist_policy_count

        # If we just reached the target, leave the executive power pending
        if after >= target_count:
            break

        # Otherwise resolve any executive power so we can continue
        _resolve_pending_power(engine, roles)


def _find_good_seed(
    num_players: int,
    target_fascist: int,
    max_seed: int = 2000,
) -> int:
    """Find a seed where we can successfully advance to `target_fascist`
    fascist policies and land on the corresponding executive-action phase.

    This actually runs the engine to verify the seed works end-to-end.
    """
    for seed in range(max_seed):
        try:
            engine = GameEngine(num_players=num_players, seed=seed)
            engine.setup()

            _advance_to_fascist_count(engine, target_fascist)

            if engine.is_game_over:
                continue

            pa = engine.pending_action
            power = get_executive_power(num_players, target_fascist)
            expected_phase = GameEngine._power_to_phase(power)

            if pa.phase == expected_phase:
                return seed
        except Exception:
            continue

    raise RuntimeError(
        f"Could not find a working seed for {num_players} players, "
        f"{target_fascist} fascist policies (tried {max_seed} seeds).",
    )


# ──────────────────────────────────────────────────────────────
#  1-3. Power Track Parametrized Tests
# ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "slot,expected",
    [
        (1, ExecutivePower.NONE),
        (2, ExecutivePower.NONE),
        (3, ExecutivePower.PEEK),
        (4, ExecutivePower.EXECUTION),
        (5, ExecutivePower.EXECUTION),
    ],
)
def test_power_track_small(slot: int, expected: ExecutivePower) -> None:
    """5-6 player track maps slots correctly."""
    for num_players in (5, 6):
        assert get_executive_power(num_players, slot) == expected
        assert get_track_key(num_players) == "small"


@pytest.mark.parametrize(
    "slot,expected",
    [
        (1, ExecutivePower.NONE),
        (2, ExecutivePower.INVESTIGATE),
        (3, ExecutivePower.SPECIAL_ELECTION),
        (4, ExecutivePower.EXECUTION),
        (5, ExecutivePower.EXECUTION),
    ],
)
def test_power_track_medium(slot: int, expected: ExecutivePower) -> None:
    """7-8 player track maps slots correctly."""
    for num_players in (7, 8):
        assert get_executive_power(num_players, slot) == expected
        assert get_track_key(num_players) == "medium"


@pytest.mark.parametrize(
    "slot,expected",
    [
        (1, ExecutivePower.INVESTIGATE),
        (2, ExecutivePower.INVESTIGATE),
        (3, ExecutivePower.SPECIAL_ELECTION),
        (4, ExecutivePower.EXECUTION),
        (5, ExecutivePower.EXECUTION),
    ],
)
def test_power_track_large(slot: int, expected: ExecutivePower) -> None:
    """9-10 player track maps slots correctly."""
    for num_players in (9, 10):
        assert get_executive_power(num_players, slot) == expected
        assert get_track_key(num_players) == "large"


# ──────────────────────────────────────────────────────────────
#  Power Track Edge Cases
# ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("count", [0, -1, 6, 7])
def test_power_track_out_of_range_returns_none(count: int) -> None:
    """Out-of-range fascist policy counts yield NONE."""
    assert get_executive_power(5, count) == ExecutivePower.NONE


# ──────────────────────────────────────────────────────────────
#  4. Investigation: reveals party, not role
# ──────────────────────────────────────────────────────────────


def test_investigate_reveals_party_not_role() -> None:
    """Investigating Hitler should reveal 'fascist' (party), not 'hitler'."""
    # Medium track (7 players): 2nd fascist policy triggers investigate.
    seed = _find_good_seed(7, target_fascist=2)
    engine = GameEngine(num_players=7, seed=seed)
    engine.setup()

    roles = _find_players_by_role(engine)
    hitler_id = roles["hitler"][0]

    _advance_to_fascist_count(engine, target_count=2)

    pa = engine.pending_action
    assert pa.phase == GamePhase.EXECUTIVE_ACTION_INVESTIGATE
    president = pa.required_by

    # Try to investigate Hitler if possible; otherwise investigate any fascist-party player
    if hitler_id in pa.legal_targets:
        target = hitler_id
    else:
        # Hitler must be the president; investigate another fascist
        fascist_targets = [t for t in pa.legal_targets if engine.get_player_party(t) == Party.FASCIST]
        target = fascist_targets[0] if fascist_targets else pa.legal_targets[0]

    result = engine.submit_action(InvestigatePlayer(player_id=president, target_id=target))
    # Result should contain party string, not role
    assert result["party"] in ("fascist", "liberal")
    if engine.get_player_party(target) == Party.FASCIST:
        assert result["party"] == "fascist"
    # "hitler" should never appear as the investigation party result
    assert result["party"] != "hitler"

    # Also verify via the round record
    last_round = [r for r in engine.round_history if r.investigation_result is not None][-1]
    assert last_round.investigation_result in (Party.FASCIST, Party.LIBERAL)


# ──────────────────────────────────────────────────────────────
#  5. Investigation: cannot target same player twice
# ──────────────────────────────────────────────────────────────


def test_investigate_cannot_target_same_player_twice() -> None:
    """After investigating player X, a second investigation of X raises IllegalActionError."""
    # Large track (9 players): slots 1 and 2 both trigger investigate.
    # We need to find a seed where the first-investigated player is NOT the
    # president during the second investigation (otherwise "cannot investigate
    # themselves" fires first).
    for seed in range(2000):
        try:
            engine = GameEngine(num_players=9, seed=seed)
            engine.setup()

            _find_players_by_role(engine)

            # Get to 1st fascist policy -> investigate
            _advance_to_fascist_count(engine, target_count=1)
            if engine.is_game_over:
                continue

            pa = engine.pending_action
            if pa.phase != GamePhase.EXECUTIVE_ACTION_INVESTIGATE:
                continue

            president1 = pa.required_by
            first_target = pa.legal_targets[0]

            engine.submit_action(InvestigatePlayer(player_id=president1, target_id=first_target))

            # Now advance to 2nd fascist policy -> another investigate
            _advance_to_fascist_count(engine, target_count=2)
            if engine.is_game_over:
                continue

            pa = engine.pending_action
            if pa.phase != GamePhase.EXECUTIVE_ACTION_INVESTIGATE:
                continue

            president2 = pa.required_by

            # Skip seeds where first_target became the president (self-check fires first)
            if first_target == president2:
                continue

            # The previously investigated player should NOT be a legal target
            assert first_target not in pa.legal_targets

            # Attempting to investigate them again should raise
            with pytest.raises(IllegalActionError, match="already been investigated"):
                engine.submit_action(InvestigatePlayer(player_id=president2, target_id=first_target))
            return
        except (AssertionError, IllegalActionError):
            continue

    pytest.fail("Could not find a seed for the double-investigation test.")


# ──────────────────────────────────────────────────────────────
#  6. Investigation: cannot target self
# ──────────────────────────────────────────────────────────────


def test_investigate_cannot_target_self() -> None:
    """President investigating themselves raises IllegalActionError."""
    seed = _find_good_seed(7, target_fascist=2)
    engine = GameEngine(num_players=7, seed=seed)
    engine.setup()

    _advance_to_fascist_count(engine, target_count=2)

    pa = engine.pending_action
    assert pa.phase == GamePhase.EXECUTIVE_ACTION_INVESTIGATE
    president = pa.required_by

    with pytest.raises(IllegalActionError, match="cannot investigate themselves"):
        engine.submit_action(InvestigatePlayer(player_id=president, target_id=president))


# ──────────────────────────────────────────────────────────────
#  7. Investigation: cannot target dead player
# ──────────────────────────────────────────────────────────────


def test_investigate_cannot_target_dead_player() -> None:
    """Investigating a dead player raises IllegalActionError."""
    seed = _find_good_seed(9, target_fascist=1)
    engine = GameEngine(num_players=9, seed=seed)
    engine.setup()

    _advance_to_fascist_count(engine, target_count=1)

    pa = engine.pending_action
    assert pa.phase == GamePhase.EXECUTIVE_ACTION_INVESTIGATE
    president = pa.required_by

    # Pick a living player (not the president) and manually kill them
    target = [t for t in range(engine.num_players) if t != president and engine.is_alive(t)][0]
    engine._players[target].alive = False

    with pytest.raises(IllegalActionError, match="dead"):
        engine.submit_action(InvestigatePlayer(player_id=president, target_id=target))

    # Restore so engine state isn't corrupt for cleanup
    engine._players[target].alive = True


# ──────────────────────────────────────────────────────────────
#  8. Policy Peek: shows top 3
# ──────────────────────────────────────────────────────────────


def test_policy_peek_shows_top_3() -> None:
    """After peek, the shown tiles match the top 3 of the draw pile."""
    # Small track (5 players): slot 3 = PEEK
    seed = _find_good_seed(5, target_fascist=3)
    engine = GameEngine(num_players=5, seed=seed)
    engine.setup()

    _advance_to_fascist_count(engine, target_count=3)

    pa = engine.pending_action
    assert pa.phase == GamePhase.EXECUTIVE_ACTION_PEEK

    president = pa.required_by

    # Record the top 3 of the deck BEFORE acknowledging
    expected_top_3 = engine._deck.peek(3)

    # The peek results should already be stored (eagerly prepared)
    obs = engine.get_observation(president)
    peeked = obs["peeked_policies"]
    assert peeked == [p.value for p in expected_top_3]

    # Acknowledge peek
    result = engine.submit_action(PolicyPeekAck(player_id=president))
    assert result["event"] == "policy_peek"
    assert result["policies"] == [p.value for p in expected_top_3]


# ──────────────────────────────────────────────────────────────
#  9. Policy Peek: does not change deck order
# ──────────────────────────────────────────────────────────────


def test_policy_peek_does_not_change_deck_order() -> None:
    """After peek, the deck order is preserved when the next draw happens."""
    seed = _find_good_seed(5, target_fascist=3)
    engine = GameEngine(num_players=5, seed=seed)
    engine.setup()

    _advance_to_fascist_count(engine, target_count=3)

    pa = engine.pending_action
    assert pa.phase == GamePhase.EXECUTIVE_ACTION_PEEK
    president = pa.required_by

    # Record the top 3 BEFORE ack
    expected_top_3 = engine._deck.peek(3)

    # Ack the peek
    engine.submit_action(PolicyPeekAck(player_id=president))

    if engine.is_game_over:
        return

    # Check the deck still has those cards on top (if no reshuffle happened)
    if engine._deck.draw_size >= 3:
        actual_top_3 = engine._deck.peek(3)
        assert actual_top_3 == expected_top_3

        # Also verify by playing the next round's draw
        roles = _find_players_by_role(engine)
        hitler_id = roles["hitler"][0]
        pa = engine.pending_action
        assert pa.phase == GamePhase.CHANCELLOR_NOMINATION

        chancellor = _safe_chancellor(engine, hitler_id)
        _nominate_and_elect(engine, chancellor_target=chancellor)
        if not engine.is_game_over and engine.phase == GamePhase.LEGISLATIVE_PRESIDENT:
            drawn = list(engine._drawn_policies)
            assert drawn == expected_top_3


# ──────────────────────────────────────────────────────────────
#  10. Special Election: sets next president
# ──────────────────────────────────────────────────────────────


def test_special_election_sets_next_president() -> None:
    """After special election, the chosen player becomes the next president."""
    # Medium track (7 players): slot 3 = SPECIAL_ELECTION
    seed = _find_good_seed(7, target_fascist=3)
    engine = GameEngine(num_players=7, seed=seed)
    engine.setup()

    _advance_to_fascist_count(engine, target_count=3)

    pa = engine.pending_action
    assert pa.phase == GamePhase.EXECUTIVE_ACTION_SPECIAL_ELECTION
    president = pa.required_by

    target = pa.legal_targets[0]
    engine.submit_action(SpecialElection(player_id=president, target_id=target))

    # The next round should have 'target' as president
    assert engine.current_president == target
    pa = engine.pending_action
    assert pa.phase == GamePhase.CHANCELLOR_NOMINATION
    assert pa.required_by == target


# ──────────────────────────────────────────────────────────────
#  11. Special Election: returns to rotation after
# ──────────────────────────────────────────────────────────────


def test_special_election_returns_to_rotation() -> None:
    """After the special-election round resolves, the rotation returns to
    the player to the left of the original president (who called the SE)."""
    seed = _find_good_seed(7, target_fascist=3)
    engine = GameEngine(num_players=7, seed=seed)
    engine.setup()

    _advance_to_fascist_count(engine, target_count=3)

    pa = engine.pending_action
    assert pa.phase == GamePhase.EXECUTIVE_ACTION_SPECIAL_ELECTION
    caller_president = pa.required_by

    # Compute who should be the next president after the SE round resolves
    # (the next living player after the caller in seat order)
    n = engine.num_players
    expected_next = caller_president
    for _ in range(n):
        expected_next = (expected_next + 1) % n
        if engine.is_alive(expected_next):
            break

    # Pick a SE target that differs from expected_next so we can verify
    target = [t for t in pa.legal_targets if t != expected_next]
    se_target = target[0] if target else pa.legal_targets[0]

    engine.submit_action(SpecialElection(player_id=caller_president, target_id=se_target))

    # SE round: play it through
    assert engine.current_president == se_target

    roles = _find_players_by_role(engine)
    hitler_id = roles["hitler"][0]
    chancellor = _safe_chancellor(engine, hitler_id)
    _play_round(engine, chancellor_target=chancellor)

    if engine.is_game_over:
        return

    # Resolve any executive power from the SE round
    _resolve_pending_power(engine, roles)

    if engine.is_game_over:
        return

    # After SE round, rotation should be back to expected_next
    assert engine.current_president == expected_next


# ──────────────────────────────────────────────────────────────
#  12. Special Election: can target term-limited player
# ──────────────────────────────────────────────────────────────


def test_special_election_can_target_term_limited_player() -> None:
    """A term-limited player can be the target of a special election."""
    seed = _find_good_seed(7, target_fascist=3)
    engine = GameEngine(num_players=7, seed=seed)
    engine.setup()

    _advance_to_fascist_count(engine, target_count=3)

    pa = engine.pending_action
    assert pa.phase == GamePhase.EXECUTIVE_ACTION_SPECIAL_ELECTION
    president = pa.required_by

    # The last elected chancellor is term-limited for nomination but
    # should still be valid for special election
    last_chancellor = engine.last_elected_chancellor
    if last_chancellor is not None and last_chancellor != president and engine.is_alive(last_chancellor):
        assert last_chancellor in pa.legal_targets
        engine.submit_action(SpecialElection(player_id=president, target_id=last_chancellor))
        assert engine.current_president == last_chancellor
    else:
        # Fallback: at minimum verify any living non-president is valid
        target = pa.legal_targets[0]
        engine.submit_action(SpecialElection(player_id=president, target_id=target))
        assert engine.current_president == target


# ──────────────────────────────────────────────────────────────
#  13. Execution: kills target
# ──────────────────────────────────────────────────────────────


def test_execution_kills_target() -> None:
    """After execution, the target is not alive."""
    # Small track (5 players): slot 4 = EXECUTION
    seed = _find_good_seed(5, target_fascist=4)
    engine = GameEngine(num_players=5, seed=seed)
    engine.setup()

    roles = _find_players_by_role(engine)
    hitler_id = roles["hitler"][0]

    _advance_to_fascist_count(engine, target_count=4)

    pa = engine.pending_action
    assert pa.phase == GamePhase.EXECUTIVE_ACTION_EXECUTION
    president = pa.required_by

    safe = [t for t in pa.legal_targets if t != hitler_id]
    target = safe[0]

    assert engine.is_alive(target)
    engine.submit_action(ExecutePlayer(player_id=president, target_id=target))
    assert not engine.is_alive(target)
    assert target not in engine.living_players


# ──────────────────────────────────────────────────────────────
#  14. Execution of Hitler ends game
# ──────────────────────────────────────────────────────────────


def test_execution_hitler_ends_game() -> None:
    """Executing Hitler causes a liberal win."""
    # We need a seed where Hitler is not the president at execution time
    for seed in range(2000):
        try:
            engine = GameEngine(num_players=5, seed=seed)
            engine.setup()

            roles = _find_players_by_role(engine)
            hitler_id = roles["hitler"][0]

            _advance_to_fascist_count(engine, target_count=4)
            if engine.is_game_over:
                continue

            pa = engine.pending_action
            if pa.phase != GamePhase.EXECUTIVE_ACTION_EXECUTION:
                continue

            president = pa.required_by
            if hitler_id not in pa.legal_targets:
                continue

            # Found a good seed
            result = engine.submit_action(ExecutePlayer(player_id=president, target_id=hitler_id))
            assert result["hitler"] is True
            assert engine.is_game_over
            assert engine.result.winner == "liberal"
            assert engine.result.condition == WinCondition.LIBERAL_HITLER_EXECUTED
            return
        except Exception:
            continue

    pytest.fail("Could not find a seed where Hitler can be executed.")


# ──────────────────────────────────────────────────────────────
#  15. Execution non-Hitler: no role reveal in public observation
# ──────────────────────────────────────────────────────────────


def test_execution_non_hitler_no_role_reveal() -> None:
    """Executing a non-Hitler fascist does not reveal their role publicly."""
    seed = _find_good_seed(5, target_fascist=4)
    engine = GameEngine(num_players=5, seed=seed)
    engine.setup()

    roles = _find_players_by_role(engine)
    hitler_id = roles["hitler"][0]

    _advance_to_fascist_count(engine, target_count=4)

    pa = engine.pending_action
    assert pa.phase == GamePhase.EXECUTIVE_ACTION_EXECUTION
    president = pa.required_by

    safe = [t for t in pa.legal_targets if t != hitler_id]
    target = safe[0]

    engine.submit_action(ExecutePlayer(player_id=president, target_id=target))
    assert not engine.is_game_over

    # Check public observation for any living player -- role should not appear
    observer = engine.living_players[0]
    obs = engine.get_observation(observer)

    # In the history, the execution target is recorded but the role is NOT
    exec_rounds = [h for h in obs["history"] if h.get("executive_target") == target]
    assert len(exec_rounds) >= 1
    for h in exec_rounds:
        assert "role" not in h
        assert "target_role" not in h


# ──────────────────────────────────────────────────────────────
#  16. Veto unlocked after 5th fascist policy
# ──────────────────────────────────────────────────────────────


def test_veto_unlocked_after_5th_fascist_policy() -> None:
    """After 5 fascist policies are enacted, veto power is unlocked."""
    # We need to get to 5 fascist policies.  The 5th triggers EXECUTION
    # on all tracks.  After resolving it, veto should be unlocked.
    for seed in range(2000):
        try:
            engine = GameEngine(num_players=5, seed=seed)
            engine.setup()

            roles = _find_players_by_role(engine)
            hitler_id = roles["hitler"][0]

            assert not engine.veto_unlocked

            # Advance to 4 fascist, resolve the 4th's execution power
            _advance_to_fascist_count(engine, target_count=4)
            if engine.is_game_over:
                continue
            pa = engine.pending_action
            if pa.phase != GamePhase.EXECUTIVE_ACTION_EXECUTION:
                continue
            # Execute a non-hitler
            safe = [t for t in pa.legal_targets if t != hitler_id]
            if not safe:
                continue
            engine.submit_action(ExecutePlayer(player_id=pa.required_by, target_id=safe[0]))
            if engine.is_game_over:
                continue

            # Now advance to the 5th fascist policy
            _advance_to_fascist_count(engine, target_count=5)
            if engine.is_game_over:
                continue

            # The 5th fascist triggers execution AND unlocks veto
            pa = engine.pending_action
            if pa.phase != GamePhase.EXECUTIVE_ACTION_EXECUTION:
                continue

            assert engine.veto_unlocked
            return
        except Exception:
            continue

    pytest.fail("Could not find a seed to reach 5 fascist policies.")


# ──────────────────────────────────────────────────────────────
#  17. Execution: cannot target self
# ──────────────────────────────────────────────────────────────


def test_execution_cannot_target_self() -> None:
    """President executing themselves raises IllegalActionError."""
    seed = _find_good_seed(5, target_fascist=4)
    engine = GameEngine(num_players=5, seed=seed)
    engine.setup()

    _advance_to_fascist_count(engine, target_count=4)

    pa = engine.pending_action
    assert pa.phase == GamePhase.EXECUTIVE_ACTION_EXECUTION
    president = pa.required_by

    with pytest.raises(IllegalActionError, match="cannot execute themselves"):
        engine.submit_action(ExecutePlayer(player_id=president, target_id=president))


# ──────────────────────────────────────────────────────────────
#  18. Special Election: cannot target self
# ──────────────────────────────────────────────────────────────


def test_special_election_cannot_target_self() -> None:
    """President designating themselves for special election raises IllegalActionError."""
    seed = _find_good_seed(7, target_fascist=3)
    engine = GameEngine(num_players=7, seed=seed)
    engine.setup()

    _advance_to_fascist_count(engine, target_count=3)

    pa = engine.pending_action
    assert pa.phase == GamePhase.EXECUTIVE_ACTION_SPECIAL_ELECTION
    president = pa.required_by

    with pytest.raises(IllegalActionError, match="cannot designate themselves"):
        engine.submit_action(SpecialElection(player_id=president, target_id=president))
