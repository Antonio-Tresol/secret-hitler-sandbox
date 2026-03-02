"""Comprehensive tests for the PolicyDeck class."""

import random

import pytest

from game.policies import PolicyDeck
from game.types import PolicyType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TOTAL_FASCIST = 11
TOTAL_LIBERAL = 6
TOTAL_TILES = TOTAL_FASCIST + TOTAL_LIBERAL  # 17


def _make_deck(seed: int = 42) -> PolicyDeck:
    """Create a PolicyDeck with a deterministic RNG."""
    return PolicyDeck(rng=random.Random(seed))


# ---------------------------------------------------------------------------
# 1. test_initial_deck_composition
# ---------------------------------------------------------------------------


def test_initial_deck_composition():
    """The deck starts with 11 Fascist + 6 Liberal = 17 tiles, all in draw pile."""
    deck = _make_deck()

    assert deck.draw_size == TOTAL_TILES
    assert deck.discard_size == 0

    # Draw every tile and verify exact composition.
    all_tiles = deck.draw(TOTAL_TILES)
    fascist_count = sum(1 for t in all_tiles if t is PolicyType.FASCIST)
    liberal_count = sum(1 for t in all_tiles if t is PolicyType.LIBERAL)

    assert fascist_count == TOTAL_FASCIST
    assert liberal_count == TOTAL_LIBERAL


# ---------------------------------------------------------------------------
# 2. test_draw_removes_from_top
# ---------------------------------------------------------------------------


def test_draw_removes_from_top():
    """Drawing 3 tiles reduces draw_size by 3."""
    deck = _make_deck()

    initial_size = deck.draw_size
    drawn = deck.draw(3)

    assert len(drawn) == 3
    assert deck.draw_size == initial_size - 3


def test_draw_removes_correct_amount_various_n():
    """Drawing n tiles reduces draw_size by exactly n for several values of n."""
    for n in (1, 2, 3, 5):
        deck = _make_deck()
        before = deck.draw_size
        drawn = deck.draw(n)
        assert len(drawn) == n
        assert deck.draw_size == before - n


# ---------------------------------------------------------------------------
# 3. test_discard_adds_to_discard_pile
# ---------------------------------------------------------------------------


def test_discard_adds_to_discard_pile():
    """Discarding tiles increases discard_size by the number discarded."""
    deck = _make_deck()

    assert deck.discard_size == 0

    deck.discard(PolicyType.FASCIST)
    assert deck.discard_size == 1

    deck.discard(PolicyType.LIBERAL, PolicyType.FASCIST)
    assert deck.discard_size == 3


def test_discard_after_draw():
    """Draw 3, discard 2 -- verify sizes are consistent."""
    deck = _make_deck()

    drawn = deck.draw(3)
    assert deck.draw_size == TOTAL_TILES - 3

    deck.discard(drawn[0], drawn[1])
    assert deck.discard_size == 2
    assert deck.draw_size == TOTAL_TILES - 3  # draw pile unchanged by discard


# ---------------------------------------------------------------------------
# 4. test_reshuffle_when_below_3
# ---------------------------------------------------------------------------


def test_reshuffle_when_below_3():
    """When draw pile < 3, reshuffle merges discard back and all tiles are accounted for."""
    deck = _make_deck(seed=99)

    enacted: list[PolicyType] = []

    # Simulate legislative sessions: draw 3, enact 1, discard 2 until < 3 remain.
    while deck.draw_size >= 3:
        hand = deck.draw(3)
        enacted.append(hand[0])       # "enact" the first tile
        deck.discard(hand[1], hand[2])  # discard the other two

    assert deck.draw_size < 3  # precondition for reshuffle

    pre_reshuffle_draw = deck.draw_size
    pre_reshuffle_discard = deck.discard_size

    reshuffled = deck.reshuffle_if_needed()
    assert reshuffled is True

    # After reshuffle, discard should be empty and draw should contain all
    # non-enacted tiles.
    assert deck.discard_size == 0
    assert deck.draw_size == pre_reshuffle_draw + pre_reshuffle_discard
    assert deck.draw_size == TOTAL_TILES - len(enacted)


def test_reshuffle_not_needed_when_enough():
    """reshuffle_if_needed returns False when draw pile >= 3."""
    deck = _make_deck()
    assert deck.reshuffle_if_needed() is False
    assert deck.draw_size == TOTAL_TILES  # nothing changed


# ---------------------------------------------------------------------------
# 5. test_reshuffle_preserves_total_tiles
# ---------------------------------------------------------------------------


