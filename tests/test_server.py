"""Tests for FastAPI REST routes in server/app.py (~20 tests)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from server.app import app

# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def client():
    return TestClient(app)


def _create_lobby(client: TestClient, num_players: int = 5, skin: str = "secret_hitler", seed: int = 42) -> dict:
    resp = client.post("/api/lobbies", json={"num_players": num_players, "skin": skin, "seed": seed})
    assert resp.status_code == 200
    return resp.json()


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ─── Lobby routes ────────────────────────────────────────────────────────────


class TestCreateLobby:
    def test_create_lobby_success(self, client: TestClient):
        data = _create_lobby(client)
        assert "game_id" in data
        assert data["num_players"] == 5
        assert data["skin"] == "secret_hitler"
        assert len(data["tokens"]) == 5

    def test_create_lobby_corporate_skin(self, client: TestClient):
        data = _create_lobby(client, skin="corporate_board")
        assert data["skin"] == "corporate_board"

    def test_create_lobby_invalid_player_count(self, client: TestClient):
        resp = client.post("/api/lobbies", json={"num_players": 3})
        assert resp.status_code == 422  # Pydantic validation

    def test_create_lobby_unknown_skin(self, client: TestClient):
        resp = client.post("/api/lobbies", json={"num_players": 5, "skin": "unknown_skin"})
        assert resp.status_code == 400


class TestLobbyStatus:
    def test_lobby_status(self, client: TestClient):
        lobby = _create_lobby(client)
        resp = client.get(f"/api/lobbies/{lobby['game_id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["game_id"] == lobby["game_id"]
        assert data["phase"] == "CHANCELLOR_NOMINATION"

    def test_lobby_status_not_found(self, client: TestClient):
        resp = client.get("/api/lobbies/nonexistent")
        assert resp.status_code == 404


# ─── Orchestrator game routes ────────────────────────────────────────────────


class TestOrchestratorRoutes:
    def test_start_game(self, client: TestClient):
        lobby = _create_lobby(client)
        resp = client.post(f"/api/games/{lobby['game_id']}/start")
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"

    def test_start_game_not_found(self, client: TestClient):
        resp = client.post("/api/games/nonexistent/start")
        assert resp.status_code == 404

    def test_close_discussion(self, client: TestClient):
        lobby = _create_lobby(client)
        resp = client.post(f"/api/games/{lobby['game_id']}/close-discussion")
        assert resp.status_code == 200
        assert resp.json()["status"] == "closed"

    def test_game_result_not_over(self, client: TestClient):
        lobby = _create_lobby(client)
        resp = client.get(f"/api/games/{lobby['game_id']}/result")
        assert resp.status_code == 400
        assert "not over" in resp.json()["detail"].lower()


# ─── Player auth routes ─────────────────────────────────────────────────────


class TestPlayerAuth:
    def test_status_requires_auth(self, client: TestClient):
        lobby = _create_lobby(client)
        resp = client.get(f"/api/games/{lobby['game_id']}/status")
        assert resp.status_code == 401

    def test_status_rejects_bad_token(self, client: TestClient):
        lobby = _create_lobby(client)
        resp = client.get(
            f"/api/games/{lobby['game_id']}/status",
            headers=_auth_header("invalid-token"),
        )
        assert resp.status_code == 401

    def test_status_with_valid_token(self, client: TestClient):
        lobby = _create_lobby(client)
        token = next(iter(lobby["tokens"]))
        resp = client.get(
            f"/api/games/{lobby['game_id']}/status",
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["phase"] == "CHANCELLOR_NOMINATION"
        assert data["is_game_over"] is False


# ─── Player game routes ─────────────────────────────────────────────────────


class TestPlayerRoutes:
    def _setup(self, client: TestClient) -> tuple[dict, str, int]:
        """Create a lobby and return (lobby_data, first_token, player_id)."""
        lobby = _create_lobby(client)
        token = next(iter(lobby["tokens"]))
        pid = lobby["tokens"][token]
        return lobby, token, pid

    def test_observation(self, client: TestClient):
        lobby, token, pid = self._setup(client)
        resp = client.get(
            f"/api/games/{lobby['game_id']}/observation",
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "raw" in data
        assert "skinned" in data
        assert data["raw"]["your_id"] == pid

    def test_submit_action_nominate(self, client: TestClient):
        lobby = _create_lobby(client)
        game_id = lobby["game_id"]
        tokens = lobby["tokens"]

        # Find the president by checking game status with each token
        for token, pid in tokens.items():
            resp = client.get(f"/api/games/{game_id}/status", headers=_auth_header(token))
            status = resp.json()
            pa = status["pending_action"]
            if pa and pa["required_by"] == pid:
                target = pa["legal_targets"][0]
                resp = client.post(
                    f"/api/games/{game_id}/action",
                    json={"action_type": "nominate", "payload": {"target_id": target}},
                    headers=_auth_header(token),
                )
                assert resp.status_code == 200
                assert resp.json()["event"] == "chancellor_nominated"
                return
        pytest.fail("Could not find president token")

    def test_submit_action_illegal(self, client: TestClient):
        lobby = _create_lobby(client)
        game_id = lobby["game_id"]
        tokens = lobby["tokens"]
        # Find a non-president token
        for token, pid in tokens.items():
            resp = client.get(f"/api/games/{game_id}/status", headers=_auth_header(token))
            status = resp.json()
            pa = status["pending_action"]
            if pa and pa["required_by"] != pid:
                resp = client.post(
                    f"/api/games/{game_id}/action",
                    json={"action_type": "nominate", "payload": {"target_id": 0}},
                    headers=_auth_header(token),
                )
                assert resp.status_code == 400
                return
        pytest.fail("Could not find non-president token")

    def test_speak_and_discussion(self, client: TestClient):
        lobby = _create_lobby(client)
        game_id = lobby["game_id"]
        tokens = lobby["tokens"]

        # First nominate to open a discussion window
        for token, pid in tokens.items():
            resp = client.get(f"/api/games/{game_id}/status", headers=_auth_header(token))
            status = resp.json()
            pa = status["pending_action"]
            if pa and pa["required_by"] == pid:
                target = pa["legal_targets"][0]
                client.post(
                    f"/api/games/{game_id}/action",
                    json={"action_type": "nominate", "payload": {"target_id": target}},
                    headers=_auth_header(token),
                )
                break

        # Now speak
        first_token = next(iter(tokens))
        resp = client.post(
            f"/api/games/{game_id}/speak",
            json={"message": "Hello, world!"},
            headers=_auth_header(first_token),
        )
        assert resp.status_code == 200
        assert resp.json()["message"] == "Hello, world!"

        # Get discussion
        resp = client.get(
            f"/api/games/{game_id}/discussion",
            headers=_auth_header(first_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_open"] is True
        assert len(data["messages"]) == 1

    def test_speak_no_window(self, client: TestClient):
        lobby = _create_lobby(client)
        game_id = lobby["game_id"]
        token = next(iter(lobby["tokens"]))
        resp = client.post(
            f"/api/games/{game_id}/speak",
            json={"message": "Should fail"},
            headers=_auth_header(token),
        )
        assert resp.status_code == 400

    def test_discussion_empty(self, client: TestClient):
        lobby = _create_lobby(client)
        game_id = lobby["game_id"]
        token = next(iter(lobby["tokens"]))
        resp = client.get(
            f"/api/games/{game_id}/discussion",
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_open"] is False
        assert data["messages"] == []

    def test_action_not_found_session(self, client: TestClient):
        resp = client.post(
            "/api/games/nonexistent/action",
            json={"action_type": "nominate", "payload": {"target_id": 1}},
            headers=_auth_header("any-token"),
        )
        assert resp.status_code == 404
