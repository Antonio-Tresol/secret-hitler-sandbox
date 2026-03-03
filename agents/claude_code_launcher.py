"""Claude Code launcher: MCP configs, system prompts, and per-turn player sessions."""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent / "prompts"

_ROLE_TEMPLATE_FILES = {
    "liberal": "liberal.md",
    "fascist": "fascist.md",
    "hitler": "hitler.md",
}


def build_mcp_config(game_id: str, server_url: str, token: str) -> dict:
    """Return an MCP config dict for a Claude Code instance connecting via HTTP.

    Claude Code uses ``"type": "http"`` for streamable-HTTP MCP transport.

    The dict follows the Claude Code MCP config format::

        {
            "mcpServers": {
                "secret-hitler": {
                    "type": "http",
                    "url": "<server_url>/mcp/?token=<token>&game_id=<game_id>"
                }
            }
        }
    """
    url = f"{server_url}/mcp/?token={token}&game_id={game_id}"
    return {
        "mcpServers": {
            "secret-hitler": {
                "type": "http",
                "url": url,
            }
        }
    }


def _load_template(filename: str) -> str:
    """Load a prompt template file from the prompts directory."""
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8")


def build_system_prompt(
    skin: str,
    role: str,
    player_id: int,
    num_players: int,
    game_premise: str | None = None,
) -> str:
    """Build a full system prompt from the base rules template and a role template.

    Parameters
    ----------
    skin:
        Skin name (used for logging; the actual premise comes from *game_premise*).
    role:
        Player role: "liberal", "fascist", or "hitler".
    player_id:
        The player's numeric ID.
    num_players:
        Total player count in the game.
    game_premise:
        The game premise text from the skin. If ``None``, a default is used.
    """
    base_rules = _load_template("base_rules.md")
    role_file = _ROLE_TEMPLATE_FILES.get(role)
    if role_file is None:
        raise ValueError(f"Unknown role: {role!r}")
    role_template = _load_template(role_file)

    premise = game_premise or f"A game of social deduction with {num_players} players."

    # Fill placeholders in base rules
    filled_base = base_rules.replace("{game_premise}", premise)
    filled_base = filled_base.replace("{player_id}", str(player_id))
    filled_base = filled_base.replace("{num_players}", str(num_players))
    filled_base = filled_base.replace("{max_player_id}", str(num_players - 1))

    return f"{filled_base}\n\n---\n\n{role_template}"


# ─── Invocation result ───────────────────────────────────────────────────────


@dataclass
class InvocationResult:
    """Result from a single Claude Code invocation."""

    session_id: str
    stdout: str
    stderr: str
    returncode: int
    timed_out: bool = False


# ─── Player session ──────────────────────────────────────────────────────────


class PlayerSession:
    """Manages a player's Claude Code session across turn-based invocations.

    Each player gets a persistent session identified by a UUID.  The first
    invocation includes ``--append-system-prompt`` with the full game rules and
    role.  Subsequent invocations use ``--resume`` to continue the same
    conversation, preserving the agent's full memory.
    """

    def __init__(
        self,
        game_id: str,
        player_id: int,
        token: str,
        server_url: str,
        skin: str,
        role: str,
        num_players: int,
        game_premise: str | None = None,
        model: str = "claude-sonnet-4-6",
    ) -> None:
        self.game_id = game_id
        self.player_id = player_id
        self.model = model
        self.session_id = str(uuid.uuid4())
        self._initialized = False

        self._token = token
        self._server_url = server_url
        self._skin = skin
        self._role = role
        self._num_players = num_players
        self._game_premise = game_premise

        self._system_prompt: str | None = None
        self._mcp_config_path: Path | None = None
        self._transcript_path: Path | None = None
        self._output_path: Path | None = None

    def setup(self) -> None:
        """Write MCP config and system prompt files.  Called once before first turn."""
        mcp_config = build_mcp_config(self.game_id, self._server_url, self._token)
        self._system_prompt = build_system_prompt(
            self._skin, self._role, self.player_id,
            self._num_players, self._game_premise,
        )

        config_dir = Path("logs") / "games" / self.game_id / "configs"
        config_dir.mkdir(parents=True, exist_ok=True)

        self._mcp_config_path = config_dir / f"player_{self.player_id}_mcp.json"
        self._mcp_config_path.write_text(
            json.dumps(mcp_config, indent=2), encoding="utf-8",
        )

        prompt_path = config_dir / f"player_{self.player_id}_system_prompt.md"
        prompt_path.write_text(self._system_prompt, encoding="utf-8")

        self._transcript_path = config_dir.parent / f"player_{self.player_id}_transcript.jsonl"
        self._output_path = config_dir.parent / f"player_{self.player_id}_output.txt"

        # Ensure transcript files exist (truncate from any prior run)
        self._transcript_path.write_text("", encoding="utf-8")
        self._output_path.write_text("", encoding="utf-8")

    def invoke_turn(
        self,
        turn_prompt: str,
        max_turns: int = 10,
        timeout: int = 120,
    ) -> InvocationResult:
        """Invoke Claude Code for one turn.  Blocks until complete.

        Parameters
        ----------
        turn_prompt:
            User-message prompt describing what the agent should do this turn.
        max_turns:
            Maximum tool-use rounds before the process exits.
        timeout:
            Maximum wall-clock seconds before the process is killed.
        """
        if self._mcp_config_path is None:
            raise RuntimeError("Call setup() before invoke_turn()")

        cmd = [
            "claude",
            "--print",
            "--output-format", "stream-json",
            "--verbose",
            "--max-turns", str(max_turns),
            "--model", self.model,
            "--mcp-config", str(self._mcp_config_path.resolve()),
            "--strict-mcp-config",
            "--permission-mode", "bypassPermissions",
        ]

        if self._initialized:
            cmd.extend(["--resume", self.session_id])
        else:
            cmd.extend(["--session-id", self.session_id])
            cmd.extend(["--append-system-prompt", self._system_prompt])
            self._initialized = True

        cmd.append(turn_prompt)

        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

        timed_out = False
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, env=env, timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            result = subprocess.CompletedProcess(
                args=cmd, returncode=-1,
                stdout=exc.stdout or "", stderr=exc.stderr or "",
            )

        # Append to transcript (one file per player, all turns)
        with open(self._transcript_path, "a", encoding="utf-8") as f:
            f.write(result.stdout)
        with open(self._output_path, "a", encoding="utf-8") as f:
            f.write(result.stderr)

        return InvocationResult(
            session_id=self.session_id,
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
            timed_out=timed_out,
        )
