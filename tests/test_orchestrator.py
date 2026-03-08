"""Tests for the orchestrator, backends, and Claude Code launcher shim."""

from __future__ import annotations

import json
import random
import subprocess
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from orchestration.backends import (
    ClaudeCodeSession,
    OpenCodeSession,
    create_session,
    parse_model_spec,
)
from orchestration.claude_code_launcher import (
    InvocationResult,
    PlayerSession,
    build_mcp_config,
    build_system_prompt,
)
from orchestration.orchestrator import GameOrchestrator, RandomBot, load_config, print_game_status
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
            discussion_rounds=0,
            poll_interval=0.0,
        )
        transport = httpx.MockTransport(lambda req: _forward_to_test_client(client, req))
        with httpx.Client(transport=transport) as http:
            orch.create_lobby(http)
            orch.start_game(http)
            orch.setup_players(http)
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
            discussion_rounds=0,
            poll_interval=0.0,
        )
        transport = httpx.MockTransport(lambda req: _forward_to_test_client(client, req))
        with httpx.Client(transport=transport) as http:
            orch.create_lobby(http)
            orch.start_game(http)
            orch.setup_players(http)
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
                discussion_rounds=0,
                poll_interval=0.0,
            )
            transport = httpx.MockTransport(lambda req: _forward_to_test_client(client, req))
            with httpx.Client(transport=transport) as http:
                orch.create_lobby(http)
                orch.start_game(http)
                orch.setup_players(http)
                result = orch.run_game_loop(http)
                results.append(result["result"]["final_round"])

        # At least 2 of 3 seeds should produce different final rounds
        assert len(set(results)) >= 2, f"All seeds produced same final_round: {results}"


# ─── Helper: forward httpx request to FastAPI TestClient ─────────────────────


# ─── Shared mock helper ──────────────────────────────────────────────────────


def _fake_run(
    calls: list[list[str]] | None = None,
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
):
    """Return a mock for ``agents.backends._run_with_timeout``.

    *calls* — if provided, each invocation's cmd is appended.
    *stdout*/*stderr*/*returncode* — values for the CompletedProcess.
    """

    def mock_run(cmd, *, env=None, timeout=120):
        if calls is not None:
            calls.append(list(cmd))
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        ), False

    return mock_run


# ─── PlayerSession (backward-compat shim tests) ─────────────────────────────


