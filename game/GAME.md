# game/ -- Deterministic Secret Hitler Engine

Pure-Python state machine implementing the Secret Hitler board game.
No external dependencies. Designed to be driven by an external caller
(server, test harness, or bot loop) via `submit_action` / `pending_action`.

## Files

| File | Purpose |
|---|---|
| `types.py` | All enums (`Role`, `Party`, `PolicyType`, `GamePhase`, `ExecutivePower`, `WinCondition`), frozen action dataclasses (`NominateChancellor`, `CastVote`, `PresidentDiscard`, `ChancellorEnact`, `VetoResponse`, `InvestigatePlayer`, `PolicyPeekAck`, `SpecialElection`, `ExecutePlayer`), `PendingAction`, `RoundRecord`, observation structs (`PlayerInfo`, `RoundSummary`, `PrivateEvent`, etc.), exceptions, and game constants. |
| `engine.py` | `GameEngine` class. Manages the full game lifecycle: setup, nomination, voting, legislative session, veto, executive actions, chaos, win detection. Single entry point: `submit_action(action)`. |
| `roles.py` | Role distribution table (5-10 players) and `get_knowledge()` implementing information asymmetry (liberals know nothing; fascists see each other; Hitler is blind in 7+ games). |
| `policies.py` | `PolicyDeck` -- draw/discard/peek/reshuffle over 11 fascist + 6 liberal tiles. |
| `powers.py` | Executive power tracks (small/medium/large) mapping fascist policy count to presidential powers. |
| `terms.py` | `get_ineligible_for_chancellor()` -- term limit logic with the 5-player exception. |
| `skins/` | Presentation-layer narrative wrappers. `BaseSkin` (ABC) defines the translation interface; `SecretHitlerSkin` and `CorporateBoardSkin` provide two framings for ablation experiments. `SKIN_REGISTRY` in `__init__.py` is the single lookup table. |

## Key Design Decisions

- **Deterministic.** All randomness flows through a seeded `random.Random(seed)` instance. Same seed = identical game.
- **Frozen action dataclasses.** Every player action is a frozen dataclass with a `player_id` field. The `Action` union type covers all nine action types.
- **`pending_action` pattern.** The engine exposes a `pending_action` property that returns who must act, what action type is expected, and what targets are legal. Callers never guess the game phase.
- **Information hiding.** `get_observation(player_id)` returns only what that player is allowed to see -- role knowledge, legislative hands, investigation results, and private event history.
- **Transient resolution.** Some transitions (e.g., chaos top-deck after third failed election) resolve immediately inside `submit_action`, so the caller never sees intermediate states.
- **Skins are presentation only.** The engine never references skins. Skins translate engine observations into narrative strings via `translate_observation()`.

## Supported Player Counts

5-10 players. Role distribution, executive power tracks, and term limit rules all scale with player count.

## Win Conditions

- **Liberal:** enact 5 liberal policies, or execute Hitler.
- **Fascist:** enact 6 fascist policies, or elect Hitler as chancellor after 3+ fascist policies.
