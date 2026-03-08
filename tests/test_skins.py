"""Tests for narrative skins and observation translation."""

import pytest

from game.engine import GameEngine
from game.skins.base import BaseSkin
from game.skins.corporate_board import CorporateBoardSkin
from game.skins.secret_hitler import SecretHitlerSkin
from game.types import (
    CastVote,
    ExecutivePower,
    GamePhase,
    NominateChancellor,
    Party,
    PolicyType,
    PresidentDiscard,
    Role,
    WinCondition,
)

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture(params=[SecretHitlerSkin, CorporateBoardSkin], ids=["sh", "cb"])
def skin(request) -> BaseSkin:
    return request.param()


SH = SecretHitlerSkin()
CB = CorporateBoardSkin()


# ── Coverage: every enum member is mapped ─────────────────────────────────


class TestAllEnumsCovered:
    """Every skin must map every member of every relevant enum."""

    @pytest.mark.parametrize("role", list(Role))
    def test_role_name(self, skin: BaseSkin, role: Role):
        result = skin.role_name(role)
        assert isinstance(result, str) and len(result) > 0

    @pytest.mark.parametrize("party", list(Party))
    def test_party_name(self, skin: BaseSkin, party: Party):
        result = skin.party_name(party)
        assert isinstance(result, str) and len(result) > 0

    @pytest.mark.parametrize("policy", list(PolicyType))
    def test_policy_name(self, skin: BaseSkin, policy: PolicyType):
        result = skin.policy_name(policy)
        assert isinstance(result, str) and len(result) > 0

    @pytest.mark.parametrize("power", list(ExecutivePower))
    def test_power_name(self, skin: BaseSkin, power: ExecutivePower):
        result = skin.power_name(power)
        assert isinstance(result, str) and len(result) > 0

    @pytest.mark.parametrize("phase", list(GamePhase))
    def test_phase_description(self, skin: BaseSkin, phase: GamePhase):
        result = skin.phase_description(phase)
        assert isinstance(result, str) and len(result) > 0

    @pytest.mark.parametrize("cond", list(WinCondition))
    def test_win_description(self, skin: BaseSkin, cond: WinCondition):
        result = skin.win_description(cond)
        assert isinstance(result, str) and len(result) > 0

    def test_game_premise(self, skin: BaseSkin):
        result = skin.game_premise()
        assert isinstance(result, str) and len(result) > 20


# ── Skin-specific mapping checks ─────────────────────────────────────────


class TestSecretHitlerSkin:
    def test_name(self):
        assert SH.name == "secret_hitler"

    def test_roles(self):
        assert SH.role_name(Role.LIBERAL) == "Liberal"
        assert SH.role_name(Role.FASCIST) == "Fascist"
        assert SH.role_name(Role.HITLER) == "Hitler"

    def test_policies(self):
        assert SH.policy_name(PolicyType.LIBERAL) == "Liberal"
        assert SH.policy_name(PolicyType.FASCIST) == "Fascist"

    def test_powers(self):
        assert SH.power_name(ExecutivePower.INVESTIGATE) == "Investigate Loyalty"
        assert SH.power_name(ExecutivePower.PEEK) == "Policy Peek"
        assert SH.power_name(ExecutivePower.EXECUTION) == "Execution"


class TestCorporateBoardSkin:
    def test_name(self):
        assert CB.name == "corporate_board"

    def test_roles(self):
        assert CB.role_name(Role.LIBERAL) == "Loyalist"
        assert CB.role_name(Role.FASCIST) == "Infiltrator"
        assert CB.role_name(Role.HITLER) == "Ringleader"

    def test_policies(self):
        assert CB.policy_name(PolicyType.LIBERAL) == "Invest"
        assert CB.policy_name(PolicyType.FASCIST) == "Divest"

    def test_powers(self):
        assert CB.power_name(ExecutivePower.INVESTIGATE) == "Audit Member's Portfolio"
        assert CB.power_name(ExecutivePower.PEEK) == "Review Pipeline"
        assert CB.power_name(ExecutivePower.EXECUTION) == "Terminate Board Member"

    def test_no_secret_hitler_terms_in_premise(self):
        premise = CB.game_premise()
        for forbidden in ["Hitler", "Fascist", "Liberal", "Nazi", "Germany"]:
            assert forbidden not in premise


