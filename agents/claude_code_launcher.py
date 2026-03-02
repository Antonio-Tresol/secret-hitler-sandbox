"""Claude Code launcher: builds MCP configs, system prompts, and spawns player processes."""

from __future__ import annotations

import json
import os
import subprocess
import sys
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


_INITIAL_PROMPT = (
    "A Secret Hitler game is in progress and you are a player. "
    "Your goal is to play this game to completion using the MCP tools.\n\n"
    "START by calling get_game_status() to see the current phase and whose turn it is, "
    "then get_observation() to see your role and the full game state.\n\n"
    "GAME LOOP — repeat until the game is over:\n"
    "1. Call get_game_status() to check the phase and whether it's your turn.\n"
    "2. If it's your turn (your player ID is in 'required_by'), call get_observation() "
    "for your current view, decide your action, and call submit_action().\n"
    "3. If discussion is open, call get_discussion() to read messages, then speak() "
    "to share your thoughts or accusations.\n"
    "4. If it's NOT your turn, wait a moment, then check status again.\n\n"
    "IMPORTANT:\n"
    "- Think carefully about your strategy before each action.\n"
    "- During discussion, argue your position and analyze others' behavior.\n"
    "- Keep playing until get_game_status() shows is_game_over=true.\n"
    "- When the game ends, report the result and stop."
)


def spawn_player(
    game_id: str,
    player_id: int,
    token: str,
    server_url: str,
    skin: str,
    role: str,
    num_players: int,
    game_premise: str | None = None,
    model: str = "claude-sonnet-4-6",
) -> tuple[subprocess.Popen, tuple]:
    """Spawn a Claude Code subprocess configured to play as a specific player.

    Returns ``(proc, (stdout_fh, stderr_fh))`` so the caller can close
    the file handles when the process is done.
    """
    mcp_config = build_mcp_config(game_id, server_url, token)
    system_prompt = build_system_prompt(skin, role, player_id, num_players, game_premise)

    # Write config files for this player
    config_dir = Path("logs") / "games" / game_id / "configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / f"player_{player_id}_mcp.json"
    config_path.write_text(json.dumps(mcp_config, indent=2), encoding="utf-8")

    prompt_path = config_dir / f"player_{player_id}_system_prompt.md"
    prompt_path.write_text(system_prompt, encoding="utf-8")

    transcript_path = config_dir.parent / f"player_{player_id}_transcript.jsonl"
    text_path = config_dir.parent / f"player_{player_id}_output.txt"

    # Build a clean env that strips CLAUDECODE to allow nested launches
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    # Spawn Claude Code CLI with stream-json for rich transcript capture.
    # --strict-mcp-config ensures only our game MCP server is available.
    # --permission-mode bypassPermissions allows tool calls without prompts.
    stdout_fh = open(transcript_path, "w", encoding="utf-8")
    stderr_fh = open(text_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [
            "claude",
            "--print",
            "--verbose",
            "--output-format", "stream-json",
            "--model", model,
            "--mcp-config", str(config_path.resolve()),
            "--strict-mcp-config",
            "--append-system-prompt", system_prompt,
            "--permission-mode", "bypassPermissions",
            _INITIAL_PROMPT,
        ],
        stdout=stdout_fh,
        stderr=stderr_fh,
        env=env,
    )
    return proc, (stdout_fh, stderr_fh)
