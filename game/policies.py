"""Policy deck management: 11 Fascist + 6 Liberal tiles."""

from __future__ import annotations

import random as _random

from game.types import PolicyType


class PolicyDeck:
    """
    Manages the draw pile and discard pile.

    The deck starts with 11 Fascist + 6 Liberal tiles, shuffled.
    When the draw pile has fewer than 3 tiles (checked after legislative sessions
    and chaos top-decks), the discard pile is shuffled back into the draw pile.
    """

    def __init__(self, rng: _random.Random) -> None:
        self._rng = rng
        self._draw_pile: list[PolicyType] = [PolicyType.FASCIST] * 11 + [PolicyType.LIBERAL] * 6
        self._discard_pile: list[PolicyType] = []
        self._rng.shuffle(self._draw_pile)

    @property
    def draw_size(self) -> int:
        return len(self._draw_pile)

    @property
    def discard_size(self) -> int:
        return len(self._discard_pile)

    def draw(self, n: int = 3) -> list[PolicyType]:
        """Draw n tiles from the top of the draw pile."""
        if len(self._draw_pile) < n:
            raise RuntimeError(
                f"Cannot draw {n} tiles: only {len(self._draw_pile)} remain. Call reshuffle_if_needed() first.",
            )
        drawn = self._draw_pile[:n]
        self._draw_pile = self._draw_pile[n:]
        return drawn

    def discard(self, *policies: PolicyType) -> None:
        """Add policies to the discard pile."""
        self._discard_pile.extend(policies)

    def peek(self, n: int = 3) -> list[PolicyType]:
        """Look at the top n tiles without removing them."""
        if len(self._draw_pile) < n:
            raise RuntimeError(f"Cannot peek {n} tiles: only {len(self._draw_pile)} remain.")
        return list(self._draw_pile[:n])

    def reshuffle_if_needed(self) -> bool:
        """
        If fewer than 3 tiles remain in draw pile, shuffle discard into draw.

        Returns True if a reshuffle occurred.
        """
        if len(self._draw_pile) < 3:
            self._draw_pile.extend(self._discard_pile)
            self._discard_pile.clear()
            self._rng.shuffle(self._draw_pile)
            return True
        return False
