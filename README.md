# Secret Hitler Sandbox

A research sandbox for studying deceptive capabilities in LLM-based
multi-agent systems using the social deduction game Secret Hitler. LLM
agents play the full game against each other through tool use (MCP),
while a deterministic game engine enforces rules and records everything
for later analysis.

Inspired by the "Among Us" multi-agent deception paper
([code](https://github.com/7vik/AmongUs),
[paper](https://arxiv.org/pdf/2504.04072)).


## Why?

Model safety evaluations need to characterise what capabilities frontier
models possess, including deceptive ones. Understanding what models *can*
do is a precondition for managing the risks of what they *might* do.
Secret Hitler isolates several capabilities that matter for safety
evaluations: sustaining a false identity over multiple rounds of social
interaction, coordinating deceptively with allies without explicit
signalling, and detecting deception from behavioural cues alone. The
game's structure makes these measurable in a controlled setting.

Specifically, this sandbox lets us ask: How reliably can LLM agents
maintain deception under social pressure? Can fascist-role agents
coordinate an implicit strategy without revealing themselves? How
effectively can liberal-role agents identify deceptive behaviour? And
how do these capabilities scale across different frontier models?


## Architecture

The project has three layers:

1. **Game engine** -- A pure-Python state machine that implements Secret
   Hitler. All randomness goes through a seeded RNG, so games are
   reproducible.

2. **Server** -- A FastAPI server that exposes the engine over REST and
   MCP (streamable-http). Agents connect to the MCP endpoint; humans or
   scripts can use REST.

3. **Orchestrator** -- Launches agent instances as players, invokes them
   turn by turn, and collects transcripts. Three backends are supported:
   Claude Code CLI, OpenCode CLI, and OpenRouter (custom ReAct agent
   core). Each agent gets a system prompt with the game rules and its
   secret role, plus an MCP config pointing at the server. The
   orchestrator uses session resumption to preserve each agent's full
   conversation history across turns without burning context on idle
   polling.

There are also two narrative "skins" (Secret Hitler and Corporate Board)
that re-theme the game terminology without changing mechanics. This is
for studying whether framing affects agent behaviour.


## How it works

The game engine is a pure state machine. It accepts action objects
(`NominateChancellor`, `CastVote`, `PresidentDiscard`, etc.) and returns
result dicts. It enforces all rules: term limits, veto power, executive
powers, chaos from the election tracker, and both win conditions. The
`pending_action` property always tells you exactly who must act next and
what actions are legal.

The server wraps the engine with authentication (per-player bearer
tokens), discussion windows (pre-vote and post-legislative), and an MCP
endpoint. Agents connect to the MCP endpoint and interact through five
tools: `get_game_status`, `get_observation`, `submit_action`, `speak`,
and `get_discussion`.

The orchestrator drives the game turn by turn. It polls `get_game_status`
to see who must act, builds a context-rich prompt ("You are President,
nominate a Chancellor from [1, 3, 4]"), and invokes the relevant
player's agent session with `--resume` to preserve conversation history.
For voting and discussion, all relevant players are invoked in parallel.
After each invocation the agent process exits, so there are no
long-lived subprocesses burning context while idle.

Each agent session uses a session ID on its first invocation and resumes
on all subsequent ones. This means the agent remembers everything from
previous turns (past observations, its own reasoning, discussion
messages, who it suspects) without needing to re-read the full game
history each time.


## Getting started

### Requirements

- Python >= 3.11
- [uv](https://docs.astral.sh/uv/)
- An [OpenRouter](https://openrouter.ai/) API key (set `OPENROUTER_API_KEY`
  in `.env`) — gives access to 200+ models with no extra tooling
- **Optional** CLI agents for their respective backends:
  - [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
    (`claudecode:` backend)
  - [OpenCode](https://opencode.ai) (`opencode:` backend)

Install dependencies:

```
uv sync
```

### Running the tests

Unit and integration tests (no API calls, no agent CLI needed):

```
uv run pytest tests/ -v -k "not e2e"
```

There are currently 415+ tests covering the engine, server, MCP tools,
orchestrator, agent core, session management, and prompt generation.

The E2E test runs a real game with Claude Code agents and will consume
API tokens:

```
uv run pytest tests/test_e2e_claude.py -v -m e2e
```


## Running a game

Start the server in one terminal:

```
uv run uvicorn server.app:app --host 127.0.0.1 --port 8000
```

### Bot mode (no tokens)

Random-action bots for testing the full pipeline:

```
uv run python -m orchestration --bot-mode --players 5 --seed 42
```

### Single model

All players use the same model. Plain model names default to the Claude
Code backend:

```
uv run python -m orchestration --players 5 --seed 42 --model claude-sonnet-4-6
```

### Mixed models via config file

A YAML config lets you assign a different backend and model to each
player. The `backend:model` prefix selects the CLI:

```yaml
# examples/game_mixed_e2e.yaml
players: 5
seed: 42
skin: secret_hitler
discussion_rounds: 1
models:
  - claudecode:claude-haiku-4-5-20251001
  - opencode:github-copilot/gpt-5-mini
  - openrouter:google/gemini-2.0-flash
  - opencode:github-copilot/gemini-3-flash-preview
  - claudecode:claude-haiku-4-5-20251001
```

Run it with:

```
uv run python -m orchestration --config examples/game_mixed_e2e.yaml
```

CLI arguments override config file values when both are provided. See
`examples/game_config.yaml` for a fully commented example.

### CLI flags

```
--players N               Number of players (5-10, default 5)
--seed N                  Random seed for reproducibility
--skin NAME               "secret_hitler" or "corporate_board"
--model SPEC              Default model for all players (backend:model)
--models SPEC,SPEC,...    Per-player models, comma-separated
--config PATH             YAML config file
--bot-mode                Use random bots instead of LLM agents
--discussion-rounds N     Discussion rounds per window (default 2)
--discussion-timeout SECS Timeout per discussion turn (default 60)
--max-turns-action N      Max tool-use rounds per action (default 10)
--max-turns-discussion N  Max tool-use rounds per discussion (default 5)
--server-url URL          Game server URL (default http://127.0.0.1:8000)
```

### Backends

Model specs use a `backend:model` prefix to select the agent CLI:

- `claudecode:claude-sonnet-4-6` -- Claude Code CLI
- `opencode:openai/gpt-4-turbo` -- OpenCode CLI
- `opencode:github-copilot/gpt-5-mini` -- OpenCode via GitHub Copilot
- `opencode:openrouter/meta-llama/llama-4-maverick` -- OpenCode via OpenRouter
- `openrouter:anthropic/claude-sonnet-4-6` -- [Agent](https://github.com/Antonio-Tresol/agents) via OpenRouter
- `openrouter:google/gemini-2.0-flash` -- [Agent](https://github.com/Antonio-Tresol/agents) via OpenRouter

Plain model names without a prefix (e.g. `claude-sonnet-4-6`) default
to `claudecode:` for backward compatibility.


## Reading the logs

Every game creates a directory under `logs/games/<game_id>/` containing:

```
metadata.json                  Game setup (players, skin, seed)
status.json                    Live status snapshot (board, round, phase)
events.jsonl                   All actions, observations, discussions,
                               and the final result (one JSON per line)
player_N_transcript.jsonl      Claude Code stream-json output (all turns)
player_N_output.txt            OpenCode plain-text stdout (all turns)
configs/player_N_mcp.json      MCP config (Claude Code players)
configs/player_N_opencode.json OpenCode config (OpenCode players)
configs/player_N_system_prompt.md  Full system prompt (rules + role)
```

Which transcript files have content depends on the backend. Claude Code
players populate `transcript.jsonl` (structured, includes thinking
blocks). OpenCode players populate `output.txt` (plain text).

Quick game summary:

```bash
GAME=<game_id>
cat logs/games/$GAME/events.jsonl | python -c "
import json, sys
for line in sys.stdin:
    e = json.loads(line)
    if e['type'] == 'action':
        r = e.get('result', {})
        print(f'P{e[\"player_id\"]} {e[\"action_type\"]:20s} -> {r.get(\"event\",\"\")}')
    elif e['type'] == 'game_result':
        print(f'RESULT: {e[\"data\"][\"winner\"]} ({e[\"data\"][\"condition\"]}), round {e[\"data\"][\"final_round\"]}')
"
```

See `docs/analysis-guide.md` for detailed log analysis instructions,
one-liners, and the agent-team analysis process for producing full game
reports.


## Skins

Skins remap the game's terminology without touching mechanics. The
engine never references skin-specific language.

- **`secret_hitler`** -- Standard theme. Liberals, Fascists, Hitler.
- **`corporate_board`** -- Re-themed as a corporate power struggle.
  Reformists vs. Loyalists vs. the Shadow CEO.

Set the skin with `--skin corporate_board`. Both skins are tested to
cover all game phases, roles, policies, and powers.


## Project layout

```
game/
    engine.py           State machine (GameEngine class)
    types.py            Enums, dataclasses, actions, exceptions
    roles.py            Role assignment and knowledge rules
    policies.py         Policy deck (11 fascist, 6 liberal)
    powers.py           Executive power tracks by player count
    terms.py            Term limit (chancellor eligibility) logic
    skins/
        base.py         Abstract skin interface
        secret_hitler.py
        corporate_board.py

server/
    app.py              FastAPI routes + MCP streamable-http
    game_session.py     GameSession (wraps engine + discussion + auth)
    models.py           Pydantic request/response models
    auth.py             Token generation
    game_logger.py      JSONL logging

orchestration/
    orchestrator.py     Turn-driven game loop, parallel invocation
    backends.py         Backend abstraction (ClaudeCode, OpenCode, Agent sessions)
    claude_code_launcher.py   Backward-compat shim

prompts/                Markdown templates (base rules + per-role)

# External dependency (installed via uv):
# agents — https://github.com/Antonio-Tresol/agents
#   Custom ReAct agent core with OpenRouter, MCP tools, middleware

examples/
    game_config.yaml          Single-model config example
    game_mixed_e2e.yaml       Mixed-backend config example

docs/
    analysis-guide.md         Log format reference and analysis process

tests/                  415+ unit/integration tests + 1 E2E test
```


## Licence

CC-BY-NC-SA-4.0
