"""Term limit logic including the 5-player exception."""

from __future__ import annotations


def get_ineligible_for_chancellor(
    last_elected_president: int | None,
    last_elected_chancellor: int | None,
    living_player_count: int,
    candidate_president: int,
) -> set[int]:
    """
    Return the set of player_ids ineligible for chancellor nomination.

    Always ineligible:
    - The current presidential candidate (can't be both president and chancellor)

    Term limits:
    - last_elected_chancellor is always ineligible (if not None)
    - last_elected_president is ineligible UNLESS living_player_count <= 5
      (5-player exception: only the chancellor is term-limited)

    After chaos, the caller should pass None for both last_elected_* to indicate
    that term limits have been reset.
    """
    ineligible: set[int] = {candidate_president}

    if last_elected_chancellor is not None:
        ineligible.add(last_elected_chancellor)

    if last_elected_president is not None and living_player_count > 5:
        ineligible.add(last_elected_president)

    return ineligible
