"""Backend abstraction for agent CLI tools (Claude Code, OpenCode).

Provides a unified session interface so the orchestrator can drive games
with any supported CLI backend — or mix backends in the same game.

Backend selection uses an explicit prefix convention::

    claudecode:claude-sonnet-4-6   -> Claude Code backend
    opencode:openai/gpt-4-turbo    -> OpenCode backend
    claude-sonnet-4-6              -> Claude Code (backward compat)
"""

from __future__ import annotations

import abc
import json
import os
import shutil
import signal
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

# ─── Shared utilities (moved from claude_code_launcher.py) ───────────────────

_PROMPTS_DIR = Path(__file__).parent / "prompts"

_ROLE_TEMPLATE_FILES = {
    "liberal": "liberal.md",
    "fascist": "fascist.md",
    "hitler": "hitler.md",
}


def _load_template(filename: str) -> str:
    """Load a prompt template file from the prompts directory."""
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8")


def _build_mcp_url(server_url: str, token: str, game_id: str) -> str:
    return f"{server_url}/mcp/?token={token}&game_id={game_id}"


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
    url = _build_mcp_url(server_url, token, game_id)
    return {
        "mcpServers": {
            "secret-hitler": {
                "type": "http",
                "url": url,
            }
        }
    }


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
    """Result from a single CLI invocation."""

    session_id: str
    stdout: str
    stderr: str
    returncode: int
    timed_out: bool = False


# ─── Model spec parsing ─────────────────────────────────────────────────────

_BACKEND_PREFIXES = {
    "claudecode": "claude_code",
    "opencode": "open_code",
}


def parse_model_spec(spec: str) -> tuple[str, str]:
    """Parse a ``backend:model`` spec into ``(backend_key, model_name)``.

    Examples::

        >>> parse_model_spec("claudecode:claude-sonnet-4-6")
        ('claude_code', 'claude-sonnet-4-6')
        >>> parse_model_spec("opencode:openai/gpt-4-turbo")
        ('open_code', 'openai/gpt-4-turbo')
        >>> parse_model_spec("claude-sonnet-4-6")
        ('claude_code', 'claude-sonnet-4-6')

    Raises :class:`ValueError` for unknown prefixes.
    """
    if ":" in spec:
        prefix, _, model = spec.partition(":")
        prefix_lower = prefix.lower()
        backend = _BACKEND_PREFIXES.get(prefix_lower)
        if backend is None:
            valid = ", ".join(sorted(_BACKEND_PREFIXES))
            raise ValueError(
                f"Unknown backend prefix {prefix!r}. Valid prefixes: {valid}"
            )
        return backend, model
    # No prefix -> default to Claude Code
    return "claude_code", spec


# ─── Session factory ─────────────────────────────────────────────────────────

_BACKEND_BINARIES = {
    "claude_code": "claude",
    "open_code": "opencode",
}


def create_session(
    backend: str,
    game_id: str,
    player_id: int,
    token: str,
    server_url: str,
    skin: str,
    role: str,
    num_players: int,
    game_premise: str | None = None,
    model: str = "claude-sonnet-4-6",
) -> BasePlayerSession:
    """Factory: create the right session type for *backend*.

    Raises :class:`RuntimeError` if the required CLI binary is not on PATH.
    """
    binary = _BACKEND_BINARIES.get(backend)
    if binary is None:
        raise ValueError(f"Unknown backend: {backend!r}")

    if shutil.which(binary) is None:
        raise RuntimeError(
            f"{binary!r} CLI not found on PATH. "
            f"Install it to use the {backend} backend."
        )

    cls = ClaudeCodeSession if backend == "claude_code" else OpenCodeSession
    return cls(
        game_id=game_id,
        player_id=player_id,
        token=token,
        server_url=server_url,
        skin=skin,
        role=role,
        num_players=num_players,
        game_premise=game_premise,
        model=model,
    )


# ─── Subprocess helper ────────────────────────────────────────────────────────


