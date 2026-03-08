# Secret Hitler Sandbox

Research sandbox for studying deceptive alignment in multi-agent LLM systems.

## Quick Reference

- **Stack**: Python >=3.13, uv, FastAPI, MCP SDK, OpenRouter
- **External dep**: [`agents`](https://github.com/Antonio-Tresol/agents) — custom agent framework
- **Tests**: `uv run pytest tests/ -v -k "not e2e"` (415+)
- **Server**: `uv run uvicorn server.app:app --port 8000`
- **Run game**: `uv run python -m orchestration --model "openrouter:openai/gpt-5-mini" --players 5`
- **Lint/format**: `uvx ruff check --fix` / `uvx ruff format`

## Conventions

- Always `uv run`, never bare `python`.
- Trailing commas enforced (COM812). Line length 120.
- Frozen dataclasses with `to_dict()` over raw dicts.
- Engine is deterministic — all RNG through `random.Random(seed)`.
- `.env` with `OPENROUTER_API_KEY` (gitignored).

## Directory Guide

| Directory | Docs | Purpose |
|-----------|------|---------|
| `game/` | [`GAME.md`](game/GAME.md) | Pure-Python game engine (state machine) |
| `server/` | [`SERVER.md`](server/SERVER.md) | FastAPI REST + MCP streamable-http |
| `orchestration/` | [`ORCHESTRATION.md`](orchestration/ORCHESTRATION.md) | Turn loop, backends, session management |
| `prompts/` | [`PROMPTS.md`](prompts/PROMPTS.md) | Markdown system prompts (base + per-role) |
| `tests/` | [`TESTS.md`](tests/TESTS.md) | Unit, integration, E2E tests |
| `docs/` | — | Analysis guide + game reports |
| `examples/` | — | YAML config examples |

Full project overview: [`README.md`](README.md)