class TestPlayerSession:
    @staticmethod
    def _make_session(tmp_path, monkeypatch, **overrides):
        monkeypatch.chdir(tmp_path)
        kwargs = dict(
            game_id="test-game",
            player_id=0,
            token="tok",
            server_url="http://localhost",
            skin="secret_hitler",
            role="liberal",
            num_players=5,
        )
        kwargs.update(overrides)
        session = PlayerSession(**kwargs)
        session.setup()
        return session

    def test_session_id_is_valid_uuid(self):
        session = PlayerSession(
            game_id="test-game",
            player_id=0,
            token="tok",
            server_url="http://localhost",
            skin="secret_hitler",
            role="liberal",
            num_players=5,
        )
        # Should not raise
        uuid.UUID(session.session_id)

    def test_setup_creates_config_files(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        session = PlayerSession(
            game_id="test-game",
            player_id=2,
            token="tok-abc",
            server_url="http://localhost:8000",
            skin="secret_hitler",
            role="fascist",
            num_players=7,
        )
        session.setup()

        config_dir = tmp_path / "logs" / "games" / "test-game" / "configs"
        assert (config_dir / "player_2_mcp.json").exists()
        assert (config_dir / "player_2_system_prompt.md").exists()

        mcp = json.loads((config_dir / "player_2_mcp.json").read_text())
        assert "mcpServers" in mcp
        assert "tok-abc" in mcp["mcpServers"]["secret-hitler"]["url"]

    def test_setup_creates_scratchpad_files(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        session = PlayerSession(
            game_id="test-game",
            player_id=0,
            token="tok",
            server_url="http://localhost:8000",
            skin="secret_hitler",
            role="liberal",
            num_players=5,
        )
        session.setup()
        notes_dir = tmp_path / "logs" / "games" / "test-game" / "notes"
        assert (notes_dir / "player_0_todo.md").exists()
        assert (notes_dir / "player_0_scratchpad.md").exists()

    def test_system_prompt_includes_scratchpad_paths(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        session = PlayerSession(
            game_id="test-game",
            player_id=0,
            token="tok",
            server_url="http://localhost:8000",
            skin="secret_hitler",
            role="liberal",
            num_players=5,
        )
        session.setup()
        assert "TODO list" in session._system_prompt
        assert "Scratchpad" in session._system_prompt
        assert "player_0_todo.md" in session._system_prompt

    def test_invoke_turn_raises_without_setup(self):
        session = PlayerSession(
            game_id="test-game",
            player_id=0,
            token="tok",
            server_url="http://localhost",
            skin="secret_hitler",
            role="liberal",
            num_players=5,
        )
        with pytest.raises(RuntimeError, match="setup"):
            session.invoke_turn("do something")

    def test_first_invoke_uses_session_id(self, tmp_path, monkeypatch):
        session = self._make_session(tmp_path, monkeypatch)

        calls = []
        monkeypatch.setattr("orchestration.backends._run_with_timeout", _fake_run(calls))
        session.invoke_turn("test prompt")

        assert "--session-id" in calls[0]
        assert session.session_id in calls[0]
        assert "--resume" not in calls[0]
        assert "--append-system-prompt" in calls[0]

    def test_second_invoke_uses_resume(self, tmp_path, monkeypatch):
        session = self._make_session(tmp_path, monkeypatch)

        calls = []
        monkeypatch.setattr("orchestration.backends._run_with_timeout", _fake_run(calls))

        session.invoke_turn("first turn")
        session.invoke_turn("second turn")

        assert "--session-id" in calls[0]
        assert "--resume" not in calls[0]
        assert "--resume" in calls[1]
        assert "--session-id" not in calls[1]
        assert session.session_id in calls[1]

    def test_invoke_appends_transcript(self, tmp_path, monkeypatch):
        session = self._make_session(tmp_path, monkeypatch)

        call_count = [0]

        def counting_run(cmd, *, env=None, timeout=120):
            call_count[0] += 1
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout=f"turn-{call_count[0]}\n",
                stderr=f"err-{call_count[0]}\n",
            ), False

        monkeypatch.setattr("orchestration.backends._run_with_timeout", counting_run)

        session.invoke_turn("turn 1")
        session.invoke_turn("turn 2")

        transcript = (tmp_path / "logs" / "games" / "test-game" / "player_0_transcript.jsonl").read_text()
        assert "turn-1" in transcript
        assert "turn-2" in transcript

    def test_invocation_result_fields(self):
        r = InvocationResult(
            session_id="abc",
            stdout="out",
            stderr="err",
            returncode=0,
            timed_out=False,
        )
        assert r.session_id == "abc"
        assert r.returncode == 0
        assert r.timed_out is False


# ─── Turn-driven prompt builders ────────────────────────────────────────────


class TestTurnDrivenPrompts:
    """Test the orchestrator's prompt-building methods."""

    def _make_orch(self) -> GameOrchestrator:
        return GameOrchestrator(
            server_url="http://testserver",
            num_players=5,
            bot_mode=True,
        )

    def test_build_turn_prompt_nominate(self):
        orch = self._make_orch()
        status = {"round": 1}
        pa = {"phase": "NOMINATION", "legal_targets": [1, 2, 3]}
        prompt = orch._build_turn_prompt(status, pa, "NominateChancellor")
        assert "President" in prompt
        assert "nominate" in prompt.lower()
        assert "[1, 2, 3]" in prompt

    def test_build_turn_prompt_vote(self):
        orch = self._make_orch()
        status = {"round": 2}
        pa = {"phase": "ELECTION_VOTE", "legal_targets": None}
        prompt = orch._build_turn_prompt(status, pa, "CastVote")
        assert "Vote" in prompt or "vote" in prompt
        assert "Ja" in prompt
        assert "Nein" in prompt

    def test_build_turn_prompt_president_discard(self):
        orch = self._make_orch()
        status = {"round": 1}
        pa = {"phase": "LEGISLATIVE_PRESIDENT", "legal_targets": [0, 1, 2]}
        prompt = orch._build_turn_prompt(status, pa, "PresidentDiscard")
        assert "President" in prompt
        assert "discard" in prompt.lower()

    def test_build_turn_prompt_chancellor_enact(self):
        orch = self._make_orch()
        status = {"round": 1}
        pa = {"phase": "LEGISLATIVE_CHANCELLOR", "legal_targets": [0, 1]}
        prompt = orch._build_turn_prompt(status, pa, "ChancellorEnact")
        assert "Chancellor" in prompt
        assert "enact" in prompt.lower()

    def test_build_turn_prompt_chancellor_enact_with_veto(self):
        orch = self._make_orch()
        status = {"round": 1}
        pa = {"phase": "LEGISLATIVE_CHANCELLOR", "legal_targets": [0, 1, None]}
        prompt = orch._build_turn_prompt(status, pa, "ChancellorEnact")
        assert "Veto" in prompt or "veto" in prompt

    def test_build_turn_prompt_investigate(self):
        orch = self._make_orch()
        status = {"round": 3}
        pa = {"phase": "EXECUTIVE_ACTION", "legal_targets": [1, 3]}
        prompt = orch._build_turn_prompt(status, pa, "InvestigatePlayer")
        assert "investigate" in prompt.lower()
        assert "[1, 3]" in prompt

    def test_build_turn_prompt_execute(self):
        orch = self._make_orch()
        status = {"round": 5}
        pa = {"phase": "EXECUTIVE_ACTION", "legal_targets": [0, 2]}
        prompt = orch._build_turn_prompt(status, pa, "ExecutePlayer")
        assert "execute" in prompt.lower()

    def test_build_turn_prompt_special_election(self):
        orch = self._make_orch()
        status = {"round": 4}
        pa = {"phase": "EXECUTIVE_ACTION", "legal_targets": [1, 2, 3]}
        prompt = orch._build_turn_prompt(status, pa, "SpecialElection")
        assert "Special Election" in prompt

    def test_build_turn_prompt_policy_peek(self):
        orch = self._make_orch()
        status = {"round": 3}
        pa = {"phase": "EXECUTIVE_ACTION", "legal_targets": None}
        prompt = orch._build_turn_prompt(status, pa, "PolicyPeekAck")
        assert "peek" in prompt.lower()

    def test_build_turn_prompt_veto_response(self):
        orch = self._make_orch()
        status = {"round": 5}
        pa = {"phase": "VETO_REPLY", "legal_targets": None}
        prompt = orch._build_turn_prompt(status, pa, "VetoResponse")
        assert "veto" in prompt.lower()
        assert "consent" in prompt.lower()

    def test_build_discussion_prompt(self):
        orch = self._make_orch()
        status = {"round": 2}
        disc = {"is_open": True, "messages": [{"player_id": 0, "message": "hi"}]}
        prompt = orch._build_discussion_prompt(status, disc)
        assert "DISCUSSION" in prompt
        assert "speak" in prompt.lower()
        assert "1 messages already posted" in prompt

    def test_build_discussion_prompt_no_messages(self):
        orch = self._make_orch()
        status = {"round": 1}
        prompt = orch._build_discussion_prompt(status, None)
        assert "DISCUSSION" in prompt
        assert "speak" in prompt.lower()

    def test_discussion_prompt_includes_timeout(self):
        orch = GameOrchestrator(
            server_url="http://testserver",
            num_players=5,
            bot_mode=True,
            discussion_timeout=45,
        )
        prompt = orch._build_discussion_prompt({"round": 1}, None)
        assert "45 seconds" in prompt

    def test_turn_prompt_includes_timeout(self):
        orch = GameOrchestrator(
            server_url="http://testserver",
            num_players=5,
            bot_mode=True,
            action_timeout=120.0,
        )
        pa = {"phase": "NOMINATION", "legal_targets": [1, 2]}
        prompt = orch._build_turn_prompt({"round": 1}, pa, "NominateChancellor")
        assert "120 seconds" in prompt

    def test_build_turn_prompt_unknown_action(self):
        orch = self._make_orch()
        status = {"round": 1}
        pa = {"phase": "UNKNOWN", "legal_targets": None}
        prompt = orch._build_turn_prompt(status, pa, "SomeFutureAction")
        assert "SomeFutureAction" in prompt


# ─── parse_model_spec ────────────────────────────────────────────────────────


class TestParseModelSpec:
    def test_claudecode_prefix(self):
        backend, model = parse_model_spec("claudecode:claude-sonnet-4-6")
        assert backend == "claude_code"
        assert model == "claude-sonnet-4-6"

    def test_opencode_prefix(self):
        backend, model = parse_model_spec("opencode:openai/gpt-4-turbo")
        assert backend == "open_code"
        assert model == "openai/gpt-4-turbo"

    def test_opencode_with_anthropic_provider(self):
        backend, model = parse_model_spec("opencode:anthropic/claude-sonnet-4-6")
        assert backend == "open_code"
        assert model == "anthropic/claude-sonnet-4-6"

    def test_plain_model_defaults_to_claudecode(self):
        backend, model = parse_model_spec("claude-sonnet-4-6")
        assert backend == "claude_code"
        assert model == "claude-sonnet-4-6"

    def test_case_insensitive_prefix(self):
        backend, model = parse_model_spec("ClaudeCode:claude-opus-4-6")
        assert backend == "claude_code"
        assert model == "claude-opus-4-6"

    def test_invalid_prefix_raises(self):
        with pytest.raises(ValueError, match="Unknown backend prefix"):
            parse_model_spec("unknown:some-model")


# ─── create_session ──────────────────────────────────────────────────────────


class TestCreateSession:
    def test_creates_claudecode_session(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda binary: "/usr/bin/claude" if binary == "claude" else None)
        session = create_session(
            backend="claude_code",
            game_id="g1",
            player_id=0,
            token="tok",
            server_url="http://localhost",
            skin="secret_hitler",
            role="liberal",
            num_players=5,
        )
        assert isinstance(session, ClaudeCodeSession)

    def test_creates_opencode_session(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda binary: "/usr/bin/opencode" if binary == "opencode" else None)
        session = create_session(
            backend="open_code",
            game_id="g1",
            player_id=0,
            token="tok",
            server_url="http://localhost",
            skin="secret_hitler",
            role="liberal",
            num_players=5,
        )
        assert isinstance(session, OpenCodeSession)

    def test_missing_binary_raises_runtime_error(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda binary: None)
        with pytest.raises(RuntimeError, match="not found on PATH"):
            create_session(
                backend="claude_code",
                game_id="g1",
                player_id=0,
                token="tok",
                server_url="http://localhost",
                skin="secret_hitler",
                role="liberal",
                num_players=5,
            )

    def test_unknown_backend_raises_value_error(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda binary: "/usr/bin/x")
        with pytest.raises(ValueError, match="Unknown backend"):
            create_session(
                backend="nonexistent",
                game_id="g1",
                player_id=0,
                token="tok",
                server_url="http://localhost",
                skin="secret_hitler",
                role="liberal",
                num_players=5,
            )


# ─── OpenCodeSession ─────────────────────────────────────────────────────────


class TestOpenCodeSession:
    def _make_session(self, tmp_path, monkeypatch) -> OpenCodeSession:
        monkeypatch.chdir(tmp_path)
        session = OpenCodeSession(
            game_id="test-game",
            player_id=1,
            token="tok-xyz",
            server_url="http://localhost:8000",
            skin="secret_hitler",
            role="liberal",
            num_players=5,
            model="openai/gpt-4-turbo",
        )
        session.setup()
        return session

    def test_config_json_structure(self, tmp_path, monkeypatch):
        self._make_session(tmp_path, monkeypatch)
        config_dir = tmp_path / "logs" / "games" / "test-game" / "configs"
        config_path = config_dir / "player_1_opencode.json"
        assert config_path.exists()

        config = json.loads(config_path.read_text())
        assert config["model"] == "openai/gpt-4-turbo"
        assert config["mcp"]["secret-hitler"]["type"] == "remote"
        assert "tok-xyz" in config["mcp"]["secret-hitler"]["url"]
        # read/write/edit allowed for strategy notes; dangerous tools denied
        perms = config["permission"]
        assert perms["read"] == "allow"
        assert perms["write"] == "allow"
        assert perms["edit"] == "allow"
        assert perms["bash"] == "deny"
        assert perms["glob"] == "deny"
        assert perms["grep"] == "deny"
        assert perms["webfetch"] == "deny"
        assert perms["websearch"] == "deny"
        assert len(config["instructions"]) == 1

    def test_first_invoke_has_no_session_flag(self, tmp_path, monkeypatch):
        session = self._make_session(tmp_path, monkeypatch)

        calls = []
        monkeypatch.setattr(
            "orchestration.backends._run_with_timeout",
            _fake_run(calls, stdout='{"result": "ok"}'),
        )
        session.invoke_turn("do something")

        cmd = calls[0]
        assert "--session" not in cmd
        assert "opencode" in cmd[0].lower()
        assert "run" in cmd
        assert "--format" in cmd
        assert "json" in cmd

    def test_second_invoke_uses_session_id(self, tmp_path, monkeypatch):
        session = self._make_session(tmp_path, monkeypatch)

        calls = []
        session_stdout = '{"type":"step_start","sessionID":"ses_oc123","part":{}}\n'

        def mock_run(cmd, *, env=None, timeout=120):
            calls.append(list(cmd))
            if "export" in cmd:
                return subprocess.CompletedProcess(
                    args=cmd,
                    returncode=0,
                    stdout="{}",
                    stderr="",
                ), False
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout=session_stdout,
                stderr="",
            ), False

        monkeypatch.setattr("orchestration.backends._run_with_timeout", mock_run)

        session.invoke_turn("first turn")
        session.invoke_turn("second turn")

        # Filter to just `opencode run` calls (not export)
        run_calls = [c for c in calls if "run" in c]

        # First run call: no --session
        assert "--session" not in run_calls[0]

        # Second run call: --session with the captured ID
        assert "--session" in run_calls[1]
        idx = run_calls[1].index("--session")
        assert run_calls[1][idx + 1] == "ses_oc123"

    def test_opencode_config_env_var_set(self, tmp_path, monkeypatch):
        session = self._make_session(tmp_path, monkeypatch)

        captured_env = {}

        def env_capturing_run(cmd, *, env=None, timeout=120):
            if env:
                captured_env.update(env)
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout="{}",
                stderr="",
            ), False

        monkeypatch.setattr("orchestration.backends._run_with_timeout", env_capturing_run)
        session.invoke_turn("do something")

        assert "OPENCODE_CONFIG" in captured_env

    def test_extract_session_id_from_jsonl(self):
        """Real OpenCode output: JSONL with sessionID on every line."""
        stdout = (
            '{"type":"step_start","sessionID":"ses_abc123","part":{}}\n'
            '{"type":"text","sessionID":"ses_abc123","part":{}}\n'
        )
        assert OpenCodeSession._extract_session_id(stdout) == "ses_abc123"

    def test_extract_session_id_snake_case_fallback(self):
        stdout = json.dumps({"session_id": "abc-123", "other": "data"})
        assert OpenCodeSession._extract_session_id(stdout) == "abc-123"

    def test_extract_session_id_camelcase_fallback(self):
        stdout = json.dumps({"sessionId": "def-456"})
        assert OpenCodeSession._extract_session_id(stdout) == "def-456"

    def test_extract_session_id_returns_none_on_failure(self):
        assert OpenCodeSession._extract_session_id("not json at all") is None
        assert OpenCodeSession._extract_session_id("") is None

    def test_output_file_appending(self, tmp_path, monkeypatch):
        """Raw run output is appended to the output file."""
        session = self._make_session(tmp_path, monkeypatch)

        call_count = [0]

        def counting_run(cmd, *, env=None, timeout=120):
            call_count[0] += 1
            if "export" in cmd:
                return subprocess.CompletedProcess(
                    args=cmd,
                    returncode=1,
                    stdout="",
                    stderr="",
                ), False
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout=f'{{"turn": {call_count[0]}}}\n',
                stderr=f"log-{call_count[0]}\n",
            ), False

        monkeypatch.setattr("orchestration.backends._run_with_timeout", counting_run)

        session.invoke_turn("turn 1")
        session.invoke_turn("turn 2")

        output = (tmp_path / "logs" / "games" / "test-game" / "player_1_output.txt").read_text()
        assert '"turn": 1' in output
        assert '"turn": 2' in output

    def test_export_transcript_called(self, tmp_path, monkeypatch):
        """When session ID is captured, opencode export is called for transcript."""
        session = self._make_session(tmp_path, monkeypatch)

        calls = []

        def export_aware_run(cmd, *, env=None, timeout=120):
            calls.append(list(cmd))
            if "export" in cmd:
                return subprocess.CompletedProcess(
                    args=cmd,
                    returncode=0,
                    stdout='{"messages": [{"role": "user", "content": "hi"}]}',
                    stderr="",
                ), False
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout='{"type":"step_start","sessionID":"ses_oc789","part":{}}\n',
                stderr="",
            ), False

        monkeypatch.setattr("orchestration.backends._run_with_timeout", export_aware_run)
        session.invoke_turn("do something")

        # Should have called opencode export after the run
        export_calls = [c for c in calls if "export" in c]
        assert len(export_calls) == 1
        assert "ses_oc789" in export_calls[0]

        # Transcript should contain the exported session
        transcript = (tmp_path / "logs" / "games" / "test-game" / "player_1_transcript.jsonl").read_text()
        assert "messages" in transcript

    def test_scratchpad_files_created(self, tmp_path, monkeypatch):
        self._make_session(tmp_path, monkeypatch)
        notes_dir = tmp_path / "logs" / "games" / "test-game" / "notes"
        todo = notes_dir / "player_1_todo.md"
        scratchpad = notes_dir / "player_1_scratchpad.md"
        assert todo.exists()
        assert scratchpad.exists()
        assert "TODO" in todo.read_text()
        assert "Scratchpad" in scratchpad.read_text()

    def test_invoke_raises_without_setup(self):
        session = OpenCodeSession(
            game_id="g1",
            player_id=0,
            token="tok",
            server_url="http://localhost",
            skin="secret_hitler",
            role="liberal",
            num_players=5,
        )
        with pytest.raises(RuntimeError, match="setup"):
            session.invoke_turn("do something")