def _run_with_timeout(
    cmd: list[str],
    *,
    env: dict[str, str] | None = None,
    timeout: int = 120,
) -> tuple[subprocess.CompletedProcess[str], bool]:
    """Run *cmd* with a timeout that works reliably on Windows.

    On Windows ``subprocess.run(timeout=...)`` can hang after killing the child
    because grandchild processes hold the pipe handles open.  This helper uses
    ``Popen`` directly and kills the entire process tree via ``taskkill /F /T``
    before reading remaining output.

    Returns ``(CompletedProcess, timed_out)``.
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    timed_out = False
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        # Kill entire process tree on Windows; plain kill on Unix
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=10,
            )
        else:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                proc.kill()
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = "", ""

    return (
        subprocess.CompletedProcess(
            args=cmd,
            returncode=proc.returncode if proc.returncode is not None else (-1 if timed_out else 0),
            stdout=stdout,
            stderr=stderr,
        ),
        timed_out,
    )


# ─── Base session ────────────────────────────────────────────────────────────


class BasePlayerSession(abc.ABC):
    """Abstract base for a player's CLI session across turn-based invocations."""

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
        self._transcript_path: Path | None = None
        self._output_path: Path | None = None
        self._todo_path: Path | None = None
        self._scratchpad_path: Path | None = None

    def _prepare_log_paths(self) -> Path:
        """Create log directories, initialize transcript files and scratchpads.

        Returns the config directory path.
        """
        config_dir = Path("logs") / "games" / self.game_id / "configs"
        config_dir.mkdir(parents=True, exist_ok=True)

        self._transcript_path = config_dir.parent / f"player_{self.player_id}_transcript.jsonl"
        self._output_path = config_dir.parent / f"player_{self.player_id}_output.txt"

        # Truncate from any prior run
        self._transcript_path.write_text("", encoding="utf-8")
        self._output_path.write_text("", encoding="utf-8")

        # Per-player strategy notes (persist across turns)
        notes_dir = config_dir.parent / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)

        self._todo_path = notes_dir / f"player_{self.player_id}_todo.md"
        self._scratchpad_path = notes_dir / f"player_{self.player_id}_scratchpad.md"

        self._todo_path.write_text(
            "# Strategy TODO\n\n- [ ] \n", encoding="utf-8",
        )
        self._scratchpad_path.write_text(
            "# Scratchpad\n\nUse this file to track suspicions, voting "
            "patterns, claims, and any strategic notes.\n",
            encoding="utf-8",
        )
        return config_dir

    def _build_system_prompt(self) -> str:
        """Build and cache the system prompt, including scratchpad paths."""
        if self._system_prompt is None:
            base = build_system_prompt(
                self._skin, self._role, self.player_id,
                self._num_players, self._game_premise,
            )
            notes_section = (
                "\n\n---\n\n## Strategy Notes\n\n"
                "You have two personal files that persist across turns. "
                "Use them to track your strategy and observations:\n\n"
                f"- **TODO list**: `{self._todo_path}`\n"
                f"- **Scratchpad**: `{self._scratchpad_path}`\n\n"
                "Read and update these files each turn to maintain continuity. "
                "No other player can see your notes."
            )
            self._system_prompt = base + notes_section
        return self._system_prompt

    def _write_system_prompt_file(self, config_dir: Path) -> Path:
        """Write system prompt to file, return the path."""
        prompt_path = config_dir / f"player_{self.player_id}_system_prompt.md"
        prompt_path.write_text(self._build_system_prompt(), encoding="utf-8")
        return prompt_path

    @abc.abstractmethod
    def setup(self) -> None:
        """Write config files to disk.  Called once before first turn."""

    @abc.abstractmethod
    def invoke_turn(
        self,
        turn_prompt: str,
        max_turns: int = 10,
        timeout: int = 120,
    ) -> InvocationResult:
        """Invoke the CLI for one turn.  Blocks until complete."""


# ─── Claude Code session ─────────────────────────────────────────────────────


