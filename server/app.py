"""FastAPI application with REST routes and MCP streamable-http transport."""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from mcp.server import Server as McpServer
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import TextContent, Tool
from starlette.requests import Request as StarletteRequest
from starlette.types import Receive, Scope, Send

from game.skins import SKIN_REGISTRY
from game.types import GameOverError, IllegalActionError
from server.game_session import GameSession
from server.models import (
    ActionRequest,
    CreateLobbyRequest,
    DiscussionResponse,
    GameStatusResponse,
    LobbyResponse,
    NoChangeResponse,
    ObservationResponse,
    SpeakRequest,
)

# ─── In-memory session store ────────────────────────────────────────────────

_sessions: dict[str, GameSession] = {}

_SKINS: dict[str, Any] = {**SKIN_REGISTRY, "none": lambda: None}


def get_sessions() -> dict[str, GameSession]:
    """Return the session store (test-friendly access)."""
    return _sessions


# ─── Auth helpers ────────────────────────────────────────────────────────────


def _resolve_player(game_id: str, authorization: str | None) -> tuple[GameSession, int]:
    """Look up session + player_id from a Bearer token.

    Raises HTTPException on failure.
    """
    session = _sessions.get(game_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Game session not found")

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Bearer token")

    token = authorization.removeprefix("Bearer ")
    try:
        player_id = session.get_player_id(token)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid token")

    return session, player_id


def _get_session(game_id: str) -> GameSession:
    """Look up a session by game_id; raise 404 if missing."""
    session = _sessions.get(game_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Game session not found")
    return session


# ─── FastAPI app ─────────────────────────────────────────────────────────────

app = FastAPI(title="Secret Hitler MCP Server")


# ─── Orchestrator routes (no auth) ──────────────────────────────────────────


@app.post("/api/lobbies", response_model=LobbyResponse)
def create_lobby(req: CreateLobbyRequest) -> LobbyResponse:
    skin_factory = _SKINS.get(req.skin)
    if skin_factory is None:
        raise HTTPException(status_code=400, detail=f"Unknown skin: {req.skin!r}")
    skin = skin_factory()

    session = GameSession(num_players=req.num_players, skin=skin, seed=req.seed)
    tokens = session.setup()
    _sessions[session.game_id] = session

    return LobbyResponse(
        game_id=session.game_id,
        num_players=req.num_players,
        skin=req.skin,
        tokens=tokens,
    )


@app.get("/api/lobbies/{game_id}")
def lobby_status(game_id: str) -> dict:
    session = _get_session(game_id)
    status = session.get_status()
    return {
        "game_id": session.game_id,
        "num_players": status["pending_action"]["required_by"]
        if isinstance(status.get("pending_action", {}).get("required_by"), list)
        else status.get("round", 0),
        "phase": status["phase"],
        "is_game_over": status["is_game_over"],
    }


@app.post("/api/games/{game_id}/start")
def start_game(game_id: str) -> dict:
    """Start game is a no-op since setup() happens at lobby creation.

    This exists as a checkpoint the orchestrator can call to confirm the game
    is ready.
    """
    session = _get_session(game_id)
    return {"game_id": session.game_id, "status": "running"}


@app.post("/api/games/{game_id}/close-discussion")
def close_discussion(game_id: str) -> dict:
    session = _get_session(game_id)
    session.close_discussion()
    return {"status": "closed"}


@app.get("/api/games/{game_id}/result")
def game_result(game_id: str) -> dict:
    session = _get_session(game_id)
    status = session.get_status()
    if not status["is_game_over"]:
        raise HTTPException(status_code=400, detail="Game is not over yet")
    return {"game_id": session.game_id, "result": status["result"]}


@app.delete("/api/games/{game_id}")
def delete_game(game_id: str) -> dict:
    session = _sessions.pop(game_id, None)
    if session is None:
        raise HTTPException(status_code=404, detail="Game session not found")
    _diff_cache.cleanup_game(game_id)
    return {"status": "deleted", "game_id": game_id}


# ─── Player routes (Bearer token auth) ──────────────────────────────────────


@app.get("/api/games/{game_id}/status", response_model=GameStatusResponse)
def game_status(game_id: str, authorization: str | None = Header(default=None)) -> GameStatusResponse:
    session, _pid = _resolve_player(game_id, authorization)
    status = session.get_status()
    return GameStatusResponse(**status)


@app.get("/api/games/{game_id}/observation", response_model=ObservationResponse)
def observation(game_id: str, authorization: str | None = Header(default=None)) -> ObservationResponse:
    session, player_id = _resolve_player(game_id, authorization)
    obs = session.get_observation(player_id)
    return ObservationResponse(**obs)


@app.post("/api/games/{game_id}/action")
def submit_action(game_id: str, req: ActionRequest, authorization: str | None = Header(default=None)) -> dict:
    session, player_id = _resolve_player(game_id, authorization)
    try:
        result = session.submit_action(player_id, req.action_type, req.payload)
    except IllegalActionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except GameOverError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@app.post("/api/games/{game_id}/speak")
def speak(game_id: str, req: SpeakRequest, authorization: str | None = Header(default=None)) -> dict:
    session, player_id = _resolve_player(game_id, authorization)
    try:
        entry = session.speak(player_id, req.message)
    except IllegalActionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return entry


@app.get("/api/games/{game_id}/discussion", response_model=DiscussionResponse | None)
def discussion(game_id: str, authorization: str | None = Header(default=None)) -> DiscussionResponse | dict:
    session, _pid = _resolve_player(game_id, authorization)
    disc = session.get_discussion()
    if disc is None:
        return DiscussionResponse(round=0, window="none", is_open=False, messages=[])
    return DiscussionResponse(**disc)


# ─── MCP streamable-http ─────────────────────────────────────────────────────


def _create_mcp_server(session: GameSession, player_id: int) -> McpServer:
    """Create a per-connection MCP server with tools bound to a specific player."""
    mcp = McpServer(f"sh-player-{player_id}")

    _full_schema = {
        "type": "boolean",
        "description": "Set to true to get the full state instead of a diff. Default false.",
    }

    @mcp.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="get_game_status",
                description=(
                    "Get the current game status. Returns only changed fields"
                    " by default (diff mode). Pass full=true for complete state."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {"full": _full_schema},
                },
            ),
            Tool(
                name="get_observation",
                description=(
                    "Get your observation of the game state. Returns only changed"
                    " fields by default (diff mode). Pass full=true for complete state."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {"full": _full_schema},
                },
            ),
            Tool(
                name="submit_action",
                description="Submit a game action",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "action_type": {
                            "type": "string",
                            "description": (
                                "Action type: nominate, vote, president_discard,"
                                " chancellor_enact, veto_response, investigate,"
                                " peek_ack, special_election, execute"
                            ),
                        },
                        "payload": {
                            "type": "object",
                            "description": 'Action payload object (e.g. {"target_id": 2})',
                        },
                    },
                    "required": ["action_type", "payload"],
                },
            ),
            Tool(
                name="speak",
                description="Send a discussion message",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "message": {"type": "string", "description": "Your message"},
                    },
                    "required": ["message"],
                },
            ),
            Tool(
                name="get_discussion",
                description=(
                    "Get current discussion messages. Returns only new messages"
                    " by default (diff mode). Pass full=true for all messages."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {"full": _full_schema},
                },
            ),
        ]

    @mcp.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        return _handle_mcp_tool(session, player_id, name, arguments)

    return mcp


