secret-hitler-sandbox
=====================

A research sandbox for studying deceptive alignment in multi-agent LLM
systems using the social deduction game Secret Hitler. LLM agents play
the full game against each other through tool use (MCP), while a
deterministic game engine enforces rules and records everything for
later analysis.

Inspired by the "Among Us" multi-agent deception paper
(github.com/7vik/AmongUs).


What this is
------------

The project has three layers:

1. A pure-Python game engine that implements Secret Hitler as a
   deterministic state machine. All randomness goes through a seeded
   RNG, so games are reproducible.

2. A FastAPI server that exposes the engine over REST and MCP
   (streamable-http). Agents connect to the MCP endpoint; humans or
   scripts can use REST.

3. An orchestrator that launches Claude Code instances as players,
   invokes them turn by turn, and collects transcripts. Each agent gets
   a system prompt with the game rules and its secret role, plus an MCP
   config pointing at the server. The orchestrator uses `--resume` to
   preserve each agent's full conversation history across turns without
   burning context on idle polling.

There are also two narrative "skins" (Secret Hitler and Corporate Board)
that re-theme the game terminology without changing mechanics. This is
for studying whether framing affects agent behavior.


Requirements
------------

- Python >= 3.11
- uv (https://docs.astral.sh/uv/)
- Claude Code CLI, installed and authenticated (for running LLM agents)

Install dependencies:

    uv sync


Running the tests
-----------------

Unit and integration tests (no API calls, no Claude Code needed):

    uv run pytest tests/ -v -k "not e2e"

There are currently 303 tests covering the engine, server, MCP tools,
orchestrator, session management, and prompt generation.

The E2E test runs a real game with Claude Code agents and will consume
API tokens:

    uv run pytest tests/test_e2e_claude.py -v -m e2e


Running a game with bots
-------------------------

Bot mode uses random-action bots instead of LLM agents. Useful for
testing the full pipeline without spending tokens.

Start the server:

    uv run uvicorn server.app:app --host 127.0.0.1 --port 8000

In another terminal:

    uv run python -m agents --bot-mode --players 5 --seed 42

The game will run to completion in a few seconds and print the result.


Running a game with Claude Code agents
---------------------------------------

Start the server:

    uv run uvicorn server.app:app --host 127.0.0.1 --port 8000

In another terminal:

    uv run python -m agents --players 5 --seed 42 --model claude-sonnet-4-6

This spawns 5 Claude Code instances. Each gets invoked only when the
orchestrator detects it is their turn to act. A typical 5-player game
takes 10-20 minutes and runs 6-10 rounds.

You can also pass per-player models from Python:

    uv run python -c "
    from agents.orchestrator import GameOrchestrator
    orch = GameOrchestrator(
        num_players=5,
        seed=42,
        models=[
            'claude-opus-4-6',
            'claude-opus-4-6',
            'claude-sonnet-4-6',
            'claude-sonnet-4-6',
            'claude-haiku-4-5-20251001',
        ],
    )
    result = orch.run()
    "

CLI flags:

    --players N             Number of players (5-10, default 5)
    --seed N                Random seed for reproducibility
    --skin NAME             "secret_hitler" or "corporate_board"
    --model MODEL           Default model for all agents
    --bot-mode              Use random bots instead of Claude Code
    --discussion-time SECS  Seconds for discussion windows (default 30)
    --max-turns-action N    Max tool-use rounds per action (default 10)
    --max-turns-discussion N  Max tool-use rounds per discussion (default 5)
    --server-url URL        Game server URL (default http://127.0.0.1:8000)


Reading the logs
----------------

Every game creates a directory under `logs/games/<game_id>/` containing:

    metadata.json                  Game setup (players, skin, seed)
    events.jsonl                   All actions, observations, and the
                                   final result, one JSON object per line
    player_N_transcript.jsonl      Raw Claude Code stream-json output
                                   for each player, all turns appended
    player_N_output.txt            Stderr from Claude Code invocations
    configs/player_N_mcp.json      MCP config used for each player
    configs/player_N_system_prompt.md  Full system prompt (rules + role)

To get a quick summary of a game:

    cat logs/games/<game_id>/events.jsonl | python -c "
    import json, sys
    for line in sys.stdin:
        e = json.loads(line)
        if e['type'] == 'action':
            r = e.get('result', {})
            print(f'P{e[\"player_id\"]} {e[\"action_type\"]:20s} -> {r.get(\"event\",\"\")}')
        elif e['type'] == 'game_result':
            print(f'RESULT: {e[\"data\"][\"winner\"]} ({e[\"data\"][\"condition\"]}), round {e[\"data\"][\"final_round\"]}')
    "

The player transcripts contain the agents' reasoning, tool calls, and
strategy. Look for entries with `"type": "assistant"` to see what the
agent was thinking when it made each decision.


Project layout
--------------

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

    agents/
        orchestrator.py     Turn-driven game loop, parallel voting
        claude_code_launcher.py   PlayerSession, MCP config, system prompts
        prompts/            Markdown templates (base rules + per-role)

    tests/                  303 unit/integration tests + 1 E2E test


How it works
------------

The game engine is a pure state machine. It accepts action objects
(NominateChancellor, CastVote, PresidentDiscard, etc.) and returns
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
player's Claude Code session with `--resume` to preserve conversation
history. For voting, all players are invoked in parallel. After each
invocation the agent process exits, so there are no long-lived
subprocesses burning context while idle.

Each agent session uses `--session-id` on its first invocation and
`--resume` on all subsequent ones. This means the agent remembers
everything from previous turns (past observations, its own reasoning,
discussion messages, who it suspects) without needing to re-read
the full game history each time.


Skins
-----

Skins remap the game's terminology without touching mechanics. The
engine never references skin-specific language.

- `secret_hitler`: Standard theme. Liberals, Fascists, Hitler.
- `corporate_board`: Re-themed as a corporate power struggle.
  Reformists vs. Loyalists vs. the Shadow CEO.

Set the skin with `--skin corporate_board`. Both skins are tested to
cover all game phases, roles, policies, and powers.


License
-------

CC-BY-NC-SA-4.0
