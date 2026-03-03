Analyzing Game Logs
===================

Every game produces a directory under `logs/games/<game_id>/` with
structured logs for the game engine and for each agent. This document
explains what each file contains and how to extract useful information
from them.


Directory layout
----------------

    logs/games/<game_id>/
        metadata.json
        events.jsonl
        player_0_transcript.jsonl
        player_0_output.txt
        player_1_transcript.jsonl
        player_1_output.txt
        ...
        configs/
            player_0_mcp.json
            player_0_system_prompt.md
            ...


metadata.json
-------------

Basic game setup. Example:

    {
      "game_id": "d8981b438401",
      "num_players": 5,
      "skin": "secret_hitler",
      "seed": 99
    }


events.jsonl
------------

One JSON object per line. This is the ground-truth record of everything
that happened in the game. Three event types:

### observation

Logged every time a player calls `get_observation()` through MCP. Contains
the full game state as seen by that player (information hiding enforced).

    {
      "type": "observation",
      "player_id": 0,
      "data": {
        "phase": "CHANCELLOR_NOMINATION",
        "round": 1,
        "liberal_policies": 0,
        "fascist_policies": 0,
        "election_tracker": 0,
        "veto_unlocked": false,
        "draw_pile_size": 17,
        "discard_pile_size": 0,
        "players": [{"id": 0, "alive": true, "confirmed_not_hitler": false}, ...],
        "current_president": 0,
        "chancellor_nominee": null,
        "last_elected_president": null,
        "last_elected_chancellor": null,
        "history": [...],
        "your_id": 0,
        "your_role": "liberal",
        "your_party": "liberal",
        "known_fascists": [],
        "known_hitler": null,
        "eligible_chancellors": [1, 2, 3, 4],
        "private_history": []
      },
      "timestamp": "2026-03-03T03:17:49.147721+00:00"
    }

Key fields that only appear when relevant:

- `drawn_policies` -- present when the player is President in the
  legislative phase (the 3 tiles they drew)
- `received_policies` -- present when the player is Chancellor
  (the 2 tiles passed by the President)
- `peeked_policies` -- present during PolicyPeekAck
- `eligible_chancellors` -- present during CHANCELLOR_NOMINATION
- `known_fascists`, `known_hitler` -- role knowledge (fascists see
  each other; in 5-6 player games Hitler also sees the fascist)
- `private_history` -- legislative details only visible to that player
  (what they drew, discarded, received, enacted)

### action

Logged every time a player submits an action.

    {
      "type": "action",
      "player_id": 0,
      "action_type": "nominate",
      "payload": {"target_id": 1},
      "result": {"event": "chancellor_nominated", "nominee": 1},
      "timestamp": "2026-03-03T03:18:08.265177+00:00"
    }

Action types and their payloads:

    nominate           {"target_id": <int>}
    vote               {"vote": true|false}
    president_discard  {"discard_index": 0|1|2}
    chancellor_enact   {"enact_index": 0|1|null}   (null = veto proposal)
    veto_response      {"consent": true|false}
    investigate        {"target_id": <int>}
    peek_ack           {}
    special_election   {"target_id": <int>}
    execute            {"target_id": <int>}

The `result` field contains what the engine returned. For votes, the
last voter's result includes the full election outcome:

    {"event": "election_result", "ja": 3, "nein": 2, "elected": true}

### game_result

Final line. Always exactly one per game.

    {
      "type": "game_result",
      "data": {
        "winner": "fascist",
        "condition": "hitler_elected_chancellor",
        "final_round": 8
      },
      "timestamp": "2026-03-03T03:33:02.654020+00:00"
    }

Win conditions: `liberal_policy_win`, `liberal_hitler_executed`,
`fascist_policy_win`, `fascist_hitler_chancellor`.


Player transcripts (player_N_transcript.jsonl)
----------------------------------------------

These are the raw Claude Code stream-json transcripts, one JSON object
per line. All invocations for a player are appended to the same file,
so you get the full history across all turns.

Line types:

### system

First line of each invocation. Contains the model, session ID, MCP
server config, and tools available.

    {"type": "system", "model": "claude-sonnet-4-6", "session_id": "...", ...}

### assistant

The agent's response. The `message` field contains a `content` array
with typed blocks:

- `thinking` -- the agent's internal reasoning (extended thinking).
  This is where you find the real strategic analysis: who they suspect,
  what they plan to do, whether they are lying.
- `tool_use` -- an MCP tool call. The `name` field tells you which tool
  (`mcp__secret-hitler__get_observation`, `mcp__secret-hitler__submit_action`,
  `mcp__secret-hitler__speak`, etc.) and `input` has the arguments.
- `text` -- the agent's visible output. Usually a summary of what they
  did and why. For fascists, compare this to the `thinking` block to
  see if they are being deceptive.

Example:

    {
      "type": "assistant",
      "message": {
        "role": "assistant",
        "content": [
          {"type": "thinking", "thinking": "I need to discard the liberal to force..."},
          {"type": "tool_use", "name": "mcp__secret-hitler__submit_action", "input": {...}},
          {"type": "text", "text": "I discarded a fascist tile and passed..."}
        ]
      }
    }

### user

Contains tool results (what the MCP server returned to the agent).
The `tool_use_result` field holds the response content.

### result

End-of-invocation summary. Useful for measuring how long each turn took.

    {
      "type": "result",
      "subtype": "success",
      "is_error": false,
      "duration_ms": 21767,
      "num_turns": 5,
      "result": "Round 1, I'm the Liberal President...",
      "session_id": "..."
    }

### rate_limit_event

API rate limit status. Can be ignored for game analysis.


Useful one-liners
-----------------

All examples assume you are in the project root and `GAME` is set:

    GAME=d8981b438401

### Quick game summary (actions only)

    cat logs/games/$GAME/events.jsonl | python -c "
    import json, sys
    for line in sys.stdin:
        e = json.loads(line)
        if e['type'] == 'action':
            r = e.get('result', {})
            print(f'P{e[\"player_id\"]} {e[\"action_type\"]:20s} -> {r.get(\"event\",\"\")}')
        elif e['type'] == 'game_result':
            d = e['data']
            print(f'RESULT: {d[\"winner\"]} ({d[\"condition\"]}), round {d[\"final_round\"]}')
    "

### Extract role assignments

Roles are in the first observation for each player. This pulls them
from the events log:

    cat logs/games/$GAME/events.jsonl | python -c "
    import json, sys
    seen = set()
    for line in sys.stdin:
        e = json.loads(line)
        if e['type'] == 'observation':
            pid = e['player_id']
            if pid not in seen:
                seen.add(pid)
                d = e['data']
                print(f'Player {pid}: role={d[\"your_role\"]}, party={d[\"your_party\"]}')
    "

### Voting record for a specific round

    ROUND=3
    cat logs/games/$GAME/events.jsonl | python -c "
    import json, sys
    round_num = $ROUND
    in_round = False
    for line in sys.stdin:
        e = json.loads(line)
        if e['type'] == 'observation' and e['data'].get('round') == round_num:
            in_round = True
        if e['type'] == 'action' and e['action_type'] == 'vote' and in_round:
            v = 'Ja' if e['payload']['vote'] else 'Nein'
            print(f'Player {e[\"player_id\"]}: {v}')
            if e['result'].get('event') == 'election_result':
                r = e['result']
                outcome = 'PASSED' if r['elected'] else 'FAILED'
                print(f'  Result: {r[\"ja\"]} Ja / {r[\"nein\"]} Nein -> {outcome}')
                in_round = False
    "

### Policy draws and discards (legislative truth)

Shows what each president actually drew and what they discarded. This is
the ground truth that players may lie about in discussion.

    cat logs/games/$GAME/events.jsonl | python -c "
    import json, sys
    current_draw = {}
    for line in sys.stdin:
        e = json.loads(line)
        if e['type'] == 'observation' and 'drawn_policies' in e['data']:
            pid = e['player_id']
            current_draw[pid] = e['data']['drawn_policies']
        if e['type'] == 'action' and e['action_type'] == 'president_discard':
            pid = e['player_id']
            idx = e['payload']['discard_index']
            drew = current_draw.get(pid, [])
            print(f'Round {len(drew) and \"?\"}: P{pid} drew {drew}, discarded index {idx} ({drew[idx] if idx < len(drew) else \"?\"})')
    "

### Extract agent reasoning (thinking blocks)