# ─── Config loading ──────────────────────────────────────────────────────────


class TestConfigLoading:
    def test_single_model_config(self, tmp_path):
        config = {
            "players": 5,
            "seed": 42,
            "skin": "secret_hitler",
            "model": "claudecode:claude-sonnet-4-6",
            "discussion_rounds": 2,
            "max_turns_action": 10,
            "max_turns_discussion": 5,
        }
        config_path = tmp_path / "game.yaml"
        import yaml

        config_path.write_text(yaml.dump(config), encoding="utf-8")

        loaded = load_config(config_path)
        assert loaded["players"] == 5
        assert loaded["model"] == "claudecode:claude-sonnet-4-6"
        assert loaded["seed"] == 42

    def test_mixed_models_config(self, tmp_path):
        config = {
            "players": 5,
            "models": [
                "claudecode:claude-sonnet-4-6",
                "opencode:openai/gpt-4-turbo",
                "claudecode:claude-sonnet-4-6",
                "opencode:openai/gpt-4-turbo",
                "claudecode:claude-sonnet-4-6",
            ],
        }
        config_path = tmp_path / "game.yaml"
        import yaml

        config_path.write_text(yaml.dump(config), encoding="utf-8")

        loaded = load_config(config_path)
        assert loaded["players"] == 5
        assert len(loaded["models"]) == 5
        assert loaded["models"][1] == "opencode:openai/gpt-4-turbo"

    def test_cli_args_override_config(self, tmp_path):
        """Verify the config loading pattern: config file provides defaults, CLI overrides."""
        config = {
            "players": 5,
            "seed": 42,
            "model": "claudecode:claude-sonnet-4-6",
        }
        config_path = tmp_path / "game.yaml"
        import yaml

        config_path.write_text(yaml.dump(config), encoding="utf-8")

        loaded = load_config(config_path)

        # Simulate CLI override
        cfg = {"players": 5, "seed": None, "model": "claude-sonnet-4-6"}
        for key, value in loaded.items():
            if key in cfg:
                cfg[key] = value

        # CLI override: seed from CLI
        cli_seed = 99
        cfg["seed"] = cli_seed

        assert cfg["seed"] == 99
        assert cfg["players"] == 5  # from config file
        assert cfg["model"] == "claudecode:claude-sonnet-4-6"  # from config file

    def test_invalid_config_raises(self, tmp_path):
        config_path = tmp_path / "bad.yaml"
        config_path.write_text("just a string", encoding="utf-8")

        with pytest.raises(ValueError, match="YAML mapping"):
            load_config(config_path)


