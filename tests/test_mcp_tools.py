"""Tests for MCP tool handler functions (unit tests without SSE transport)."""

from __future__ import annotations

import json
import tempfile

import pytest

from game.types import IllegalActionError
from server.app import _handle_mcp_tool
from server.game_session import GameSession


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def session() -> GameSession:
    """Create a fresh GameSession with 5 players, seeded for reproducibility."""
    s = GameSession(num_players=5, seed=42, log_base_dir=tempfile.mkdtemp())
    s.setup()
    return s


def _get_president(session: GameSession) -> int:
    """Return the current president's player_id."""
    status = session.get_status()
    return status["pending_action"]["required_by"]


def _get_legal_targets(session: GameSession) -> list[int]:
    """Return legal targets for the current pending action."""
    status = session.get_status()
    return status["pending_action"]["legal_targets"]


def _parse_result(result: list) -> dict:
    """Parse the TextContent list returned by _handle_mcp_tool into a dict."""
    assert len(result) == 1
    return json.loads(result[0].text)


# ─── get_game_status ─────────────────────────────────────────────────────────


class TestGetGameStatus:
    def test_returns_status(self, session: GameSession):
        result = _handle_mcp_tool(session, 0, "get_game_status", {})
        data = _parse_result(result)
        assert data["phase"] == "CHANCELLOR_NOMINATION"
        assert data["is_game_over"] is False
        assert "pending_action" in data

    def test_has_game_id(self, session: GameSession):
        result = _handle_mcp_tool(session, 0, "get_game_status", {})
        data = _parse_result(result)
        assert data["game_id"] == session.game_id


# ─── get_observation ─────────────────────────────────────────────────────────


class TestGetObservation:
    def test_returns_observation(self, session: GameSession):
        result = _handle_mcp_tool(session, 0, "get_observation", {})
        data = _parse_result(result)
        assert "raw" in data
        assert "skinned" in data
        assert data["raw"]["your_id"] == 0

    def test_different_players_see_own_id(self, session: GameSession):
        r0 = _parse_result(_handle_mcp_tool(session, 0, "get_observation", {}))
        r2 = _parse_result(_handle_mcp_tool(session, 2, "get_observation", {}))
        assert r0["raw"]["your_id"] == 0
        assert r2["raw"]["your_id"] == 2


# ─── submit_action ───────────────────────────────────────────────────────────


class TestSubmitAction:
    def test_nominate_success(self, session: GameSession):
        president = _get_president(session)
        targets = _get_legal_targets(session)
        result = _handle_mcp_tool(
            session,
            president,
            "submit_action",
            {"action_type": "nominate", "payload": {"target_id": targets[0]}},
        )
        data = _parse_result(result)
        assert data["event"] == "chancellor_nominated"

    def test_illegal_action_returns_error(self, session: GameSession):
        # Player 0 is not necessarily the president, but even if they are,
        # nominating themselves is likely illegal. We pick a non-president.
        president = _get_president(session)
        non_president = next(p for p in range(5) if p != president)
        result = _handle_mcp_tool(
            session,
            non_president,
            "submit_action",
            {"action_type": "nominate", "payload": {"target_id": 1}},
        )
        data = _parse_result(result)
        assert "error" in data


# ─── speak ───────────────────────────────────────────────────────────────────


class TestSpeak:
    def test_speak_with_open_window(self, session: GameSession):
        # Nominate to open a discussion window
        president = _get_president(session)
        targets = _get_legal_targets(session)
        session.submit_action(president, "nominate", {"target_id": targets[0]})

        result = _handle_mcp_tool(session, 0, "speak", {"message": "Test message"})
        data = _parse_result(result)
        assert data["message"] == "Test message"
        assert data["player_id"] == 0

    def test_speak_no_window_returns_error(self, session: GameSession):
        result = _handle_mcp_tool(session, 0, "speak", {"message": "No window"})
        data = _parse_result(result)
        assert "error" in data


# ─── get_discussion ──────────────────────────────────────────────────────────


class TestGetDiscussion:
    def test_no_discussion(self, session: GameSession):
        result = _handle_mcp_tool(session, 0, "get_discussion", {})
        data = _parse_result(result)
        assert data["is_open"] is False
        assert data["messages"] == []

    def test_with_active_discussion(self, session: GameSession):
        president = _get_president(session)
        targets = _get_legal_targets(session)
        session.submit_action(president, "nominate", {"target_id": targets[0]})
        session.speak(0, "Hello")

        result = _handle_mcp_tool(session, 0, "get_discussion", {})
        data = _parse_result(result)
        assert data["is_open"] is True
        assert len(data["messages"]) == 1


# ─── Unknown tool ────────────────────────────────────────────────────────────


class TestUnknownTool:
    def test_unknown_tool(self, session: GameSession):
        result = _handle_mcp_tool(session, 0, "nonexistent_tool", {})
        data = _parse_result(result)
        assert "error" in data
        assert "Unknown tool" in data["error"]