# ─── Diff cache ─────────────────────────────────────────────────────────────


class DiffCache:
    """Per-player state caches for MCP diff computation."""

    def __init__(self) -> None:
        self._status: dict[tuple[str, int], dict] = {}
        self._observation: dict[tuple[str, int], dict] = {}
        self._discussion_count: dict[tuple[str, int], int] = {}

    def get_last_status(self, key: tuple[str, int]) -> dict | None:
        return self._status.get(key)

    def set_last_status(self, key: tuple[str, int], val: dict) -> None:
        self._status[key] = val

    def get_last_observation(self, key: tuple[str, int]) -> dict | None:
        return self._observation.get(key)

    def set_last_observation(self, key: tuple[str, int], val: dict) -> None:
        self._observation[key] = val

    def get_last_discussion_count(self, key: tuple[str, int]) -> int:
        return self._discussion_count.get(key, 0)

    def set_last_discussion_count(self, key: tuple[str, int], val: int) -> None:
        self._discussion_count[key] = val

    def invalidate(self, game_id: str, player_id: int) -> None:
        key = (game_id, player_id)
        self._status.pop(key, None)
        self._observation.pop(key, None)

    def cleanup_game(self, game_id: str) -> None:
        for cache in (self._status, self._observation, self._discussion_count):
            to_remove = [k for k in cache if k[0] == game_id]
            for k in to_remove:
                del cache[k]


_diff_cache = DiffCache()


def _dict_diff(old: dict, new: dict) -> dict:
    """Return only keys whose values changed between *old* and *new*.

    Always includes ``phase``, ``round``, and ``is_game_over`` for orientation.
    """
    always = {"phase", "round", "is_game_over"}
    diff: dict = {}
    for k, v in new.items():
        if k in always or old.get(k) != v:
            diff[k] = v
    return diff


# ─── Per-tool MCP handlers ──────────────────────────────────────────────────


def _handle_get_status(session: GameSession, player_id: int, arguments: dict, cache: DiffCache) -> list[TextContent]:
    status = session.get_status()
    key = (session.game_id, player_id)
    want_full = arguments.get("full", False)
    prev = cache.get_last_status(key)
    cache.set_last_status(key, status)
    if not want_full and prev is not None:
        diff = _dict_diff(prev, status)
        always_keys = {k for k in ("phase", "round", "is_game_over") if k in status}
        if set(diff.keys()) == always_keys:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        NoChangeResponse(phase=status.get("phase"), round=status.get("round")).to_dict(),
                        default=str,
                    ),
                ),
            ]
        diff["_diff"] = True
        return [TextContent(type="text", text=json.dumps(diff, default=str))]
    return [TextContent(type="text", text=json.dumps(status, default=str))]


