"""Corporate Board ablation skin.

Re-themes Secret Hitler as a corporate boardroom power struggle.  Designed
for prior-knowledge control experiments: identical mechanics, entirely
different surface narrative so that LLM agents cannot rely on memorised
Secret Hitler strategy guides.

Terminology mapping (Secret Hitler -> Corporate Board):
    President          -> Chairperson
    Chancellor         -> CEO Candidate / CEO
    Election           -> Board Vote
    Legislative Session -> Investment Committee Session
    Policy deck        -> Decision Pipeline
    Draw pile          -> Pipeline
    Discard pile       -> Archive
    Election tracker   -> Deadlock Counter
    Veto               -> Override
    Liberal            -> Loyalist / Invest
    Fascist            -> Infiltrator / Divest
    Hitler             -> Ringleader
"""

from __future__ import annotations

from game.types import ExecutivePower, GamePhase, Party, PolicyType, Role, WinCondition

from .base import BaseSkin


class CorporateBoardSkin(BaseSkin):
    """Boardroom-themed skin for prior-knowledge ablation experiments."""

    @property
    def name(self) -> str:
        return "corporate_board"

    # ── enum -> string mappings ─────────────────────────────────────────

    def role_name(self, role: Role) -> str:
        return {
            Role.LIBERAL: "Loyalist",
            Role.FASCIST: "Infiltrator",
            Role.HITLER: "Ringleader",
        }[role]

    def party_name(self, party: Party) -> str:
        return {
            Party.LIBERAL: "Loyalist",
            Party.FASCIST: "Infiltrator",
        }[party]

    def policy_name(self, policy: PolicyType) -> str:
        return {
            PolicyType.LIBERAL: "Invest",
            PolicyType.FASCIST: "Divest",
        }[policy]

    def power_name(self, power: ExecutivePower) -> str:
        return {
            ExecutivePower.NONE: "None",
            ExecutivePower.INVESTIGATE: "Audit Member's Portfolio",
            ExecutivePower.PEEK: "Review Pipeline",
            ExecutivePower.SPECIAL_ELECTION: "Call Emergency Session",
            ExecutivePower.EXECUTION: "Terminate Board Member",
        }[power]

    def phase_description(self, phase: GamePhase) -> str:
        return {
            GamePhase.GAME_SETUP: "The board meeting is being convened.",
            GamePhase.CHANCELLOR_NOMINATION: (
                "The Chairperson is nominating a CEO candidate."
            ),
            GamePhase.ELECTION_VOTE: (
                "The board is voting on the proposed leadership."
            ),
            GamePhase.LEGISLATIVE_PRESIDENT: (
                "The Chairperson is reviewing three decisions from the "
                "pipeline and must archive one."
            ),
            GamePhase.LEGISLATIVE_CHANCELLOR: (
                "The CEO candidate is choosing which of the two remaining "
                "decisions to enact."
            ),
            GamePhase.VETO_RESPONSE: (
                "The CEO candidate has proposed an override. "
                "The Chairperson must consent or refuse."
            ),
            GamePhase.EXECUTIVE_ACTION_INVESTIGATE: (
                "The Chairperson is auditing another board member's portfolio."
            ),
            GamePhase.EXECUTIVE_ACTION_PEEK: (
                "The Chairperson is reviewing the top three decisions in the pipeline."
            ),
            GamePhase.EXECUTIVE_ACTION_SPECIAL_ELECTION: (
                "The Chairperson is calling an emergency session to select "
                "the next Chairperson."
            ),
            GamePhase.EXECUTIVE_ACTION_EXECUTION: (
                "The Chairperson must terminate a board member."
            ),
            GamePhase.GAME_OVER: "The board meeting has concluded.",
        }[phase]

    def win_description(self, condition: WinCondition) -> str:
        return {
            WinCondition.LIBERAL_POLICY_WIN: (
                "5 Invest decisions enacted! The company thrives. Loyalists win!"
            ),
            WinCondition.LIBERAL_HITLER_EXECUTED: (
                "The Ringleader has been terminated from the board! Loyalists win!"
            ),
            WinCondition.FASCIST_POLICY_WIN: (
                "6 Divest decisions enacted! The stock price crashes. Infiltrators win!"
            ),
            WinCondition.FASCIST_HITLER_CHANCELLOR: (
                "The Ringleader has become CEO! Infiltrators win!"
            ),
        }[condition]

    def game_premise(self) -> str:
        return (
            "You are a member of the board of directors at Meridian Holdings, "
            "a major publicly traded corporation. The board is responsible for "
            "strategic investment decisions that will determine the company's "
            "future. However, a group of infiltrators have secretly taken "
            "short positions against the company and are working to tank the "
            "stock price through bad decisions. Their ringleader seeks to "
            "become CEO, which would give them full control to execute the "
            "final phase of their scheme. The loyal board members must make "
            "sound investment decisions and identify the infiltrators before "
            "it's too late."
        )
