"""Role assignment and knowledge rules by player count."""

from __future__ import annotations

import random as _random

from game.types import Party, PlayerState, Role

# Maps player_count -> (num_liberals, num_fascists). Hitler is always +1.
ROLE_DISTRIBUTION: dict[int, tuple[int, int]] = {
    5: (3, 1),
    6: (4, 1),
    7: (4, 2),
    8: (5, 2),
    9: (5, 3),
    10: (6, 3),
}


def assign_roles(num_players: int, rng: _random.Random) -> list[PlayerState]:
    """
    Assign roles to players.

    Returns a list of PlayerState objects with player_ids 0..num_players-1.
    The order is the seating order (used for presidential rotation).
    """
    if num_players not in ROLE_DISTRIBUTION:
        raise ValueError(f"Player count must be 5-10, got {num_players}")

    num_liberals, num_fascists = ROLE_DISTRIBUTION[num_players]

    roles: list[tuple[Role, Party]] = []
    roles.extend((Role.LIBERAL, Party.LIBERAL) for _ in range(num_liberals))
    roles.extend((Role.FASCIST, Party.FASCIST) for _ in range(num_fascists))
    roles.append((Role.HITLER, Party.FASCIST))

    rng.shuffle(roles)

    return [
        PlayerState(player_id=i, role=role, party=party)
        for i, (role, party) in enumerate(roles)
    ]


def get_knowledge(
    player_id: int, players: list[PlayerState], num_players: int
) -> dict:
    """
    Return what a player knows about others at game start.

    Returns:
        {
            "known_fascists": list[int],  # player_ids of known fascists (not including self)
            "known_hitler": int | None,   # player_id of hitler (if known)
        }

    Knowledge rules:
    - Liberals: know nothing beyond own role.
    - Fascists (non-Hitler): always see other fascists and Hitler.
    - Hitler in 5-6 player games: sees all fascists.
    - Hitler in 7+ player games: sees nothing (only knows own role).
    """
    player = players[player_id]

    if player.role == Role.LIBERAL:
        return {"known_fascists": [], "known_hitler": None}

    if player.role == Role.FASCIST:
        # Fascists see all other fascists + Hitler
        known_fascists = [
            p.player_id
            for p in players
            if p.player_id != player_id and p.party == Party.FASCIST and p.role != Role.HITLER
        ]
        known_hitler = next(p.player_id for p in players if p.role == Role.HITLER)
        return {"known_fascists": known_fascists, "known_hitler": known_hitler}

    # Hitler
    if num_players <= 6:
        # Hitler sees fascists in small games
        known_fascists = [
            p.player_id
            for p in players
            if p.player_id != player_id and p.role == Role.FASCIST
        ]
        return {"known_fascists": known_fascists, "known_hitler": None}
    else:
        # Hitler is blind in 7+ player games
        return {"known_fascists": [], "known_hitler": None}
