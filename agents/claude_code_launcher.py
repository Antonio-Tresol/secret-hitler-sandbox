"""Backward-compatible re-exports. Import from agents.backends instead."""

from agents.backends import (  # noqa: F401
    ClaudeCodeSession as PlayerSession,
    InvocationResult,
    build_mcp_config,
    build_system_prompt,
)
