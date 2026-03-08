"""Tests for GameSession: wrapping, skins, discussion, logging, auth, multi-session."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from game.skins.secret_hitler import SecretHitlerSkin
from game.types import IllegalActionError
from server.auth import generate_player_tokens
from server.game_logger import GameLogger
from server.game_session import DiscussionWindow, GameSession

# ─── Helpers ─────────────────────────────────────────────────────────────────


def _make_session(
    num_players: int = 5,
    skin: SecretHitlerSkin | None = None,
    seed: int = 42,
    tmp_dir: str | None = None,
) -> GameSession:
    """Create and set up a GameSession with a temporary log directory."""
    s = GameSession(
        num_players=num_players,
        skin=skin,
        seed=seed,
        log_base_dir=tmp_dir or tempfile.mkdtemp(),
    )
    s.setup()
    return s


def _get_first_token(session: GameSession) -> str:
    """Return an arbitrary valid token from the session."""
    tokens = session.setup()
    return next(iter(tokens))


# ─── Auth module tests ───────────────────────────────────────────────────────


class TestAuth:
    def test_generate_tokens_count(self):
        tokens = generate_player_tokens(7)
        assert len(tokens) == 7

    def test_generate_tokens_unique(self):
        tokens = generate_player_tokens(10)
        assert len(set(tokens.keys())) == 10

    def test_generate_tokens_player_ids(self):
        tokens = generate_player_tokens(5)
        assert set(tokens.values()) == {0, 1, 2, 3, 4}


# ─── Logger tests ────────────────────────────────────────────────────────────


class TestGameLogger:
    def test_log_metadata_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger = GameLogger("test-game", base_dir=tmp)
            logger.log_metadata({"num_players": 5})
            meta_path = Path(tmp) / "test-game" / "metadata.json"
            assert meta_path.exists()
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            assert data["num_players"] == 5

    def test_log_events_creates_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger = GameLogger("test-game", base_dir=tmp)
            logger.log_action(0, "nominate", {"target_id": 1}, {"event": "nominated"})
            logger.log_discussion(0, "pre_vote", "I think player 1 is good")
            events_path = Path(tmp) / "test-game" / "events.jsonl"
            assert events_path.exists()
            lines = events_path.read_text(encoding="utf-8").strip().split("\n")
            assert len(lines) == 2
            first = json.loads(lines[0])
            assert first["type"] == "action"
            assert "timestamp" in first


# ─── Discussion window tests ────────────────────────────────────────────────


class TestDiscussionWindow:
    def test_add_message(self):
        dw = DiscussionWindow(round_number=1, window_type="pre_vote")
        entry = dw.add_message(0, "Hello")
        assert entry["player_id"] == 0
        assert entry["message"] == "Hello"
        assert entry["seq"] == 0

    def test_close_prevents_messages(self):
        dw = DiscussionWindow(round_number=1, window_type="pre_vote")
        dw.close()
        with pytest.raises(IllegalActionError):
            dw.add_message(0, "too late")

    def test_to_dict(self):
        dw = DiscussionWindow(round_number=2, window_type="post_legislative")
        dw.add_message(1, "Interesting move")
        d = dw.to_dict()
        assert d["round"] == 2
        assert d["window"] == "post_legislative"
        assert d["is_open"] is True
        assert len(d["messages"]) == 1


# ─── GameSession wrapping tests ─────────────────────────────────────────────


class TestGameSessionBasic:
    def test_setup_returns_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = GameSession(num_players=5, seed=42, log_base_dir=tmp)
            tokens = session.setup()
            assert len(tokens) == 5
            assert set(tokens.values()) == {0, 1, 2, 3, 4}

    def test_get_player_id_valid_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = GameSession(num_players=5, seed=42, log_base_dir=tmp)
            tokens = session.setup()
            token, pid = next(iter(tokens.items()))
            assert session.get_player_id(token) == pid

    def test_get_player_id_invalid_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = _make_session(tmp_dir=tmp)
            with pytest.raises(ValueError, match="Invalid token"):
                session.get_player_id("bogus-token")

    def test_get_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = _make_session(tmp_dir=tmp)
            status = session.get_status()
            assert status["game_id"] == session.game_id
            assert status["phase"] == "CHANCELLOR_NOMINATION"
            assert status["is_game_over"] is False
            assert status["pending_action"] is not None
            assert status["pending_action"]["expected_action"] == "NominateChancellor"

    def test_get_observation_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = _make_session(tmp_dir=tmp)
            obs = session.get_observation(0)
            assert "raw" in obs
            assert "skinned" in obs
            assert obs["raw"]["your_id"] == 0

    def test_submit_action_nominate(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = _make_session(tmp_dir=tmp)
            # Find the current president from the status
            status = session.get_status()
            president = status["pending_action"]["required_by"]
            targets = status["pending_action"]["legal_targets"]
            result = session.submit_action(president, "nominate", {"target_id": targets[0]})
            assert result["event"] == "chancellor_nominated"


# ─── Skin translation ───────────────────────────────────────────────────────


class TestSkinTranslation:
    def test_observation_uses_skin(self):
        with tempfile.TemporaryDirectory() as tmp:
            skin = SecretHitlerSkin()
            session = _make_session(skin=skin, tmp_dir=tmp)
            obs = session.get_observation(0)
            # Skinned observation should have translated phase
            skinned = obs["skinned"]
            assert skinned["phase"] != "CHANCELLOR_NOMINATION"
            assert "nominating" in skinned["phase"].lower() or "President" in skinned["phase"]

    def test_no_skin_returns_same(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = _make_session(skin=None, tmp_dir=tmp)
            obs = session.get_observation(0)
            assert obs["raw"] == obs["skinned"]


# ─── Discussion integration ─────────────────────────────────────────────────


class TestDiscussionIntegration:
    def test_discussion_opens_after_nomination(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = _make_session(tmp_dir=tmp)
            status = session.get_status()
            president = status["pending_action"]["required_by"]
            targets = status["pending_action"]["legal_targets"]
            session.submit_action(president, "nominate", {"target_id": targets[0]})
            disc = session.get_discussion()
            assert disc is not None
            assert disc["window"] == "pre_vote"
            assert disc["is_open"] is True

    def test_speak_adds_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = _make_session(tmp_dir=tmp)
            status = session.get_status()
            president = status["pending_action"]["required_by"]
            targets = status["pending_action"]["legal_targets"]
            session.submit_action(president, "nominate", {"target_id": targets[0]})
            entry = session.speak(0, "I think this is a good pick")
            assert entry["message"] == "I think this is a good pick"
            disc = session.get_discussion()
            assert len(disc["messages"]) == 1

    def test_speak_fails_without_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = _make_session(tmp_dir=tmp)
            with pytest.raises(IllegalActionError):
                session.speak(0, "no window open")

    def test_close_discussion(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = _make_session(tmp_dir=tmp)
            status = session.get_status()
            president = status["pending_action"]["required_by"]
            targets = status["pending_action"]["legal_targets"]
            session.submit_action(president, "nominate", {"target_id": targets[0]})
            session.close_discussion()
            assert session.get_discussion() is None


# ─── Multi-session independence ──────────────────────────────────────────────


class TestMultiSession:
    def test_independent_game_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            s1 = _make_session(tmp_dir=tmp)
            s2 = _make_session(seed=99, tmp_dir=tmp)
            assert s1.game_id != s2.game_id

    def test_independent_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            s1 = GameSession(num_players=5, seed=42, log_base_dir=tmp)
            t1 = s1.setup()
            s2 = GameSession(num_players=5, seed=99, log_base_dir=tmp)
            s2.setup()
            # Tokens from one session should not work in the other
            token_from_s1 = next(iter(t1))
            with pytest.raises(ValueError):
                s2.get_player_id(token_from_s1)


# ─── Logging integration ────────────────────────────────────────────────────


class TestLoggingIntegration:
    def test_metadata_written_on_setup(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = _make_session(tmp_dir=tmp)
            meta_path = Path(tmp) / session.game_id / "metadata.json"
            assert meta_path.exists()
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            assert data["game_id"] == session.game_id
            assert data["num_players"] == 5

    def test_action_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = _make_session(tmp_dir=tmp)
            status = session.get_status()
            president = status["pending_action"]["required_by"]
            targets = status["pending_action"]["legal_targets"]
            session.submit_action(president, "nominate", {"target_id": targets[0]})
            events_path = Path(tmp) / session.game_id / "events.jsonl"
            assert events_path.exists()
            lines = events_path.read_text(encoding="utf-8").strip().split("\n")
            events = [json.loads(line) for line in lines]
            action_events = [e for e in events if e["type"] == "action"]
            assert len(action_events) >= 1
            assert action_events[0]["action_type"] == "nominate"