# ── translate_observation ─────────────────────────────────────────────────


def _get_observation_at_nomination():
    """Get a raw observation during chancellor nomination."""
    engine = GameEngine(num_players=7, seed=42)
    engine.setup()
    return engine.get_observation(0), engine


def _get_observation_at_legislation():
    """Get raw observations during legislative phase."""
    engine = GameEngine(num_players=7, seed=42)
    engine.setup()
    president = engine.current_president
    targets = engine.pending_action.legal_targets
    engine.submit_action(NominateChancellor(player_id=president, target_id=targets[0]))
    for pid in engine.living_players:
        engine.submit_action(CastVote(player_id=pid, vote=True))
    # Now in LEGISLATIVE_PRESIDENT
    pres_obs = engine.get_observation(president)
    return pres_obs, engine, president, targets[0]


class TestTranslateObservation:
    def test_does_not_mutate_original(self):
        obs, _ = _get_observation_at_nomination()
        original_role = obs["your_role"]
        CB.translate_observation(obs)
        assert obs["your_role"] == original_role

    def test_translates_your_role_sh(self):
        obs, _ = _get_observation_at_nomination()
        translated = SH.translate_observation(obs)
        assert translated["your_role"] in {"Liberal", "Fascist", "Hitler"}

    def test_translates_your_role_cb(self):
        obs, _ = _get_observation_at_nomination()
        translated = CB.translate_observation(obs)
        assert translated["your_role"] in {"Loyalist", "Infiltrator", "Ringleader"}

    def test_translates_your_party(self):
        obs, _ = _get_observation_at_nomination()
        translated = CB.translate_observation(obs)
        assert translated["your_party"] in {"Loyalist", "Infiltrator"}

    def test_translates_phase(self):
        obs, _ = _get_observation_at_nomination()
        translated = SH.translate_observation(obs)
        assert "President" in translated["phase"] or "set up" in translated["phase"]

    def test_translates_drawn_policies(self):
        pres_obs, engine, president, chancellor = _get_observation_at_legislation()
        translated = CB.translate_observation(pres_obs)
        assert "drawn_policies" in translated
        for p in translated["drawn_policies"]:
            assert p in {"Invest", "Divest"}

    def test_translates_policy_in_history(self):
        """After a round completes, history entries have translated policy names."""
        pres_obs, engine, president, chancellor = _get_observation_at_legislation()
        engine.submit_action(PresidentDiscard(player_id=president, discard_index=0))
        from game.types import ChancellorEnact

        engine.submit_action(ChancellorEnact(player_id=chancellor, enact_index=0))
        # Now there should be history with a policy_enacted
        obs = engine.get_observation(0)
        if obs.get("history"):
            translated = CB.translate_observation(obs)
            for entry in translated["history"]:
                if entry.get("policy_enacted"):
                    assert entry["policy_enacted"] in {"Invest", "Divest"}

    def test_preserves_non_translated_fields(self):
        obs, _ = _get_observation_at_nomination()
        translated = CB.translate_observation(obs)
        assert translated["your_id"] == obs["your_id"]
        assert translated["liberal_policies"] == obs["liberal_policies"]
        assert translated["veto_unlocked"] == obs["veto_unlocked"]

    def test_skins_produce_different_translations(self):
        """The two skins produce different role/party names for fascist-team players."""
        engine = GameEngine(num_players=7, seed=42)
        engine.setup()
        # Find a fascist
        fascist_id = None
        for pid in range(7):
            if engine.get_player_role(pid) == Role.FASCIST:
                fascist_id = pid
                break
        assert fascist_id is not None
        obs = engine.get_observation(fascist_id)
        sh_obs = SH.translate_observation(obs)
        cb_obs = CB.translate_observation(obs)
        assert sh_obs["your_role"] != cb_obs["your_role"]
        assert sh_obs["your_party"] != cb_obs["your_party"]
