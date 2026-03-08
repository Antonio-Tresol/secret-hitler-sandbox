"""Executive power tracks for different player counts."""

from __future__ import annotations

from game.types import ExecutivePower

# Power track: maps fascist_policy_count (1-indexed) to power.
# The 5th fascist policy always unlocks veto as a side effect (handled in engine).
# The 6th fascist policy is always a fascist victory (handled in engine).
POWER_TRACKS: dict[str, dict[int, ExecutivePower]] = {
    "small": {
        1: ExecutivePower.NONE,
        2: ExecutivePower.NONE,
        3: ExecutivePower.PEEK,
        4: ExecutivePower.EXECUTION,
        5: ExecutivePower.EXECUTION,
    },
    "medium": {
        1: ExecutivePower.NONE,
        2: ExecutivePower.INVESTIGATE,
        3: ExecutivePower.SPECIAL_ELECTION,
        4: ExecutivePower.EXECUTION,
        5: ExecutivePower.EXECUTION,
    },
    "large": {
        1: ExecutivePower.INVESTIGATE,
        2: ExecutivePower.INVESTIGATE,
        3: ExecutivePower.SPECIAL_ELECTION,
        4: ExecutivePower.EXECUTION,
        5: ExecutivePower.EXECUTION,
    },
}


def get_track_key(num_players: int) -> str:
    """Return 'small', 'medium', or 'large' based on player count."""
    if num_players <= 6:
        return "small"
    elif num_players <= 8:
        return "medium"
    else:
        return "large"


def get_executive_power(num_players: int, fascist_policy_count: int) -> ExecutivePower:
    """
    Return the executive power triggered by the Nth fascist policy.

    Returns ExecutivePower.NONE if fascist_policy_count is 0 or 6+.
    """
    if fascist_policy_count <= 0 or fascist_policy_count > 5:
        return ExecutivePower.NONE

    track_key = get_track_key(num_players)
    return POWER_TRACKS[track_key][fascist_policy_count]
