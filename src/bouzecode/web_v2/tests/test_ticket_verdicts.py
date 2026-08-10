# [desc] Le verdict d'une validation doit être trouvé même si le dernier message assistant est vide de sens. [/desc]
"""Bug prod 2026-06-10 : l'agent de validation émet 'VERDICT: OK' puis un dernier
tour d'enforcement dont le contenu est juste '.' — le parseur ne lisait que le
dernier message assistant et le verdict restait null pour toujours."""
import json

from bouzecode.web_v2.runtime.runner import Agent
from bouzecode.web_v2.services.work.tickets import _find_verdict, _run_carries_verdict


def _agent(tmp_path, messages):
    session = tmp_path / "agent.session.json"
    session.write_text(json.dumps({"messages": messages}), encoding="utf-8")
    return Agent(agent_id="t", prompt="", model="", cwd="", pid=0,
                 started_at="", session_path=str(session))


def test_verdict_dans_message_anterieur_au_dernier(tmp_path):
    messages = [
        {"role": "assistant", "content": "55 passed, 2 skipped\nVERDICT: OK"},
        {"role": "user", "content": "enforcement"},
        {"role": "assistant", "content": "."},
    ]
    assert _find_verdict(_agent(tmp_path, messages)) == "OK"


def test_verdict_ko_dernier_message(tmp_path):
    messages = [{"role": "assistant", "content": "2 failed\nVERDICT: KO"}]
    assert _find_verdict(_agent(tmp_path, messages)) == "KO"


def test_pas_de_verdict(tmp_path):
    messages = [{"role": "assistant", "content": "tests verts mais ligne oubliée"}]
    assert _find_verdict(_agent(tmp_path, messages)) is None


def test_le_plus_recent_gagne(tmp_path):
    messages = [
        {"role": "assistant", "content": "VERDICT: KO"},
        {"role": "assistant", "content": "correction relue\nVERDICT: OK"},
    ]
    assert _find_verdict(_agent(tmp_path, messages)) == "OK"


def test_run_review_porte_un_verdict():
    """Bug 2026-06-18 : un run de review (kind=work, typologie review) termine par
    VERDICT mais ne le voyait jamais parser (seuls les kind=validate* l'etaient),
    laissant le verdict vide et les monitors tourner dans le vide."""
    assert _run_carries_verdict({"kind": "work", "typology": "review", "verdict": None})
    assert _run_carries_verdict({"kind": "validate_tests", "typology": "", "verdict": None})
    # run de dev classique : pas de typologie verdict -> on ne tail-lit pas sa session
    assert not _run_carries_verdict({"kind": "work", "typology": "feature", "verdict": None})
    assert not _run_carries_verdict({"kind": "work", "verdict": None})
    # deja parse -> ne repasse pas
    assert not _run_carries_verdict({"kind": "work", "typology": "review", "verdict": "OK"})
