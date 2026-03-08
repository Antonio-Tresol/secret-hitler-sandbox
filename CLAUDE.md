# Secret Hitler Sandbox

Research sandbox for studying deceptive alignment in multi-agent LLM systems.
LLM agents play Secret Hitler against each other through tool use (MCP), while
a deterministic game engine enforces rules and records everything for analysis.

## Stack

- Python >=3.11, uv, pytest
- FastAPI + uvicorn (game server)
- MCP SDK (streamable-http, `"type": "http"`)
- `agents` package (external: https://github.com/Antonio-Tresol/agents) for OpenRouter backend
- OpenRouter API for multi-model agent backends

## Architecture (three layers)

1. **Game engine** (`game/`) — Pure-Python state machine, seeded RNG, no external deps. See [`game/GAME.md`](game/GAME.md).
2. **Server** (`server/`) — FastAPI REST + MCP streamable-http. Per-player auth tokens. See [`server/SERVER.md`](server/SERVER.md).
3. **Orchestration** (`orchestration/`) — Turn-driven game loop, backend abstraction, session management. See [`orchestration/ORCHESTRATION.md`](orchestration/ORCHESTRATION.md).

Supporting directories:
- **Prompts** (`prompts/`) — Markdown system prompts (base rules + per-role). See [`prompts/PROMPTS.md`](prompts/PROMPTS.md).
- **Tests** (`tests/`) — 415+ unit/integration tests + E2E. See [`tests/TESTS.md`](tests/TESTS.md).

## Commands

```bash
uv sync                                          # install deps
uv run pytest tests/ -v -k "not e2e"             # unit/integration tests (415+)
uv run uvicorn server.app:app --port 8000         # start server
uv run python -m orchestration --bot-mode         # test with random bots
uv run python -m orchestration \                  # real game
  --model "openrouter:openai/gpt-5-mini" --players 5 --seed 42
```

## Conventions

- Always use `uv run` for Python commands, never bare `python`.
- Ruff for linting and formatting (`uvx ruff check`, `uvx ruff format`).
- Trailing commas enforced (COM812). Line length 120. Import sorting via isort.
- Prefer frozen dataclasses with `to_dict()` over raw dicts for structured data.
- Engine is deterministic — all RNG through `random.Random(seed)`.
- Skins are presentation-layer only; engine never references them.
- `pending_action` property drives the turn loop (who must act + what's legal).
- MCP transport: streamable-http with `"type": "http"` in Claude Code config.
- `.env` file with `OPENROUTER_API_KEY` loaded via `python-dotenv` in orchestrator.