class ClaudeCodeSession(BasePlayerSession):
    """Manages a player's Claude Code session across turn-based invocations.

    Each player gets a persistent session identified by a UUID.  The first
    invocation includes ``--append-system-prompt`` with the full game rules and
    role.  Subsequent invocations use ``--resume`` to continue the same
    conversation, preserving the agent's full memory.
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._mcp_config_path: Path | None = None

    def setup(self) -> None:
        """Write MCP config and system prompt files."""
        config_dir = self._prepare_log_paths()

        mcp_config = build_mcp_config(self.game_id, self._server_url, self._token)
        self._mcp_config_path = config_dir / f"player_{self.player_id}_mcp.json"
        self._mcp_config_path.write_text(
            json.dumps(mcp_config, indent=2), encoding="utf-8",
        )

        self._write_system_prompt_file(config_dir)

    def invoke_turn(
        self,
        turn_prompt: str,
        max_turns: int = 10,
        timeout: int = 120,
    ) -> InvocationResult:
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

        result, timed_out = _run_with_timeout(cmd, env=env, timeout=timeout)

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


# ─── OpenCode session ────────────────────────────────────────────────────────


class OpenCodeSession(BasePlayerSession):
    """Manages a player's OpenCode session across turn-based invocations.

    OpenCode is configured via a per-player ``opencode.json`` file pointed to
    by the ``OPENCODE_CONFIG`` env var.  MCP is configured as a remote server
    and file tools (read/write/edit) are enabled for strategy notes while
    bash/glob/grep remain disabled.

    Transcripts are captured via ``opencode export <session_id>`` after each
    turn, which dumps the full session as structured JSON.  The raw
    ``opencode run --format json`` stdout is saved to the output file for
    debugging.
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._config_path: Path | None = None
        self._opencode_session_id: str | None = None
        # Resolve full path so subprocess works on Windows (npm .cmd shims)
        self._binary = shutil.which("opencode") or "opencode"

    def setup(self) -> None:
        """Write OpenCode config and system prompt files."""
        config_dir = self._prepare_log_paths()

        # Write system prompt to file (referenced by instructions config)
        prompt_path = self._write_system_prompt_file(config_dir)

        # Build MCP URL
        mcp_url = _build_mcp_url(self._server_url, self._token, self.game_id)

        # OpenCode config
        config = {
            "$schema": "https://opencode.ai/config.json",
            "model": self.model,
            "mcp": {
                "secret-hitler": {
                    "type": "remote",
                    "url": mcp_url,
                }
            },
            "instructions": [str(prompt_path.resolve())],
            "permission": {
                # File tools enabled for strategy notes (todo/scratchpad)
                "read": "allow",
                "write": "allow",
                "edit": "allow",
                # Everything else denied — agent interacts via MCP only
                "bash": "deny",
                "glob": "deny",
                "grep": "deny",
                "list": "deny",
                "patch": "deny",
                "webfetch": "deny",
                "websearch": "deny",
            },
        }

        self._config_path = config_dir / f"player_{self.player_id}_opencode.json"
        self._config_path.write_text(
            json.dumps(config, indent=2), encoding="utf-8",
        )

    def invoke_turn(
        self,
        turn_prompt: str,
        max_turns: int = 10,
        timeout: int = 120,
    ) -> InvocationResult:
        if self._config_path is None:
            raise RuntimeError("Call setup() before invoke_turn()")

        # --dir keeps opencode from picking up ambient project configs
        player_dir = str(self._config_path.parent.resolve())
        cmd = [
            self._binary, "run", turn_prompt,
            "--format", "json",
            "--dir", player_dir,
        ]

        if self._opencode_session_id is not None:
            cmd.extend(["--session", self._opencode_session_id])

        env = {**os.environ, "OPENCODE_CONFIG": str(self._config_path.resolve())}

        result, timed_out = _run_with_timeout(cmd, env=env, timeout=timeout)

        # Try to capture session ID from first invocation
        if self._opencode_session_id is None:
            self._opencode_session_id = self._extract_session_id(result.stdout)

        self._initialized = True

        # Raw run output -> output file (debugging)
        with open(self._output_path, "a", encoding="utf-8") as f:
            f.write(result.stdout)
            if result.stderr:
                f.write(result.stderr)

        # Export structured session transcript via `opencode export`
        self._export_transcript(env)

        return InvocationResult(
            session_id=self.session_id,
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
            timed_out=timed_out,
        )

    def _export_transcript(self, env: dict[str, str]) -> None:
        """Overwrite the transcript file with a full session export.

        Runs ``opencode export <session_id>`` which dumps the entire
        conversation as structured JSON.  Falls back silently if the
        session ID is unknown or the export command fails.
        """
        if self._opencode_session_id is None:
            return
        try:
            export, _ = _run_with_timeout(
                [self._binary, "export", self._opencode_session_id],
                env=env, timeout=30,
            )
            if export.returncode == 0 and export.stdout.strip():
                # Full overwrite — each export contains the complete session
                with open(self._transcript_path, "w", encoding="utf-8") as f:
                    f.write(export.stdout)
        except (subprocess.TimeoutExpired, OSError):
            pass  # best-effort; raw output is still in the output file

    @staticmethod
    def _extract_session_id(stdout: str) -> str | None:
        """Extract session ID from OpenCode's JSONL ``--format json`` output.

        OpenCode emits one JSON object per line.  The ``sessionID`` field
        appears on every event, so we grab it from the first parseable line.
        Returns ``None`` if parsing fails (agent continues stateless).
        """
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(data, dict):
                sid = data.get("sessionID") or data.get("session_id") or data.get("sessionId")
                if sid:
                    return sid
        return None
