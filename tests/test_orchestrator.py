"""Tests for the orchestrator and Claude Code launcher."""

from __future__ import annotations

import json
import random
import tempfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from agents.claude_code_launcher import build_mcp_config, build_system_prompt
from agents.orchestrator import GameOrchestrator, RandomBot
from server.app import app, get_sessions


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def client():
    return TestClient(app)


# ─── build_mcp_config ───────────────────────────────────────────────────────


class TestBuildMcpConfig:
    def test_structure(self):
        cfg = build_mcp_config("game123", "http://localhost:8000", "tok-abc")
        assert "mcpServers" in cfg
        assert "secret-hitler" in cfg["mcpServers"]
        srv = cfg["mcpServers"]["secret-hitler"]
        assert srv["type"] == "http"
        assert "game123" in srv["url"]
        assert "tok-abc" in srv["url"]

    def test_url_format(self):
        cfg = build_mcp_config("g1", "http://example.com:9000", "mytoken")
        url = cfg["mcpServers"]["secret-hitler"]["url"]
        assert url == "http://example.com:9000/mcp/?token=mytoken&game_id=g1"


# ─── build_system_prompt ─────────────────────────────────────────────────────


class TestBuildSystemPrompt:
    def test_liberal_prompt_contains_role_guide(self):
        prompt = build_system_prompt("secret_hitler", "liberal", 0, 5, "Test premise.")
        assert "Liberal" in prompt
        assert "player **0**" in prompt
        assert "Test premise." in prompt

    def test_fascist_prompt_contains_role_guide(self):
        prompt = build_system_prompt("secret_hitler", "fascist", 2, 7)
        assert "Fascist" in prompt
        assert "player **2**" in prompt
        assert "7" in prompt

    def test_hitler_prompt_contains_role_guide(self):
        prompt = build_system_prompt("secret_hitler", "hitler", 4, 10)
        assert "Hitler" in prompt
        assert "Survival is everything" in prompt

    def test_unknown_role_raises(self):
        with pytest.raises(ValueError, match="Unknown role"):
            build_system_prompt("secret_hitler", "unknown_role", 0, 5)


# ─── Orchestrator: lobby creation via HTTP ───────────────────────────────────


class TestOrchestratorLobby:
    def test_create_lobby_via_http(self, client: TestClient):
        """Orchestrator creates a lobby through the REST API."""
        orch = GameOrchestrator(
            server_url="http://testserver",
            num_players=5,
            skin="secret_hitler",
            seed=42,
            bot_mode=True,
        )
        # Use the TestClient as an httpx-compatible transport
        transport = httpx.MockTransport(lambda req: _forward_to_test_client(client, req))
        with httpx.Client(transport=transport) as http:
            lobby = orch.create_lobby(http)

        assert "game_id" in lobby
        assert len(lobby["tokens"]) == 5
        assert orch.game_id is not None

    def test_start_game_via_http(self, client: TestClient):
        orch = GameOrchestrator(
            server_url="http://testserver",
            num_players=5,
            skin="secret_hitler",
            seed=42,
            bot_mode=True,
        )
        transport = httpx.MockTransport(lambda req: _forward_to_test_client(client, req))
        with httpx.Client(transport=transport) as http:
            orch.create_lobby(http)
            result = orch.start_game(http)

        assert result["status"] == "running"


# ─── RandomBot ───────────────────────────────────────────────────────────────


class TestRandomBot:
    def test_bot_picks_valid_action(self, client: TestClient):
        """A RandomBot can pick and submit a valid nomination action."""
        # Create a game through the API
        lobby_resp = client.post(
            "/api/lobbies",
            json={"num_players": 5, "skin": "secret_hitler", "seed": 42},
        )
        lobby = lobby_resp.json()
        game_id = lobby["game_id"]
        tokens = lobby["tokens"]

        # Find the president
        for token, pid in tokens.items():
            resp = client.get(
                f"/api/games/{game_id}/status",
                headers={"Authorization": f"Bearer {token}"},
            )
            status = resp.json()
            pa = status["pending_action"]
            if pa and pa["required_by"] == pid:
                bot = RandomBot(game_id, pid, token, "http://testserver", random.Random(42))
                transport = httpx.MockTransport(lambda req: _forward_to_test_client(client, req))
                with httpx.Client(transport=transport) as http:
                    result = bot.act(http)
                assert result is not None
                assert result["event"] == "chancellor_nominated"
                return

        pytest.fail("No president found")


