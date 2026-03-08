# server/

FastAPI server exposing the Secret Hitler game engine via REST API and MCP
streamable-http transport. Agents (LLM or bot) interact with the game through
per-player authenticated endpoints.

## Files

- **app.py** -- FastAPI application. Defines REST routes for orchestrator
  operations (lobby creation, game start/close/delete) and player operations
  (status, observation, action, discussion). Mounts an MCP streamable-http ASGI
  handler at `/mcp/` with per-connection tool servers. Contains `DiffCache` for
  efficient state diffing per player.

- **game_session.py** -- `GameSession` wraps `GameEngine` with token auth,
  discussion windows, skin translation, and JSONL logging. Uses a declarative
  `_ACTION_SPECS` mapping to convert `(action_type, payload)` pairs into frozen
  action dataclasses without branching.

- **models.py** -- Pydantic request/response models (`CreateLobbyRequest`,
  `ActionRequest`, `GameStatusResponse`, etc.) and frozen dataclasses with
  `to_dict()` for structured sub-objects (`PendingActionInfo`, `GameResultInfo`,
  `NoChangeResponse`).

- **auth.py** -- Generates per-player bearer tokens via `secrets.token_urlsafe`.
  Returns a `{token: player_id}` mapping at lobby creation.

- **game_logger.py** -- `GameLogger` writes per-game JSONL logs to
  `logs/games/{game_id}/` (metadata.json + events.jsonl). Logs observations,
  actions, discussion messages, and game results with UTC timestamps.

## Key design decisions

- **MCP transport**: Streamable-http (not SSE), mounted as raw ASGI at `/mcp/`.
  Each request creates a stateless `StreamableHTTPSessionManager` with
  `json_response=True`. Player identity is resolved from query params
  (`?token=...&game_id=...`).

- **DiffCache**: Per-player caches for status, observation, and discussion.
  MCP tools return only changed fields by default; clients pass `full=true` to
  get the complete state. Unchanged responses return a `NoChangeResponse`.

- **Declarative action specs**: `_ACTION_SPECS` maps action type strings to
  `(dataclass, field_names)` tuples, so `_build_action` constructs any game
  action without if/elif chains.

- **Auth model**: Bearer tokens for REST routes; query-param tokens for MCP.
  Tokens are generated once at lobby creation and map 1:1 to player IDs.

- **Discussion windows**: Automatically opened after nomination (pre-vote) and
  after policy enactment (post-legislative). Closed explicitly by the
  orchestrator or implicitly on the next action submission.