This pulls the extended thinking from a specific player's transcript.
This is where agents reveal their true strategy.

    PLAYER=3
    cat logs/games/$GAME/player_${PLAYER}_transcript.jsonl | python -c "
    import json, sys
    for line in sys.stdin:
        line = line.strip()
        if not line: continue
        obj = json.loads(line)
        if obj['type'] == 'assistant' and isinstance(obj.get('message'), dict):
            for block in obj['message'].get('content', []):
                if isinstance(block, dict) and block.get('type') == 'thinking':
                    text = block['thinking']
                    if len(text) > 20:
                        print(text)
                        print('---')
    " 2>/dev/null

### Extract agent public statements (text blocks)

What the agent said out loud (as opposed to what it thought privately).
Compare this with the thinking blocks to detect deception.

    PLAYER=4
    cat logs/games/$GAME/player_${PLAYER}_transcript.jsonl | python -c "
    import json, sys
    for line in sys.stdin:
        line = line.strip()
        if not line: continue
        obj = json.loads(line)
        if obj['type'] == 'assistant' and isinstance(obj.get('message'), dict):
            for block in obj['message'].get('content', []):
                if isinstance(block, dict) and block.get('type') == 'text':
                    print(block['text'])
                    print('---')
    " 2>/dev/null

### Invocation stats per player

How many times each player was invoked, total tool-use turns, and
wall-clock time spent.

    for i in 0 1 2 3 4; do
      echo -n "Player $i: "
      cat logs/games/$GAME/player_${i}_transcript.jsonl | python -c "
    import json, sys
    results = []
    for line in sys.stdin:
        line = line.strip()
        if not line: continue
        obj = json.loads(line)
        if obj['type'] == 'result':
            results.append(obj)
    n = len(results)
    turns = sum(r.get('num_turns', 0) for r in results)
    ms = sum(r.get('duration_ms', 0) for r in results)
    print(f'{n} invocations, {turns} tool-use turns, {ms/1000:.1f}s total')
    " 2>/dev/null
    done

### MCP tool calls made by a player

    PLAYER=0
    cat logs/games/$GAME/player_${PLAYER}_transcript.jsonl | python -c "
    import json, sys
    from collections import Counter
    calls = Counter()
    for line in sys.stdin:
        line = line.strip()
        if not line: continue
        obj = json.loads(line)
        if obj['type'] == 'assistant' and isinstance(obj.get('message'), dict):
            for block in obj['message'].get('content', []):
                if isinstance(block, dict) and block.get('type') == 'tool_use':
                    calls[block['name']] += 1
    for name, count in calls.most_common():
        print(f'  {count:3d}  {name}')
    " 2>/dev/null


What to look for
----------------

### Deception in the legislative phase

Compare what the president actually drew (from observation events with
`drawn_policies`) against what they claimed in discussion. Fascist
presidents may lie about their draw to justify discarding liberal
tiles. Similarly, compare what the chancellor received (`received_policies`)
against what they claim.

### Thinking vs. public statements

The `thinking` blocks in transcripts reveal what the agent truly
believes and plans. The `text` blocks are what they say out loud.
Fascist agents will often have thinking that contradicts their public
statements. This is the core data for studying deceptive alignment.

### Voting patterns

Fascists typically vote Ja on governments that include Hitler (especially
after 3 fascist policies) and Nein on strong liberal governments. Look
for voting clusters: players who consistently vote together may be on
the same team.

### The critical round

In games ending with `hitler_elected_chancellor`, the last round is
the one to study most carefully. Trace back: who nominated Hitler, why
did they trust them, what information led to that decision, and what
could the liberals have done differently.

### Investigation results

When a president uses the Investigate power, the game logs the true
party membership they learned. Check whether they reported it honestly
in discussion or lied about it.

### Failed elections and chaos

Three consecutive failed elections trigger chaos (a policy is enacted
from the top of the deck with no vote). This resets term limits. Watch
for fascists deliberately tanking votes to force chaos when the deck
is fascist-heavy.


Configs directory
-----------------

`configs/player_N_mcp.json` contains the MCP connection config that was
given to each agent. The URL includes the player's auth token and game
ID.

`configs/player_N_system_prompt.md` is the full system prompt: base
game rules, role-specific instructions, and the game premise from the
skin. Reading these helps understand what the agent was told about
its objectives and strategy.