# ─── Full bot-mode game ─────────────────────────────────────────────────────


class TestBotModeFullGame:
    def test_bot_mode_completes_game(self, client: TestClient):
        """A full game with random bots runs to completion."""
        orch = GameOrchestrator(
            server_url="http://testserver",
            num_players=5,
            skin="secret_hitler",
            seed=42,
            bot_mode=True,
            discussion_time=0.0,
            poll_interval=0.0,
        )
        transport = httpx.MockTransport(lambda req: _forward_to_test_client(client, req))
        with httpx.Client(transport=transport) as http:
            orch.create_lobby(http)
            orch.start_game(http)
            orch.spawn_players(http)
            result = orch.run_game_loop(http)

        assert "result" in result
        assert result["result"]["winner"] in ("liberal", "fascist")
        assert result["result"]["condition"] is not None
        assert result["result"]["final_round"] >= 1

    def test_bot_mode_collect_results(self, client: TestClient):
        """collect_results() returns the game result after game over."""
        orch = GameOrchestrator(
            server_url="http://testserver",
            num_players=5,
            skin="secret_hitler",
            seed=42,
            bot_mode=True,
            discussion_time=0.0,
            poll_interval=0.0,
        )
        transport = httpx.MockTransport(lambda req: _forward_to_test_client(client, req))
        with httpx.Client(transport=transport) as http:
            orch.create_lobby(http)
            orch.start_game(http)
            orch.spawn_players(http)
            orch.run_game_loop(http)
            result = orch.collect_results(http)

        assert result["game_id"] == orch.game_id
        assert result["result"]["winner"] in ("liberal", "fascist")

    def test_different_seeds_produce_different_outcomes(self, client: TestClient):
        """Different seeds should (usually) produce different game outcomes."""
        results = []
        for seed in [42, 99, 123]:
            sessions = get_sessions()
            sessions.clear()

            orch = GameOrchestrator(
                server_url="http://testserver",
                num_players=5,
                skin="secret_hitler",
                seed=seed,
                bot_mode=True,
                discussion_time=0.0,
                poll_interval=0.0,
            )
            transport = httpx.MockTransport(lambda req: _forward_to_test_client(client, req))
            with httpx.Client(transport=transport) as http:
                orch.create_lobby(http)
                orch.start_game(http)
                orch.spawn_players(http)
                result = orch.run_game_loop(http)
                results.append(result["result"]["final_round"])

        # At least 2 of 3 seeds should produce different final rounds
        assert len(set(results)) >= 2, f"All seeds produced same final_round: {results}"


# ─── Helper: forward httpx request to FastAPI TestClient ─────────────────────


def _forward_to_test_client(test_client: TestClient, request: httpx.Request) -> httpx.Response:
    """Translate an httpx.Request into a TestClient call and return an httpx.Response."""
    # Extract path from URL
    url = str(request.url)
    # Remove the base URL to get just the path + query
    path = url.replace("http://testserver", "")

    headers = dict(request.headers)
    # Remove host header as TestClient sets its own
    headers.pop("host", None)

    body = request.content
    content_type = headers.get("content-type", "")

    if request.method == "GET":
        resp = test_client.get(path, headers=headers)
    elif request.method == "POST":
        if "application/json" in content_type and body:
            resp = test_client.post(path, content=body, headers=headers)
        else:
            resp = test_client.post(path, headers=headers)
    else:
        resp = test_client.request(request.method, path, content=body, headers=headers)

    return httpx.Response(
        status_code=resp.status_code,
        headers=dict(resp.headers),
        content=resp.content,
    )
