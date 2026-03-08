# orchestration/

Game lifecycle management: lobby creation, player session setup, and turn-driven agent invocation.

## Files

- **`orchestrator.py`** -- `GameOrchestrator` drives the full game loop. Detects whose turn it is via `pending_action`, builds context-rich prompts, and invokes only the relevant player(s). Includes `RandomBot` for testing (`--bot-mode`), a YAML config loader, and a status dashboard that reads `events.jsonl`.
- **`backends.py`** -- Backend abstraction layer. Defines `BasePlayerSession` (ABC) with three implementations: `ClaudeCodeSession` (spawns `claude` CLI with `--resume` for session continuity), `OpenCodeSession` (spawns `opencode` CLI), and `AgentSession` (in-process ReAct agent via OpenRouter). Also contains shared utilities: `build_system_prompt()`, `build_mcp_config()`, `parse_model_spec()`, and the `create_session()` factory.
- **`claude_code_launcher.py`** -- Backward-compatible re-exports (`build_mcp_config`, `build_system_prompt`, `PlayerSession`, `InvocationResult`). All implementation now lives in `backends.py`.
- **`__main__.py`** -- Entry point for `uv run python -m orchestration`.
- **`__init__.py`** -- Empty package marker.

## Key design decisions

- **Turn-driven invocation.** The orchestrator polls the server for `pending_action`, then invokes only the player(s) who must act. Agents are not long-lived pollers.
- **Session resumption.** Claude Code uses `--resume <session_id>` to preserve full conversation history across turns. OpenCode uses `--session`. AgentSession keeps the `Agent` object (and its `_messages` list) alive in-process.
- **Parallel voting and discussion.** `CastVote` and discussion rounds invoke all relevant players concurrently via `ThreadPoolExecutor`.
- **Backend prefix convention.** Model specs use `backend:model` syntax (`claudecode:claude-sonnet-4-6`, `opencode:openai/gpt-4-turbo`, `openrouter:anthropic/claude-sonnet-4-6`). No prefix defaults to `claudecode`.
- **AgentSession for OpenRouter.** Uses the external `agents` package (https://github.com/Antonio-Tresol/agents) which provides `Agent`, `OpenRouter`, `McpTools`, `LocalTools`, `Transcript`, `Compactor`, and `DiskStore`. Model metadata (context length, max tokens) is fetched at startup to configure compaction thresholds.
- **Retry and skip logic.** Failed actions retry up to 3 times; after 5 consecutive skip cycles for the same pending action, the game aborts to prevent infinite loops.

## Prompts

System prompts live at project root `prompts/` (not inside this package): `base_rules.md`, `liberal.md`, `fascist.md`, `hitler.md`. They are loaded and templated by `build_system_prompt()` in `backends.py`.

## CLI usage

```bash
uv run python -m orchestration --bot-mode --players 5 --seed 42
uv run python -m orchestration --model "openrouter:openai/gpt-5-mini" --players 5
uv run python -m orchestration --config examples/game_config.yaml
uv run python -m orchestration --status          # dashboard for latest game
uv run python -m orchestration --status GAME_ID  # dashboard for specific game
```