def _handle_get_observation(
    session: GameSession,
    player_id: int,
    arguments: dict,
    cache: DiffCache,
) -> list[TextContent]:
    obs = session.get_observation(player_id)
    key = (session.game_id, player_id)
    want_full = arguments.get("full", False)
    prev = cache.get_last_observation(key)
    cache.set_last_observation(key, obs)
    if not want_full and prev is not None:
        old_raw = prev.get("raw", {})
        new_raw = obs.get("raw", {})
        diff_raw = _dict_diff(old_raw, new_raw)
        if diff_raw == {k: new_raw[k] for k in ("phase", "round", "is_game_over") if k in new_raw}:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        NoChangeResponse(phase=new_raw.get("phase"), round=new_raw.get("round")).to_dict(),
                        default=str,
                    ),
                ),
            ]
        result = {"_diff": True, "raw": diff_raw}
        if "skinned" in obs and "skinned" in prev:
            result["skinned"] = _dict_diff(prev["skinned"], obs["skinned"])
        return [TextContent(type="text", text=json.dumps(result, default=str))]
    return [TextContent(type="text", text=json.dumps(obs, default=str))]


def _handle_submit_action(session: GameSession, player_id: int, arguments: dict, cache: DiffCache) -> list[TextContent]:
    action_type = arguments["action_type"]
    payload = arguments.get("payload", {})
    try:
        result = session.submit_action(player_id, action_type, payload)
    except (IllegalActionError, GameOverError) as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]
    cache.invalidate(session.game_id, player_id)
    return [TextContent(type="text", text=json.dumps(result, default=str))]


def _handle_speak(session: GameSession, player_id: int, arguments: dict) -> list[TextContent]:
    message = arguments["message"]
    try:
        entry = session.speak(player_id, message)
    except IllegalActionError as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]
    return [TextContent(type="text", text=json.dumps(entry))]


def _handle_get_discussion(
    session: GameSession,
    player_id: int,
    arguments: dict,
    cache: DiffCache,
) -> list[TextContent]:
    disc = session.get_discussion()
    if disc is None:
        disc = {"round": 0, "window": "none", "is_open": False, "messages": []}
    key = (session.game_id, player_id)
    want_full = arguments.get("full", False)
    prev_count = cache.get_last_discussion_count(key)
    msgs = disc.get("messages", [])
    cache.set_last_discussion_count(key, len(msgs))
    if not want_full and prev_count > 0:
        new_msgs = msgs[prev_count:]
        if not new_msgs:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        NoChangeResponse(message_count=len(msgs)).to_dict(),
                    ),
                ),
            ]
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "_diff": True,
                        "round": disc["round"],
                        "window": disc["window"],
                        "is_open": disc["is_open"],
                        "new_messages": new_msgs,
                        "total_count": len(msgs),
                    },
                ),
            ),
        ]
    return [TextContent(type="text", text=json.dumps(disc))]


# Dispatch table: tool name -> handler function
# Handlers with cache get 4 args; "speak" gets 3 (no cache needed).
_MCP_HANDLERS: dict[str, Any] = {
    "get_game_status": _handle_get_status,
    "get_observation": _handle_get_observation,
    "submit_action": _handle_submit_action,
    "speak": _handle_speak,
    "get_discussion": _handle_get_discussion,
}


def _handle_mcp_tool(session: GameSession, player_id: int, name: str, arguments: dict) -> list[TextContent]:
    """Handle an MCP tool call. Separated for unit-testing."""
    handler = _MCP_HANDLERS.get(name)
    if handler is None:
        return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]
    if handler is _handle_speak:
        return handler(session, player_id, arguments)
    return handler(session, player_id, arguments, _diff_cache)


async def _handle_mcp_http(scope: Scope, receive: Receive, send: Send) -> None:
    """ASGI handler for MCP streamable-http: validate token, dispatch to manager."""
    request = StarletteRequest(scope, receive)
    token = request.query_params.get("token")
    game_id = request.query_params.get("game_id")

    if not token or not game_id:
        resp = JSONResponse(
            status_code=400,
            content={"detail": "Missing token or game_id query parameter"},
        )
        await resp(scope, receive, send)
        return

    session = _sessions.get(game_id)
    if session is None:
        resp = JSONResponse(status_code=404, content={"detail": "Game session not found"})
        await resp(scope, receive, send)
        return

    try:
        player_id = session.get_player_id(token)
    except ValueError:
        resp = JSONResponse(status_code=401, content={"detail": "Invalid token"})
        await resp(scope, receive, send)
        return

    # Create a fresh stateless MCP server + manager per request.
    # With stateless=True each request is self-contained.
    mcp = _create_mcp_server(session, player_id)
    manager = StreamableHTTPSessionManager(
        app=mcp,
        stateless=True,
        json_response=True,
    )
    async with manager.run():
        await manager.handle_request(scope, receive, send)


# Mount MCP streamable-http as a raw ASGI app (not a Starlette endpoint)
app.mount("/mcp", app=_handle_mcp_http)
