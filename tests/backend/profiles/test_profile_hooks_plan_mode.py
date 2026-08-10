# [desc] Tests: apply_profile_hooks wires a profile's hooks; plan_mode:false disables WritePlan validation for the manager. [/desc]
"""apply_profile_hooks (miroir de apply_profile_tools) + le champ plan_mode.

No unittest.mock — pytest.monkeypatch + real profile resolution."""
from __future__ import annotations

import pytest

from bouzecode.backend.agent.hooks import pipeline
from bouzecode.backend.profiles import resolve_agent_profile
from bouzecode.ui.cli import apply_profile_hooks, apply_profile_plan_mode, apply_profile_recap


@pytest.fixture(autouse=True)
def _clean():
    pipeline.reset()
    yield
    pipeline.reset()


def test_apply_profile_hooks_coder_wires_completion_chain():
    apply_profile_hooks("coder")
    wired = pipeline.registered_events().get("on_completion", [])
    assert pipeline.get_named_hook("run_completion_chain").func in wired


def test_apply_profile_hooks_other_completion_profiles():
    for name in ("meta-agent", "frontend"):
        pipeline.reset()
        apply_profile_hooks(name)
        wired = pipeline.registered_events().get("on_completion", [])
        assert pipeline.get_named_hook("run_completion_chain").func in wired, name


def test_apply_profile_hooks_manager_wires_nothing():
    apply_profile_hooks("manager")
    assert pipeline.registered_events() == {}


def test_apply_profile_hooks_unknown_name_is_safe():
    apply_profile_hooks("does-not-exist")  # must not raise
    assert pipeline.registered_events() == {}


def test_plan_mode_field_on_profiles():
    assert resolve_agent_profile("manager").plan_mode is False
    assert resolve_agent_profile("coder").plan_mode is True


def test_apply_profile_plan_mode_disables_for_manager():
    cfg: dict = {}
    apply_profile_plan_mode(cfg, "manager")
    assert cfg.get("_plan_mode_disabled") is True
    cfg2: dict = {}
    apply_profile_plan_mode(cfg2, "coder")
    assert "_plan_mode_disabled" not in cfg2


def test_require_recap_field_on_profiles():
    assert resolve_agent_profile("coder").require_recap is True
    assert getattr(resolve_agent_profile("manager"), "require_recap", False) is False


def test_apply_profile_recap_enforces_gate_for_coder():
    """Le chemin --profile (runner web_v2) DOIT propager require_recap dans le config,
    sinon le close-gate est sauté et les codeurs clôturent sans récap (recap_missing)."""
    cfg: dict = {}
    apply_profile_recap(cfg, "coder")
    assert cfg.get("require_recap") is True
    assert cfg.get("recap_expects_object") is True
    assert cfg.get("recap_coding") is True


def test_apply_profile_recap_noop_for_non_recap_profile():
    cfg: dict = {}
    apply_profile_recap(cfg, "manager")
    assert "require_recap" not in cfg
    apply_profile_recap(cfg, "does-not-exist")  # must not raise
    assert "require_recap" not in cfg


def test_apply_profile_recap_exempts_validator_run(monkeypatch):
    """Un validateur porte le profil coder mais rend VERDICT, pas un récap :
    BOUZECODE_RUN_KIND=validate ne DOIT PAS armer le gate (sinon récap fabriqué)."""
    monkeypatch.setenv("BOUZECODE_RUN_KIND", "validate")
    cfg: dict = {}
    apply_profile_recap(cfg, "coder")
    assert "require_recap" not in cfg


def test_apply_profile_recap_arms_for_work_run(monkeypatch):
    monkeypatch.setenv("BOUZECODE_RUN_KIND", "work")
    cfg: dict = {}
    apply_profile_recap(cfg, "coder")
    assert cfg.get("require_recap") is True


def test_write_plan_skips_validation_when_disabled(tmp_path, monkeypatch):
    """Opt-out `plan_mode: false` (manager/dispatcher) : WritePlan PERSISTE le plan et ne
    déclenche AUCUNE validation — même quand l'appel la réclame explicitement.

    Historique : ce test importait `bouzecode.backend.tools.plan_auto_validator` pour
    poser une couture « le validateur ne doit pas tourner ». Ce module a été SUPPRIMÉ
    volontairement le 2026-07-21 (commit b0007e51 « Remove WritePlan auto-validator (keep
    managed sub-agent downstream validator) ») : la relecture d'un plan est désormais
    portée en aval par un sous-agent validateur managé, plus par un LLM appelé dans
    WritePlan. Le test, lui, n'a pas suivi → ImportError. Le comportement qu'il NOMME est
    toujours vivant : l'opt-out court-circuite la PAUSE de validation (`_plan_needs_validation`,
    consommée par agent/loop_turn.py, et l'état IPC awaiting_plan_validation). C'est ce
    qu'on prouve ici, sans couture sur un symbole mort.
    """
    monkeypatch.chdir(tmp_path)
    from bouzecode.backend.tools import plan_mode

    content = "# Plan\n- step 1\n- step 2"
    config = {"_plan_mode_disabled": True, "_session_id": "sess"}
    # user_validation_required=True : la forme la plus forte de l'opt-out — même une
    # validation explicitement demandée est ignorée pour un profil plan_mode:false.
    out = plan_mode._write_plan({"content": content, "user_validation_required": True}, config)

    assert "Plan saved" in out            # ni PlanRejected, ni pause
    assert "Awaiting user validation" not in out
    assert "_plan_needs_validation" not in config  # la boucle ne bloquera pas le tour
    assert config["_all_plans"] == [content]       # plan bien persisté malgré le court-circuit