def test_reshuffle_preserves_total_tiles():
    """After multiple draw/discard/reshuffle cycles, total = 17 minus enacted."""
    deck = _make_deck(seed=7)

    enacted: list[PolicyType] = []

    for _ in range(8):  # 8 legislative sessions
        deck.reshuffle_if_needed()
        hand = deck.draw(3)
        enacted.append(hand[0])
        deck.discard(hand[1], hand[2])

    # Total tiles across all locations must equal 17.
    total_accounted = deck.draw_size + deck.discard_size + len(enacted)
    assert total_accounted == TOTAL_TILES

    # Force all tiles back into draw pile so we can inspect composition.
    # First discard everything in draw pile, then reshuffle to merge.
    leftover_draw = deck.draw(deck.draw_size) if deck.draw_size > 0 else []
    deck.discard(*leftover_draw)
    # Now all non-enacted tiles are in the discard pile; force reshuffle by
    # confirming draw_size < 3 and calling reshuffle_if_needed.
    assert deck.draw_size < 3  # must be 0
    deck.reshuffle_if_needed()
    remaining = deck.draw(deck.draw_size)

    all_tiles = remaining + enacted
    assert sum(1 for t in all_tiles if t is PolicyType.FASCIST) == TOTAL_FASCIST
    assert sum(1 for t in all_tiles if t is PolicyType.LIBERAL) == TOTAL_LIBERAL


# ---------------------------------------------------------------------------
# 6. test_peek_does_not_modify_deck
# ---------------------------------------------------------------------------


def test_peek_does_not_modify_deck():
    """Peeking at the top 3 tiles does not remove them; drawing returns same tiles."""
    deck = _make_deck(seed=123)

    peeked = deck.peek(3)
    assert len(peeked) == 3
    assert deck.draw_size == TOTAL_TILES  # unchanged

    drawn = deck.draw(3)
    assert drawn == peeked  # same tiles, same order


def test_peek_returns_copy():
    """The list returned by peek is a copy -- mutating it doesn't affect the deck."""
    deck = _make_deck()

    peeked = deck.peek(3)
    peeked.clear()

    assert deck.draw_size == TOTAL_TILES
    assert len(deck.peek(3)) == 3


# ---------------------------------------------------------------------------
# 7. test_draw_empty_raises
# ---------------------------------------------------------------------------


def test_draw_empty_raises():
    """Drawing more tiles than available raises RuntimeError."""
    deck = _make_deck()

    # Draw all 17 tiles first.
    deck.draw(TOTAL_TILES)
    assert deck.draw_size == 0

    with pytest.raises(RuntimeError, match="Cannot draw"):
        deck.draw(1)


def test_draw_insufficient_raises():
    """Drawing n when fewer than n remain raises RuntimeError."""
    deck = _make_deck()

    deck.draw(TOTAL_TILES - 2)  # leave exactly 2
    assert deck.draw_size == 2

    with pytest.raises(RuntimeError, match="Cannot draw"):
        deck.draw(3)


def test_peek_insufficient_raises():
    """Peeking more tiles than available raises RuntimeError."""
    deck = _make_deck()
    deck.draw(TOTAL_TILES)

    with pytest.raises(RuntimeError, match="Cannot peek"):
        deck.peek(1)


# ---------------------------------------------------------------------------
# 8. test_deterministic_shuffle_with_seed
# ---------------------------------------------------------------------------


def test_deterministic_shuffle_with_seed():
    """Two decks created with the same seed produce the same tile order."""
    deck_a = _make_deck(seed=2025)
    deck_b = _make_deck(seed=2025)

    tiles_a = deck_a.draw(TOTAL_TILES)
    tiles_b = deck_b.draw(TOTAL_TILES)

    assert tiles_a == tiles_b


def test_different_seeds_produce_different_order():
    """Two decks created with different seeds (very likely) produce different orders."""
    deck_a = _make_deck(seed=1)
    deck_b = _make_deck(seed=2)

    tiles_a = deck_a.draw(TOTAL_TILES)
    tiles_b = deck_b.draw(TOTAL_TILES)

    # It is astronomically unlikely for two different seeds to produce the
    # same permutation of 17 tiles, so we assert inequality.
    assert tiles_a != tiles_b


def test_deterministic_reshuffle_with_seed():
    """After a reshuffle, a deck with the same seed and same operations produces
    the same order again."""
    def _simulate(seed: int) -> list[PolicyType]:
        deck = PolicyDeck(rng=random.Random(seed))
        # Draw and discard to trigger a reshuffle.
        for _ in range(5):
            hand = deck.draw(3)
            deck.discard(hand[1], hand[2])
        deck.reshuffle_if_needed()
        return deck.draw(deck.draw_size)

    result_a = _simulate(seed=555)
    result_b = _simulate(seed=555)
    assert result_a == result_b
