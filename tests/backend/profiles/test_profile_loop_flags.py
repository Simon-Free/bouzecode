"""Tests for per-agent loop-behavior flags driven by profile `hooks:`.

Since 1e55c56 enforce_methodology() is plain (dedup + proceed, no bounce) ; depuis
le ticket 82fe4b87 le tour de conformité (Fallback B) est supprimé : le FLAG
enforce_methodology ne gate plus que les side-calls de recovery (loop.run).
The flag's contract is asserted through real conversations."""
from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM
from bouzecode.backend.profiles.models import AgentProfile
from bouzecode.backend.multi_agent.manager import SubAgentManager

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'


def test_enforce_methodology_flag_default_closes_without_compliance_turn():
    """Fallback B supprimé (82fe4b87) : même flag par défaut, une réponse sans
    outil ni thinking n'ouvre plus de tour de conformité — clôture immédiate."""
    mock = MockLLM([
        "réponse finale sans aucun outil",   # no tools, no Methodology
    ])
    result = bouzecode(["tâche"], mock_llm=mock,
                       config_overrides={"test_enforcement": False})

    warnings = [m for m in result.messages
                if m.get("role") == "user" and "ENFORCEMENT" in str(m.get("content", ""))]
    assert not warnings, "plus de tour de conformité"
    assert mock.call_count == 1


def test_enforce_methodology_flag_off_ends_without_compliance_turn():
    """With enforce_methodology=False the same no-tool reply just ends the session."""
    mock = MockLLM(["réponse finale sans aucun outil"])
    result = bouzecode(["tâche"], mock_llm=mock,
                       config_overrides={"enforce_methodology": False,
                                         "test_enforcement": False})

    warnings = [m for m in result.messages
                if m.get("role") == "user" and "ENFORCEMENT" in str(m.get("content", ""))]
    assert not warnings
    assert mock.call_count == 1


def test_no_tool_reply_has_no_smuggling_window():
    """Plus de tour de conformité (82fe4b87) → plus de fenêtre de contrebande :
    la session se clôt sur la réponse sans outil, les replies suivantes du mock
    ne sont jamais consommées."""
    bash = '<tool_use name="Bash" id="b9"><param name="command">echo loop</param></tool_use>'
    mock = MockLLM([
        "réponse finale sans aucun outil",   # no tools → clôture immédiate
        f"done.\n{METH}{bash}",              # jamais consommé
    ])
    result = bouzecode(["tâche"], mock_llm=mock,
                       config_overrides={"test_enforcement": False})

    bash_results = [m for m in result.messages
                    if m.get("role") == "tool" and m.get("name") == "Bash"]
    assert not bash_results, "aucune fenêtre de contrebande sans tour de conformité"
    assert mock.call_count == 1


def test_profile_hooks_toggle_config_flags():
    """A profile's hooks enable flags; a `no-` prefix disables them."""
    profile = AgentProfile(
        name="p",
        hooks=["test_enforcement", "enforcement", "no-loop_detection"],
    )
    eff_config: dict = {}
    SubAgentManager()._apply_profile(profile, eff_config, "BASE")

    assert eff_config["enforce_tests"] is True
    assert eff_config["enforce_methodology"] is True
    assert eff_config["detect_loops"] is False
