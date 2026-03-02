"""Shared test fixtures for the Secret Hitler sandbox test suite."""

from __future__ import annotations

import pytest

from game.engine import GameEngine
from server.app import get_sessions
from server.game_session import GameSession


@pytest.fixture(autouse=True)
def _clean_sessions():
    """Clear the in-memory session store before and after each test."""
    sessions = get_sessions()
    sessions.clear()
    yield
    sessions.clear()


@pytest.fixture
def engine_5p():
    """5-player GameEngine, setup complete, seed=42."""
    e = GameEngine(num_players=5, seed=42)
    e.setup()
    return e


@pytest.fixture
def engine_7p():
    """7-player GameEngine, setup complete, seed=42."""
    e = GameEngine(num_players=7, seed=42)
    e.setup()
    return e


@pytest.fixture
def session_5p(tmp_path):
    """5-player GameSession with temp log dir, setup complete."""
    s = GameSession(num_players=5, seed=42, log_base_dir=str(tmp_path))
    s.setup()
    return s
