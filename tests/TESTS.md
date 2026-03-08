# Test Suite

416 tests total (415 non-e2e). Run with:

```bash
uv run pytest tests/ -v -k "not e2e"
```

## Game Engine (215 tests)

| File | Tests | Covers |
|------|------:|--------|
| `test_deck.py` | 16 | PolicyDeck: composition, draw/discard, shuffle, peek, edge cases |
| `test_engine.py` | 28 | GameEngine integration: setup, nominations, voting, legislation, chaos, win conditions |
| `test_info_hiding.py` | 20 | `get_observation()` enforces per-player information hiding (role knowledge, hands, executive results) |
| `test_powers.py` | 34 | Executive power tracks and engine integration (investigate, peek, special election, execution) |
| `test_term_limits.py` | 15 | Chancellor eligibility rules: term limits, 5-player exception, chaos resets, executions |
| `test_veto.py` | 28 | Veto power mechanics: unlock at 5 fascist policies, propose/accept/reject flows |
| `test_skins.py` | 74 | Narrative skins (SecretHitler, CorporateBoard): enum coverage, observation translation, registry |

## Server (55 tests)

| File | Tests | Covers |
|------|------:|--------|
| `test_game_session.py` | 24 | GameSession wrapper: skins, discussion windows, JSONL logging, auth, multi-session |
| `test_server.py` | 20 | FastAPI REST routes: lobby CRUD, game status, action submission, auth, error handling |
| `test_mcp_tools.py` | 11 | MCP tool handlers: get_game_status, submit_action, send_message (unit tests, no transport) |

## Orchestration & Agent Core (146 tests)

| File | Tests | Covers |
|------|------:|--------|
| `test_orchestrator.py` | 65 | Orchestrator lifecycle, RandomBot, backends (ClaudeCode/OpenCode sessions), config loading, MCP config builder |
| `test_agent_core.py` | 80 | Agent core scaffold: types (frozen dataclasses), OpenRouter provider, MCP/local tools, middleware (transcript, compactor), ReAct loop, stores |

## End-to-End (1 test, skipped by default)

| File | Tests | Covers |
|------|------:|--------|
| `test_e2e_claude.py` | 1 | Full game with real Claude Code agents; requires CLI auth and API access |

Run e2e separately: `uv run pytest tests/test_e2e_claude.py -v -m e2e --timeout=600`

## Shared Fixtures (`conftest.py`)

- `engine_5p` / `engine_7p` -- seeded GameEngine instances (5 and 7 players)
- `session_5p` -- GameSession with temp log directory
- `_clean_sessions` (autouse) -- clears in-memory session store between tests
