"""Token-based authentication for mapping API callers to player IDs."""

from __future__ import annotations

import secrets


def generate_player_tokens(num_players: int) -> dict[str, int]:
    """Return a mapping of {token: player_id} for *num_players* players.

    Each token is a 16-byte URL-safe string generated via ``secrets``.
    """
    return {secrets.token_urlsafe(16): pid for pid in range(num_players)}
