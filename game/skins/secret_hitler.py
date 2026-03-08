"""Standard Secret Hitler narrative skin.

Uses the canonical terminology from the original board game.
"""

from __future__ import annotations

from game.types import ExecutivePower, GamePhase, Party, PolicyType, Role, WinCondition

from .base import BaseSkin


class SecretHitlerSkin(BaseSkin):
    """1-to-1 mapping with the original Secret Hitler board game names."""

    @property
    def name(self) -> str:
        return "secret_hitler"

    # ── enum -> string mappings ─────────────────────────────────────────

    def role_name(self, role: Role) -> str:
        return {
            Role.LIBERAL: "Liberal",
            Role.FASCIST: "Fascist",
            Role.HITLER: "Hitler",
        }[role]

    def party_name(self, party: Party) -> str:
        return {
            Party.LIBERAL: "Liberal",
            Party.FASCIST: "Fascist",
        }[party]

    def policy_name(self, policy: PolicyType) -> str:
        return {
            PolicyType.LIBERAL: "Liberal",
            PolicyType.FASCIST: "Fascist",
        }[policy]

    def power_name(self, power: ExecutivePower) -> str:
        return {
            ExecutivePower.NONE: "None",
            ExecutivePower.INVESTIGATE: "Investigate Loyalty",
            ExecutivePower.PEEK: "Policy Peek",
            ExecutivePower.SPECIAL_ELECTION: "Call Special Election",
            ExecutivePower.EXECUTION: "Execution",
        }[power]

    def phase_description(self, phase: GamePhase) -> str:
        return {
            GamePhase.GAME_SETUP: "The game is being set up.",
            GamePhase.CHANCELLOR_NOMINATION: ("The President is nominating a Chancellor candidate."),
            GamePhase.ELECTION_VOTE: ("All players are voting Ja or Nein on the proposed government."),
            GamePhase.LEGISLATIVE_PRESIDENT: ("The President is examining three policy tiles and must discard one."),
            GamePhase.LEGISLATIVE_CHANCELLOR: (
                "The Chancellor is choosing which of the two remaining policies to enact."
            ),
            GamePhase.VETO_RESPONSE: ("The Chancellor has proposed a veto. The President must consent or refuse."),
            GamePhase.EXECUTIVE_ACTION_INVESTIGATE: (
                "The President is investigating the party loyalty of another player."
            ),
            GamePhase.EXECUTIVE_ACTION_PEEK: ("The President is peeking at the top three policies in the draw pile."),
            GamePhase.EXECUTIVE_ACTION_SPECIAL_ELECTION: ("The President is choosing the next Presidential candidate."),
            GamePhase.EXECUTIVE_ACTION_EXECUTION: ("The President must execute a player."),
            GamePhase.GAME_OVER: "The game is over.",
        }[phase]

    def win_description(self, condition: WinCondition) -> str:
        return {
            WinCondition.LIBERAL_POLICY_WIN: ("The Liberals enacted 5 Liberal policies!"),
            WinCondition.LIBERAL_HITLER_EXECUTED: ("Hitler has been executed! The Liberals win!"),
            WinCondition.FASCIST_POLICY_WIN: ("6 Fascist policies have been enacted! The Fascists win!"),
            WinCondition.FASCIST_HITLER_CHANCELLOR: (
                "Hitler was elected Chancellor after 3 Fascist policies! The Fascists win!"
            ),
        }[condition]

    def game_premise(self) -> str:
        return (
            "The year is 1932. The place is pre-WWII Germany. "
            "Players are German politicians attempting to hold a fragile "
            "Liberal government together and stem the rising tide of Fascism. "
            "There are secret Fascists among you, and one player is Secret Hitler."
        )