# ─── Status dashboard ────────────────────────────────────────────────────────


class TestStatusDashboard:
    def test_write_status_creates_status_json(self, tmp_path, monkeypatch):
        """_write_status writes a status.json snapshot to the game log directory."""
        monkeypatch.chdir(tmp_path)
        game_dir = tmp_path / "logs" / "games" / "test-status"
        game_dir.mkdir(parents=True)

        # Write some events
        events = [
            {
                "type": "action",
                "player_id": 0,
                "result": {"event": "policy_enacted", "policy": "liberal"},
                "timestamp": "T1",
            },
            {
                "type": "action",
                "player_id": 1,
                "result": {"event": "election_result", "ja": 4, "nein": 1, "elected": True},
                "timestamp": "T2",
            },
            {"type": "discussion", "player_id": 2, "message": "hi", "timestamp": "T3"},
        ]
        (game_dir / "events.jsonl").write_text(
            "\n".join(json.dumps(e) for e in events),
            encoding="utf-8",
        )

        orch = GameOrchestrator(bot_mode=True)
        orch.game_id = "test-status"
        orch._write_status("voting", "Round 2")

        status_path = game_dir / "status.json"
        assert status_path.exists()
        status = json.loads(status_path.read_text())
        assert status["game_id"] == "test-status"
        assert status["phase"] == "voting"
        assert status["detail"] == "Round 2"
        assert status["board"] == {"liberal": 1, "fascist": 0}
        assert status["elections"] == 1
        assert status["discussion_messages"] == 1

    def test_print_game_status_with_events(self, tmp_path, monkeypatch, capsys):
        """print_game_status reads events.jsonl and prints a dashboard."""
        monkeypatch.chdir(tmp_path)
        game_dir = tmp_path / "logs" / "games" / "test-dash"
        game_dir.mkdir(parents=True)

        events = [
            {
                "type": "action",
                "player_id": 0,
                "action_type": "nominate",
                "result": {"event": "chancellor_nominated", "nominee": 1},
                "timestamp": "2026-03-03T10:00:00+00:00",
            },
            {
                "type": "discussion",
                "player_id": 0,
                "window": "pre_vote",
                "message": "Let's pass this government.",
                "timestamp": "2026-03-03T10:01:00+00:00",
            },
            {
                "type": "action",
                "player_id": 0,
                "action_type": "vote",
                "result": {"event": "election_result", "ja": 4, "nein": 1, "elected": True},
                "timestamp": "2026-03-03T10:02:00+00:00",
            },
            {
                "type": "action",
                "player_id": 1,
                "action_type": "chancellor_enact",
                "result": {"event": "policy_enacted", "policy": "liberal"},
                "timestamp": "2026-03-03T10:03:00+00:00",
            },
        ]
        events_path = game_dir / "events.jsonl"
        events_path.write_text(
            "\n".join(json.dumps(e) for e in events),
            encoding="utf-8",
        )

        print_game_status("test-dash")
        out = capsys.readouterr().out
        assert "test-dash" in out
        assert "1/5" in out  # 1 liberal
        assert "L" in out
        assert "PASSED" in out
        assert "Let's pass" in out

    def test_print_game_status_no_games(self, tmp_path, monkeypatch, capsys):
        """print_game_status handles missing logs directory."""
        monkeypatch.chdir(tmp_path)
        print_game_status(None)
        out = capsys.readouterr().out
        assert "No games found" in out


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
