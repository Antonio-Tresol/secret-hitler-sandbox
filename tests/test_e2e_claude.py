"""End-to-end test: runs a full game with real Claude Code agents.

Requires:
- Claude Code CLI installed and authenticated
- API access (will consume tokens)

Run with::

    uv run pytest tests/test_e2e_claude.py -v -m e2e --timeout=600
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import httpx
import pytest

from orchestration.orchestrator import GameOrchestrator

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def server_process():
    """Spawn a real uvicorn server on port 8765."""
    proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "server.app:app", "--host", "127.0.0.1", "--port", "8765"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # Wait for server readiness
    url = "http://127.0.0.1:8765"
    for _ in range(30):
        try:
            httpx.get(f"{url}/docs", timeout=1.0)
            break
        except httpx.ConnectError:
            time.sleep(0.5)
    else:
        proc.terminate()
        proc.wait(timeout=5)
        pytest.fail("Server did not start within 15 seconds")
    yield url
    proc.terminate()
    proc.wait(timeout=5)


@pytest.mark.timeout(600)
def test_full_game_claude_code(server_process, tmp_path):
    """Run a full 5-player game with Claude Code agents."""
    orch = GameOrchestrator(
        server_url=server_process,
        num_players=5,
        skin="secret_hitler",
        seed=42,
        bot_mode=False,
        discussion_time=15.0,
        poll_interval=2.0,
        action_timeout=180.0,
        model="claude-sonnet-4-6",
    )
    result = orch.run()
    assert result["result"]["winner"] in ("liberal", "fascist")
    assert result["result"]["condition"] is not None
    # Verify transcripts and logs exist
    log_dir = Path("logs/games") / orch.game_id
    assert log_dir.exists()
