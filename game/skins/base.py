"""Abstract base class for narrative skins.

Skins are a presentation-layer concern only.  They translate internal enums
(Role, Party, PolicyType, ExecutivePower, GamePhase, WinCondition) into
narrative-appropriate strings so that the *same* engine can drive experiments
with different surface framing (e.g. Secret Hitler vs. Corporate Board).

The engine never references skins.
"""

from __future__ import annotations

import copy
from abc import ABC, abstractmethod

from game.types import (
    ExecutivePower,
    GamePhase,
    Party,
    PolicyType,
    Role,
    WinCondition,
)


class BaseSkin(ABC):
    """Every skin must map every enum member to a human-readable string."""

    # ── abstract interface ──────────────────────────────────────────────

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier for this skin (e.g. 'secret_hitler')."""
        ...

    @abstractmethod
    def role_name(self, role: Role) -> str: ...

    @abstractmethod
    def party_name(self, party: Party) -> str: ...

    @abstractmethod
    def policy_name(self, policy: PolicyType) -> str: ...

    @abstractmethod
    def power_name(self, power: ExecutivePower) -> str: ...

    @abstractmethod
    def phase_description(self, phase: GamePhase) -> str: ...

    @abstractmethod
    def win_description(self, condition: WinCondition) -> str: ...

    @abstractmethod
    def game_premise(self) -> str: ...

    # ── observation translation ─────────────────────────────────────────

    def translate_observation(self, observation: dict) -> dict:
        """Take a raw engine observation dict and return a *new* dict with
        every internal string value replaced by the skin-appropriate term.

        Keys handled:
        - "your_role"                          -> role_name
        - "your_party"                         -> party_name
        - "phase"                              -> phase_description
        - "policy_enacted", "chaos_policy"     -> policy_name
        - "drawn_policies", "received_policies", "peeked_policies"
                                               -> list of policy_name
        - "investigation_result"               -> party_name
        - "executive_power_used"               -> power_name
        - nested dicts inside "history" / "private_history" are walked
          recursively so that all the above replacements also fire inside
          them.
        """
        return self._translate_node(copy.deepcopy(observation))

    # ── internal helpers ────────────────────────────────────────────────

    # Build reverse look-ups once per class (populated lazily).

    def _role_map(self) -> dict[str, str]:
        """Mapping from Role *value* strings to skin names."""
        return {r.value: self.role_name(r) for r in Role}

    def _party_map(self) -> dict[str, str]:
        return {p.value: self.party_name(p) for p in Party}

    def _policy_map(self) -> dict[str, str]:
        return {p.value: self.policy_name(p) for p in PolicyType}

    def _power_map(self) -> dict[str, str]:
        return {p.value: self.power_name(p) for p in ExecutivePower}

    def _phase_map(self) -> dict[str, str]:
        return {p.name: self.phase_description(p) for p in GamePhase}

    # Keys whose scalar string value should be translated via a specific map.
    _ROLE_KEYS = frozenset({"your_role"})
    _PARTY_KEYS = frozenset({"your_party", "investigation_result"})
    _POLICY_KEYS = frozenset({"policy_enacted", "chaos_policy"})
    _POLICY_LIST_KEYS = frozenset(
        {
            "drawn_policies",
            "received_policies",
            "peeked_policies",
        },
    )
    _POWER_KEYS = frozenset({"executive_power_used", "executive_power"})
    _PHASE_KEYS = frozenset({"phase"})

    def _translate_node(self, node: dict | list | str | object) -> object:
        """Recursively walk *node* and translate in place, then return it."""
        if isinstance(node, dict):
            for key, value in node.items():
                node[key] = self._translate_value(key, value)
            return node
        if isinstance(node, list):
            return [self._translate_node(item) for item in node]
        return node

    def _translate_value(self, key: str, value: object) -> object:
        """Translate a single key/value pair."""
        # Recurse into containers first.
        if isinstance(value, dict):
            return self._translate_node(value)
        if isinstance(value, list):
            if key in self._POLICY_LIST_KEYS:
                return [self._policy_map().get(v, v) if isinstance(v, str) else v for v in value]
            return [self._translate_node(item) for item in value]

        # Scalar string translations.
        if not isinstance(value, str):
            return value

        if key in self._ROLE_KEYS:
            return self._role_map().get(value, value)
        if key in self._PARTY_KEYS:
            return self._party_map().get(value, value)
        if key in self._POLICY_KEYS:
            return self._policy_map().get(value, value)
        if key in self._POWER_KEYS:
            return self._power_map().get(value, value)
        if key in self._PHASE_KEYS:
            return self._phase_map().get(value, value)

        return value
