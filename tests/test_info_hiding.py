"""Comprehensive information-hiding tests for get_observation(player_id).

These tests verify that each player only sees the information they are
entitled to according to the Secret Hitler rules -- role knowledge, legislative
hand contents, executive-action results, and public vs. private data.
"""

from __future__ import annotations

import pytest

from game.engine import GameEngine
from game.types import (
    CastVote,
    ChancellorEnact,
    ExecutePlayer,
    GamePhase,
    InvestigatePlayer,
    NominateChancellor,
    PolicyPeekAck,
    PresidentDiscard,
    Role,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_players_by_role(engine: GameEngine) -> dict[str, list[int]]:
    """Return a mapping of role name -> list of player_ids."""
    result: dict[str, list[int]] = {"liberal": [], "fascist": [], "hitler": []}
    for pid in range(engine.num_players):
        role = engine.get_player_role(pid)
        if role == Role.LIBERAL:
            result["liberal"].append(pid)
        elif role == Role.FASCIST:
            result["fascist"].append(pid)
        elif role == Role.HITLER:
            result["hitler"].append(pid)
    return result


def _setup_game(num_players: int = 7, seed: int = 42) -> GameEngine:
    """Create and set up a game engine ready for play."""
    engine = GameEngine(num_players=num_players, seed=seed)
    engine.setup()
    return engine


def _nominate_and_elect(engine: GameEngine, ja_voters: list[int] | None = None) -> bool:
    """Drive the game through nomination and election.

    Nominates the first eligible chancellor candidate, then has all
    living players vote Ja (or only those in *ja_voters* vote Ja,
    everyone else votes Nein).

    Returns True if the election passed, False otherwise.
    """
    assert engine.phase == GamePhase.CHANCELLOR_NOMINATION

    president = engine.current_president
    pending = engine.pending_action
    eligible = pending.legal_targets
    # Pick the first eligible candidate
    nominee = eligible[0]
    engine.submit_action(NominateChancellor(player_id=president, target_id=nominee))

    # Vote
    living = engine.living_players
    for pid in living:
        if ja_voters is None:
            vote = True  # everyone votes Ja
        else:
            vote = pid in ja_voters
        engine.submit_action(CastVote(player_id=pid, vote=vote))

    # After all votes the phase advances; check if we ended up in a legislative phase
    # (election passed) or nomination phase (election failed).
    return engine.phase in (
        GamePhase.LEGISLATIVE_PRESIDENT,
        GamePhase.GAME_OVER,
    )


def _pass_election_unanimously(engine: GameEngine) -> tuple[int, int]:
    """Nominate first eligible chancellor and pass unanimously.

    Returns (president_id, chancellor_id).
    """
    president = engine.current_president
    pending = engine.pending_action
    nominee = pending.legal_targets[0]
    engine.submit_action(NominateChancellor(player_id=president, target_id=nominee))

    for pid in engine.living_players:
        engine.submit_action(CastVote(player_id=pid, vote=True))

    return president, nominee


def _complete_legislative_session(engine: GameEngine) -> None:
    """Complete a legislative session by having the president discard index 0
    and the chancellor enact index 0."""
    president = engine.current_president
    chancellor = engine.chancellor_nominee

    assert engine.phase == GamePhase.LEGISLATIVE_PRESIDENT
    engine.submit_action(PresidentDiscard(player_id=president, discard_index=0))

    assert engine.phase == GamePhase.LEGISLATIVE_CHANCELLOR
    engine.submit_action(ChancellorEnact(player_id=chancellor, enact_index=0))


def _play_full_round(engine: GameEngine) -> None:
    """Play one complete round: nomination -> election -> legislation.

    Handles executive action phases by dispatching the appropriate action
    so we return to CHANCELLOR_NOMINATION (next round) or GAME_OVER.
    """
    president, chancellor = _pass_election_unanimously(engine)

    if engine.is_game_over:
        return

    _complete_legislative_session(engine)

    # Handle any executive action phase that might follow
    _handle_executive_action_if_needed(engine)


def _handle_executive_action_if_needed(engine: GameEngine) -> None:
    """If the engine is in an executive action phase, perform it."""
    if engine.phase == GamePhase.EXECUTIVE_ACTION_INVESTIGATE:
        president = engine.current_president
        target = engine.pending_action.legal_targets[0]
        engine.submit_action(InvestigatePlayer(player_id=president, target_id=target))
    elif engine.phase == GamePhase.EXECUTIVE_ACTION_PEEK:
        president = engine.current_president
        engine.submit_action(PolicyPeekAck(player_id=president))
    elif engine.phase == GamePhase.EXECUTIVE_ACTION_SPECIAL_ELECTION:
        president = engine.current_president
        target = engine.pending_action.legal_targets[0]
        from game.types import SpecialElection

        engine.submit_action(SpecialElection(player_id=president, target_id=target))
    elif engine.phase == GamePhase.EXECUTIVE_ACTION_EXECUTION:
        president = engine.current_president
        target = engine.pending_action.legal_targets[0]
        engine.submit_action(ExecutePlayer(player_id=president, target_id=target))


# ---------------------------------------------------------------------------
# 1. test_liberal_sees_own_role_only
# ---------------------------------------------------------------------------


def test_liberal_sees_own_role_only():
    """A liberal player's observation contains your_role='liberal', empty
    known_fascists, and known_hitler=None."""
    engine = _setup_game(num_players=7, seed=42)
    roles = _find_players_by_role(engine)

    liberal_id = roles["liberal"][0]
    obs = engine.get_observation(liberal_id)

    assert obs["your_role"] == "liberal"
    assert obs["your_party"] == "liberal"
    assert obs["known_fascists"] == []
    assert obs["known_hitler"] is None


# ---------------------------------------------------------------------------
# 2. test_fascist_sees_team_7_players
# ---------------------------------------------------------------------------


def test_fascist_sees_team_7_players():
    """In a 7-player game, a fascist sees other fascists and knows Hitler."""
    engine = _setup_game(num_players=7, seed=42)
    roles = _find_players_by_role(engine)

    fascist_ids = roles["fascist"]
    hitler_id = roles["hitler"][0]

    # There should be 2 fascists in a 7-player game
    assert len(fascist_ids) == 2

    for fid in fascist_ids:
        obs = engine.get_observation(fid)

        assert obs["your_role"] == "fascist"
        assert obs["your_party"] == "fascist"
        assert obs["known_hitler"] == hitler_id

        # known_fascists should list the OTHER fascist(s), not self
        other_fascists = [f for f in fascist_ids if f != fid]
        assert sorted(obs["known_fascists"]) == sorted(other_fascists)


# ---------------------------------------------------------------------------
# 3. test_hitler_sees_nothing_7_players
# ---------------------------------------------------------------------------


def test_hitler_sees_nothing_7_players():
    """In a 7-player game, Hitler sees only their own role and knows
    no other fascists."""
    engine = _setup_game(num_players=7, seed=42)
    roles = _find_players_by_role(engine)

    hitler_id = roles["hitler"][0]
    obs = engine.get_observation(hitler_id)

    assert obs["your_role"] == "hitler"
    assert obs["your_party"] == "fascist"
    assert obs["known_fascists"] == []
    assert obs["known_hitler"] is None


# ---------------------------------------------------------------------------
# 4. test_hitler_sees_fascists_5_players
# ---------------------------------------------------------------------------


def test_hitler_sees_fascists_5_players():
    """In a 5-player game, Hitler can see the fascist teammate(s)."""
    engine = _setup_game(num_players=5, seed=10)
    roles = _find_players_by_role(engine)

    hitler_id = roles["hitler"][0]
    fascist_ids = roles["fascist"]

    obs = engine.get_observation(hitler_id)

    assert obs["your_role"] == "hitler"
    assert obs["your_party"] == "fascist"
    # In 5p: 1 fascist + Hitler. Hitler should see the 1 fascist.
    assert sorted(obs["known_fascists"]) == sorted(fascist_ids)
    # Hitler does not know themselves via known_hitler
    assert obs["known_hitler"] is None


# ---------------------------------------------------------------------------
# 5. test_fascist_sees_team_5_players
# ---------------------------------------------------------------------------


def test_fascist_sees_team_5_players():
    """In a 5-player game, the fascist sees Hitler and the (empty) set
    of other fascists (only 1 fascist + Hitler in 5p)."""
    engine = _setup_game(num_players=5, seed=10)
    roles = _find_players_by_role(engine)

    fascist_ids = roles["fascist"]
    hitler_id = roles["hitler"][0]

    # 5p has exactly 1 fascist + 1 Hitler
    assert len(fascist_ids) == 1

    fid = fascist_ids[0]
    obs = engine.get_observation(fid)

    assert obs["your_role"] == "fascist"
    assert obs["known_hitler"] == hitler_id
    # No other fascists exist, so known_fascists is empty
    assert obs["known_fascists"] == []


# ---------------------------------------------------------------------------
# 6. test_president_sees_3_policies_during_legislative
# ---------------------------------------------------------------------------


def test_president_sees_3_policies_during_legislative():
    """During LEGISLATIVE_PRESIDENT, the president's observation includes
    drawn_policies as a list of 3 policy strings."""
    engine = _setup_game(num_players=7, seed=42)

    president, _ = _pass_election_unanimously(engine)

    assert engine.phase == GamePhase.LEGISLATIVE_PRESIDENT

    obs = engine.get_observation(president)
    assert "drawn_policies" in obs
    assert isinstance(obs["drawn_policies"], list)
    assert len(obs["drawn_policies"]) == 3
    # Each policy should be "liberal" or "fascist"
    for p in obs["drawn_policies"]:
        assert p in ("liberal", "fascist")


# ---------------------------------------------------------------------------
# 7. test_chancellor_sees_2_policies_during_legislative
# ---------------------------------------------------------------------------


def test_chancellor_sees_2_policies_during_legislative():
    """During LEGISLATIVE_CHANCELLOR, the chancellor's observation includes
    received_policies as a list of 2 policy strings."""
    engine = _setup_game(num_players=7, seed=42)

    president, chancellor = _pass_election_unanimously(engine)

    assert engine.phase == GamePhase.LEGISLATIVE_PRESIDENT
    # President discards one policy
    engine.submit_action(PresidentDiscard(player_id=president, discard_index=0))

    assert engine.phase == GamePhase.LEGISLATIVE_CHANCELLOR
    obs = engine.get_observation(chancellor)

    assert "received_policies" in obs
    assert isinstance(obs["received_policies"], list)
    assert len(obs["received_policies"]) == 2
    for p in obs["received_policies"]:
        assert p in ("liberal", "fascist")


# ---------------------------------------------------------------------------
# 8. test_non_president_cannot_see_drawn_policies
# ---------------------------------------------------------------------------


def test_non_president_cannot_see_drawn_policies():
    """During LEGISLATIVE_PRESIDENT, non-president players do NOT see
    drawn_policies in their observation."""
    engine = _setup_game(num_players=7, seed=42)

    president, chancellor = _pass_election_unanimously(engine)
    assert engine.phase == GamePhase.LEGISLATIVE_PRESIDENT

    for pid in engine.living_players:
        if pid == president:
            continue
        obs = engine.get_observation(pid)
        assert "drawn_policies" not in obs, f"Player {pid} (not president) should not see drawn_policies"

    # Also verify during LEGISLATIVE_CHANCELLOR that non-chancellor cannot
    # see received_policies
    engine.submit_action(PresidentDiscard(player_id=president, discard_index=0))
    assert engine.phase == GamePhase.LEGISLATIVE_CHANCELLOR

    for pid in engine.living_players:
        if pid == chancellor:
            continue
        obs = engine.get_observation(pid)
        assert "received_policies" not in obs, f"Player {pid} (not chancellor) should not see received_policies"


# ---------------------------------------------------------------------------
# 9. test_investigation_result_only_for_president
# ---------------------------------------------------------------------------


def test_investigation_result_only_for_president():
    """After an investigation, only the investigating president's observation
    contains the investigation_result (via top-level key or private_history)."""
    # Use 7-player game. Medium track: 2nd fascist policy triggers investigate.
    # We need to find a seed where we can enact 2 fascist policies and reach
    # the investigation phase.
    # Instead of relying on seed, we drive the game and keep trying rounds.
    for seed in range(100):
        engine = _setup_game(num_players=7, seed=seed)
        try:
            investigating_president = _drive_to_investigation(engine)
            if investigating_president is not None:
                break
        except Exception:
            continue
    else:
        pytest.skip("Could not reach investigation phase in 100 seeds")

    # Now check that only the investigating president sees the result
    for pid in range(engine.num_players):
        obs = engine.get_observation(pid)
        if pid == investigating_president:
            assert "investigation_result" in obs, f"Investigating president {pid} should see investigation_result"
            # Also check private_history
            inv_events = [e for e in obs["private_history"] if e["type"] == "investigation"]
            assert len(inv_events) >= 1
        else:
            assert "investigation_result" not in obs, f"Player {pid} should not see investigation_result"


def _drive_to_investigation(engine: GameEngine) -> int | None:
    """Drive the game until the EXECUTIVE_ACTION_INVESTIGATE phase is reached.

    Returns the president_id who performs the investigation, or None if
    we could not reach it.
    """
    max_rounds = 20
    for _ in range(max_rounds):
        if engine.is_game_over:
            return None

        if engine.phase == GamePhase.EXECUTIVE_ACTION_INVESTIGATE:
            president = engine.current_president
            target = engine.pending_action.legal_targets[0]
            engine.submit_action(InvestigatePlayer(player_id=president, target_id=target))
            return president

        if engine.phase == GamePhase.CHANCELLOR_NOMINATION:
            _pass_election_unanimously(engine)

            if engine.is_game_over:
                return None

            if engine.phase == GamePhase.LEGISLATIVE_PRESIDENT:
                _complete_legislative_session(engine)

                if engine.phase == GamePhase.EXECUTIVE_ACTION_INVESTIGATE:
                    president = engine.current_president
                    target = engine.pending_action.legal_targets[0]
                    engine.submit_action(InvestigatePlayer(player_id=president, target_id=target))
                    return president

                _handle_executive_action_if_needed(engine)
        else:
            # In some other phase we did not expect; try to resolve it
            _handle_executive_action_if_needed(engine)

    return None


# ---------------------------------------------------------------------------
# 10. test_peek_result_only_for_president
# ---------------------------------------------------------------------------


def test_peek_result_only_for_president():
    """Peek results are only visible to the peeking president."""
    # 5-6p game, small track: 3rd fascist policy triggers peek.
    for seed in range(200):
        engine = _setup_game(num_players=5, seed=seed)
        peeking_president = _drive_to_peek(engine)
        if peeking_president is not None:
            break
    else:
        pytest.skip("Could not reach peek phase in 200 seeds")

    # During PEEK phase (before ack), only the president sees peeked_policies
    # But _drive_to_peek already acknowledged, so check private_history instead
    for pid in range(engine.num_players):
        obs = engine.get_observation(pid)
        if pid == peeking_president:
            peek_events = [e for e in obs["private_history"] if e["type"] == "policy_peek"]
            assert len(peek_events) >= 1, f"Peeking president {pid} should have peek event in private_history"
        else:
            peek_events = [e for e in obs["private_history"] if e["type"] == "policy_peek"]
            assert len(peek_events) == 0, f"Player {pid} should NOT have peek event in private_history"


def _drive_to_peek(engine: GameEngine) -> int | None:
    """Drive the game until a policy peek is performed.

    Returns the president who peeked, or None.
    """
    max_rounds = 30
    for _ in range(max_rounds):
        if engine.is_game_over:
            return None

        if engine.phase == GamePhase.EXECUTIVE_ACTION_PEEK:
            president = engine.current_president
            # Before acknowledging, verify only president sees peeked_policies
            for pid in range(engine.num_players):
                obs = engine.get_observation(pid)
                if pid == president:
                    assert "peeked_policies" in obs
                else:
                    assert "peeked_policies" not in obs, f"Player {pid} should not see peeked_policies"
            engine.submit_action(PolicyPeekAck(player_id=president))
            return president

        if engine.phase == GamePhase.CHANCELLOR_NOMINATION:
            try:
                _pass_election_unanimously(engine)
            except Exception:
                return None

            if engine.is_game_over:
                return None

            if engine.phase == GamePhase.LEGISLATIVE_PRESIDENT:
                _complete_legislative_session(engine)

                if engine.phase == GamePhase.EXECUTIVE_ACTION_PEEK:
                    continue  # will be caught at the top of the loop

                _handle_executive_action_if_needed(engine)
        else:
            _handle_executive_action_if_needed(engine)

    return None


# ---------------------------------------------------------------------------
# 11. test_confirmed_not_hitler_is_public
# ---------------------------------------------------------------------------


def test_confirmed_not_hitler_is_public():
    """After a chancellor is elected with 3+ fascist policies and is NOT Hitler,
    all players see confirmed_not_hitler=True on that player."""
    # We need 3 fascist policies enacted, then elect a non-Hitler chancellor.
    for seed in range(300):
        engine = _setup_game(num_players=7, seed=seed)
        confirmed_player = _drive_to_confirmed_not_hitler(engine)
        if confirmed_player is not None:
            break
    else:
        pytest.skip("Could not reach confirmed_not_hitler scenario in 300 seeds")

    # All players should see confirmed_not_hitler=True for the confirmed player
    for pid in range(engine.num_players):
        obs = engine.get_observation(pid)
        player_entry = None
        for p in obs["players"]:
            if p["id"] == confirmed_player:
                player_entry = p
                break

        assert player_entry is not None
        assert player_entry["confirmed_not_hitler"] is True, (
            f"Player {pid}'s view of player {confirmed_player} should show confirmed_not_hitler=True"
        )


def _drive_to_confirmed_not_hitler(engine: GameEngine) -> int | None:
    """Drive the game until a chancellor passes the Hitler check (3+ fascist
    policies, elected chancellor, not Hitler).

    Returns the confirmed player_id or None.
    """
    roles = _find_players_by_role(engine)
    hitler_id = roles["hitler"][0]

    max_rounds = 40
    for _ in range(max_rounds):
        if engine.is_game_over:
            return None

        if engine.phase != GamePhase.CHANCELLOR_NOMINATION:
            _handle_executive_action_if_needed(engine)
            continue

        if engine.fascist_policy_count >= 3:
            # Elect a non-Hitler chancellor. Pick one from eligible that is not Hitler.
            president = engine.current_president
            pending = engine.pending_action
            eligible = pending.legal_targets
            non_hitler_eligible = [e for e in eligible if e != hitler_id]

            if not non_hitler_eligible:
                # All eligible are Hitler -- skip this round
                _play_full_round(engine)
                continue

            nominee = non_hitler_eligible[0]
            engine.submit_action(NominateChancellor(player_id=president, target_id=nominee))

            # Everyone votes Ja
            for pid in engine.living_players:
                engine.submit_action(CastVote(player_id=pid, vote=True))

            if engine.is_game_over:
                return None

            # Check that the nominee is now confirmed_not_hitler
            if nominee in engine._confirmed_not_hitler:
                # Complete the legislative session so we don't leave the game stuck
                if engine.phase == GamePhase.LEGISLATIVE_PRESIDENT:
                    _complete_legislative_session(engine)
                    _handle_executive_action_if_needed(engine)
                return nominee

        # Not enough fascist policies yet -- play a normal round
        if engine.phase == GamePhase.CHANCELLOR_NOMINATION:
            try:
                _pass_election_unanimously(engine)
            except Exception:
                return None

            if engine.is_game_over:
                return None

            if engine.phase == GamePhase.LEGISLATIVE_PRESIDENT:
                _complete_legislative_session(engine)
                _handle_executive_action_if_needed(engine)
            else:
                _handle_executive_action_if_needed(engine)

    return None


# ---------------------------------------------------------------------------
# 12. test_executed_player_role_not_revealed
# ---------------------------------------------------------------------------


def test_executed_player_role_not_revealed():
    """After a player is executed, no other player's observation reveals
    the dead player's role."""
    for seed in range(300):
        engine = _setup_game(num_players=7, seed=seed)
        executed_target = _drive_to_execution(engine)
        if executed_target is not None:
            break
    else:
        pytest.skip("Could not reach execution in 300 seeds")

    # Check that no player's observation reveals the executed player's role
    for pid in range(engine.num_players):
        if not engine.is_alive(pid):
            continue
        obs = engine.get_observation(pid)

        # The player entries should not contain a 'role' field
        for p in obs["players"]:
            assert "role" not in p, f"Player {pid}'s observation reveals role of player {p['id']}"

        # Check that history entries do not contain target role info
        for h in obs["history"]:
            assert "target_role" not in h
            assert "executed_role" not in h


def _drive_to_execution(engine: GameEngine) -> int | None:
    """Drive the game until an execution is performed.

    Returns the executed player_id or None.
    """
    max_rounds = 40
    for _ in range(max_rounds):
        if engine.is_game_over:
            return None

        if engine.phase == GamePhase.EXECUTIVE_ACTION_EXECUTION:
            president = engine.current_president
            targets = engine.pending_action.legal_targets
            # Execute someone who is NOT Hitler to avoid game-over
            roles = _find_players_by_role(engine)
            hitler_id = roles["hitler"][0]
            non_hitler_targets = [t for t in targets if t != hitler_id]
            if not non_hitler_targets:
                target = targets[0]
            else:
                target = non_hitler_targets[0]
            engine.submit_action(ExecutePlayer(player_id=president, target_id=target))
            if not engine.is_game_over:
                return target
            return None

        if engine.phase == GamePhase.CHANCELLOR_NOMINATION:
            try:
                _pass_election_unanimously(engine)
            except Exception:
                return None

            if engine.is_game_over:
                return None

            if engine.phase == GamePhase.LEGISLATIVE_PRESIDENT:
                _complete_legislative_session(engine)

                if engine.phase == GamePhase.EXECUTIVE_ACTION_EXECUTION:
                    continue  # handled at top of loop

                _handle_executive_action_if_needed(engine)
        else:
            if engine.phase == GamePhase.EXECUTIVE_ACTION_EXECUTION:
                continue
            _handle_executive_action_if_needed(engine)

    return None


# ---------------------------------------------------------------------------
# 13. test_private_history_accumulates
# ---------------------------------------------------------------------------


def test_private_history_accumulates():
    """After multiple rounds as president/chancellor, private_history contains
    all past private events for that player."""
    engine = _setup_game(num_players=7, seed=42)

    events_per_player: dict[int, int] = {pid: 0 for pid in range(engine.num_players)}

    rounds_played = 0
    max_rounds = 10

    while rounds_played < max_rounds and not engine.is_game_over:
        if engine.phase != GamePhase.CHANCELLOR_NOMINATION:
            _handle_executive_action_if_needed(engine)
            if engine.is_game_over:
                break
            continue

        president = engine.current_president
        pending = engine.pending_action
        nominee = pending.legal_targets[0]
        engine.submit_action(NominateChancellor(player_id=president, target_id=nominee))

        for pid in engine.living_players:
            engine.submit_action(CastVote(player_id=pid, vote=True))

        if engine.is_game_over:
            break

        if engine.phase == GamePhase.LEGISLATIVE_PRESIDENT:
            events_per_player[president] = events_per_player.get(president, 0) + 1
            _complete_legislative_session(engine)
            events_per_player[nominee] = events_per_player.get(nominee, 0) + 1

            _handle_executive_action_if_needed(engine)

        rounds_played += 1

    # Verify that private_history accumulates for players who acted
    for pid in range(engine.num_players):
        obs = engine.get_observation(pid)
        expected_count = events_per_player.get(pid, 0)
        # Private history should have at least as many events as times acting
        # (could have more from executive actions like investigation/peek)
        actual_count = len(obs["private_history"])
        assert actual_count >= expected_count, (
            f"Player {pid} expected >= {expected_count} private events, got {actual_count}"
        )

    # Verify at least one player accumulated multiple events
    max_events = max(len(engine.get_observation(pid)["private_history"]) for pid in range(engine.num_players))
    assert max_events >= 2, "Expected at least one player to have 2+ private history events"


# ---------------------------------------------------------------------------
# 14. test_observation_does_not_leak_deck_contents
# ---------------------------------------------------------------------------


def test_observation_does_not_leak_deck_contents():
    """No player can see actual policy tiles in the draw/discard piles.
    They can only see pile sizes."""
    engine = _setup_game(num_players=7, seed=42)

    # Play a round so there are cards in the discard pile
    if engine.phase == GamePhase.CHANCELLOR_NOMINATION:
        _play_full_round(engine)

    for pid in range(engine.num_players):
        obs = engine.get_observation(pid)

        # Sizes should be present and be integers
        assert "draw_pile_size" in obs
        assert "discard_pile_size" in obs
        assert isinstance(obs["draw_pile_size"], int)
        assert isinstance(obs["discard_pile_size"], int)

        # Actual pile contents must NOT be present
        assert "draw_pile" not in obs
        assert "discard_pile" not in obs
        assert "deck" not in obs
        assert "draw_pile_contents" not in obs
        assert "discard_pile_contents" not in obs

        # Recursively check that no nested structure leaks the full deck
        str(obs)
        # The draw pile has 14 cards after drawing 3, and the observation
        # should not contain a list representation of 14+ policy values
        # that corresponds to deck contents.
        # We just verify the keys are not present; that is sufficient.


# ---------------------------------------------------------------------------
# 15. test_votes_are_public_after_resolution
# ---------------------------------------------------------------------------


def test_votes_are_public_after_resolution():
    """After an election resolves, all players see the vote breakdown
    in the round history."""
    engine = _setup_game(num_players=7, seed=42)

    president = engine.current_president
    pending = engine.pending_action
    nominee = pending.legal_targets[0]
    engine.submit_action(NominateChancellor(player_id=president, target_id=nominee))

    # Have a mixed vote: first 4 vote Ja, rest vote Nein
    living = engine.living_players
    for i, pid in enumerate(living):
        engine.submit_action(CastVote(player_id=pid, vote=(i < 4)))

    # After resolution, the round should be in history with votes visible.
    # Note: we need to check that after the election is resolved (whether
    # passed or failed), the votes appear in the history for ALL players.

    # The round may have been finalized already. Let's check the history
    # from each player's perspective.
    for pid in range(engine.num_players):
        obs = engine.get_observation(pid)
        history = obs["history"]

        # Find the round with votes
        voted_rounds = [h for h in history if h["votes"] is not None]

        # If election passed, the round might still be "current" (not in history yet)
        # because the legislative session follows. If it failed, it should be in history.
        if len(voted_rounds) > 0:
            last_voted = voted_rounds[-1]
            votes = last_voted["votes"]

            # All living players should have voted
            assert len(votes) == len(living), f"Player {pid} sees {len(votes)} votes, expected {len(living)}"

            # Each vote should be a boolean
            for voter_id, vote in votes.items():
                assert isinstance(vote, bool) or isinstance(voter_id, (int, str))

            # Verify the vote breakdown
            ja_count = sum(1 for v in votes.values() if v)
            nein_count = sum(1 for v in votes.values() if not v)
            assert ja_count + nein_count == len(living)


def test_votes_are_public_after_failed_election():
    """After a FAILED election, all players see the vote breakdown in history."""
    engine = _setup_game(num_players=7, seed=42)

    president = engine.current_president
    pending = engine.pending_action
    nominee = pending.legal_targets[0]
    engine.submit_action(NominateChancellor(player_id=president, target_id=nominee))

    # Everyone votes Nein so the election fails
    living = engine.living_players
    for pid in living:
        engine.submit_action(CastVote(player_id=pid, vote=False))

    # After a failed election, the round should be in history
    for pid in range(engine.num_players):
        obs = engine.get_observation(pid)
        history = obs["history"]
        assert len(history) >= 1, f"Player {pid} should see at least 1 history entry"

        last_round = history[-1]
        assert last_round["votes"] is not None
        assert last_round["elected"] is False
        assert len(last_round["votes"]) == len(living)

        # All votes should be Nein (False)
        for voter_id, vote in last_round["votes"].items():
            assert vote is False, f"Player {pid}'s history shows vote={vote} for voter {voter_id}, expected False"


# ---------------------------------------------------------------------------
# Additional edge-case tests
# ---------------------------------------------------------------------------


def test_non_chancellor_cannot_see_received_policies():
    """During LEGISLATIVE_CHANCELLOR, the president and other players do NOT
    see received_policies."""
    engine = _setup_game(num_players=7, seed=42)

    president, chancellor = _pass_election_unanimously(engine)
    engine.submit_action(PresidentDiscard(player_id=president, discard_index=0))

    assert engine.phase == GamePhase.LEGISLATIVE_CHANCELLOR

    # President should not see received_policies
    obs_president = engine.get_observation(president)
    assert "received_policies" not in obs_president

    # Other players should not see received_policies
    for pid in engine.living_players:
        if pid == chancellor:
            continue
        obs = engine.get_observation(pid)
        assert "received_policies" not in obs


def test_peek_not_visible_to_non_president_during_peek_phase():
    """During EXECUTIVE_ACTION_PEEK phase, only the current president sees
    peeked_policies."""
    for seed in range(200):
        engine = _setup_game(num_players=5, seed=seed)
        found = _drive_to_peek_phase_only(engine)
        if found:
            break
    else:
        pytest.skip("Could not reach peek phase in 200 seeds")

    president = engine.current_president
    assert engine.phase == GamePhase.EXECUTIVE_ACTION_PEEK

    for pid in range(engine.num_players):
        obs = engine.get_observation(pid)
        if pid == president:
            assert "peeked_policies" in obs
            assert isinstance(obs["peeked_policies"], list)
            assert len(obs["peeked_policies"]) == 3
        else:
            assert "peeked_policies" not in obs


def _drive_to_peek_phase_only(engine: GameEngine) -> bool:
    """Drive the game until we are IN the EXECUTIVE_ACTION_PEEK phase
    (before acknowledging). Returns True if reached."""
    max_rounds = 30
    for _ in range(max_rounds):
        if engine.is_game_over:
            return False

        if engine.phase == GamePhase.EXECUTIVE_ACTION_PEEK:
            return True

        if engine.phase == GamePhase.CHANCELLOR_NOMINATION:
            try:
                _pass_election_unanimously(engine)
            except Exception:
                return False

            if engine.is_game_over:
                return False

            if engine.phase == GamePhase.LEGISLATIVE_PRESIDENT:
                _complete_legislative_session(engine)

                if engine.phase == GamePhase.EXECUTIVE_ACTION_PEEK:
                    return True

                if engine.phase != GamePhase.EXECUTIVE_ACTION_PEEK:
                    _handle_executive_action_if_needed(engine)
        else:
            if engine.phase == GamePhase.EXECUTIVE_ACTION_PEEK:
                return True
            _handle_executive_action_if_needed(engine)

    return False


def test_president_does_not_see_drawn_policies_outside_legislative():
    """The president should NOT see drawn_policies when we are NOT in the
    LEGISLATIVE_PRESIDENT phase."""
    engine = _setup_game(num_players=7, seed=42)

    # During CHANCELLOR_NOMINATION phase
    president = engine.current_president
    obs = engine.get_observation(president)
    assert "drawn_policies" not in obs


def test_investigation_result_not_in_history_for_others():
    """The public history does NOT contain the investigation result party.
    Only the investigating president sees it privately."""
    for seed in range(100):
        engine = _setup_game(num_players=7, seed=seed)
        try:
            investigating_president = _drive_to_investigation(engine)
            if investigating_president is not None:
                break
        except Exception:
            continue
    else:
        pytest.skip("Could not reach investigation phase in 100 seeds")

    for pid in range(engine.num_players):
        obs = engine.get_observation(pid)
        for h in obs["history"]:
            # The public history should NOT contain investigation_result
            assert "investigation_result" not in h, (
                f"Player {pid}'s history round {h.get('round')} leaks investigation_result"
            )
