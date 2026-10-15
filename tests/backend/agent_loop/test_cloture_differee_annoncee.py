# [desc] Clôture différée : la réponse dit que la vérification n'est pas faite, et son verdict la rejoint à l'arrivée. [/desc]
"""`final_answer_deferred` : livrée AVANT que la suite complète n'ait tourné.

Sessions a5536ec2 (23/09) et 3f364511 (25/09) : FinalAnswer + `Bash(deferred=true)` de
la suite complète web_v2 dans le même lot. La clôture est acceptée, le rapport livré
parle de tests verts… et la seule trace de la suite est « Suite complète web_v2 déférée
à la fermeture », glissée en fin de section. Côté web, le drain écrit la sortie dans le
stdout de l'agent et, vert, supprime le fichier : rien ne rejoint le rapport. Côté TUI,
`_persist_deferred_and_exit` quittait le REPL sans lancer la moindre vérification.
"""
from __future__ import annotations

import json
import time

import pytest

import tests.e2e_harness as harness
from bouzecode.backend.agent.state import AgentState
from bouzecode.backend.tools.interaction import DeferredChecks
from bouzecode.web_v2.runtime import deferred as web_deferred
from bouzecode.web_v2.runtime.runner import agent_fiche, agent_reprise
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
ANSWER = "Mails(message_id=...) rend le mail en entier. 13 passed."
FINAL = ('<tool_use name="FinalAnswer" id="f1">'
         f'<param name="answer">{ANSWER}</param>'
         '<param name="taches_terminees">[]</param>'
         '<param name="taches_restantes">[]</param></tool_use>')
SUITE = "uv run --no-sync pytest src/bouzecode/web_v2/tests -q"
DIFFEREE = ('<tool_use name="Bash" id="d1"><param name="command">' + SUITE + '</param>'
            '<param name="deferred">true</param><param name="timeout">900</param></tool_use>')


@pytest.fixture
def cloture_differee(monkeypatch):
    """Le lot réel de a5536ec2 (tour 17) : la suite mise en file ET la clôture."""
    state = AgentState()
    monkeypatch.setattr(harness, "AgentState", lambda: state)
    with pytest.raises(DeferredChecks) as exc:
        harness.bouzecode(["lis le mail en entier"],
                          mock_llm=MockLLM([f"{METH}\n{DIFFEREE}\n{FINAL}", "JAMAIS"]))
    return state, exc.value


def test_la_reponse_livree_dit_que_la_verification_n_est_pas_faite(cloture_differee):
    state, differe = cloture_differee
    assert state.close_reason == "final_answer_deferred"
    for livre in (state.final_answer, differe.answer):
        assert livre.startswith(ANSWER)
        assert "NON FAITE" in livre and SUITE in livre
    resultat_final = next(m for m in state.messages
                          if m.get("role") == "tool" and m.get("name") == "FinalAnswer")
    assert "NON FAITE" in resultat_final["content"], "la conversation affichée le dit aussi"


def test_la_file_est_remise_a_la_suite_qui_la_vide(cloture_differee):
    """Une seconde clôture de la même session ne relance pas les mêmes vérifications."""
    state, differe = cloture_differee
    assert [c["command"] for c in differe.checks] == [SUITE]
    assert state.context_state.deferred_queue == []


# --- Web : le drain consigne son verdict dans la session ---------------------------

def _agent_web(tmp_path, commande: str):
    session = tmp_path / "coder1.session.json"
    reponse = ANSWER + web_deferred_annonce([{"command": commande}])
    session.write_text(json.dumps({
        "close_reason": "final_answer_deferred", "final_answer": reponse,
        "messages": [{"role": "tool", "name": "FinalAnswer", "tool_call_id": "f1",
                      "content": "Session closing — final answer delivered:\n" + reponse}],
    }), encoding="utf-8")
    web_deferred.save(session, DeferredChecks(answer=reponse,
                                              checks=[{"command": commande, "timeout": 60}]))
    return agent_fiche.Agent(agent_id="coder1", prompt="p", model="m", cwd=str(tmp_path), pid=0,
                        started_at="", stdout_path=str(tmp_path / "out.log"),
                        session_path=str(session))


def web_deferred_annonce(checks):
    from bouzecode.backend.tools.interaction import annonce_verifications_differees
    return annonce_verifications_differees(checks)


def _session(agent):
    return json.loads(open(agent.session_path, encoding="utf-8").read())


def test_suite_differee_verte_consignee_dans_le_rapport(tmp_path):
    agent = _agent_web(tmp_path, "echo 812 passed")
    agent_reprise._maybe_drain_deferred(agent)

    data = _session(agent)
    assert data["deferred_result"]["statut"] == "vert"
    for texte in (data["final_answer"], data["messages"][-1]["content"]):
        assert texte.startswith(ANSWER) or ANSWER in texte
        assert "NON FAITE" not in texte
        assert "812 passed" in texte
    assert not web_deferred.exists(agent.session_path)


def test_suite_differee_rouge_consignee_avant_la_relance(tmp_path, monkeypatch):
    relances = []
    monkeypatch.setattr(agent_reprise, "resume_deferred_agent",
                        lambda agent, log: relances.append(log) or agent)
    agent = _agent_web(tmp_path, "echo 3 failed; exit 1")
    agent_reprise._maybe_drain_deferred(agent)

    data = _session(agent)
    assert data["deferred_result"]["statut"] == "rouge"
    assert "3 failed" in data["final_answer"] and "NON FAITE" not in data["final_answer"]
    assert relances, "l'agent est toujours relancé pour corriger"


# --- TUI : plus de sortie du REPL, la suite tourne et son verdict revient --------

def test_tui_lance_la_suite_sans_quitter_et_rapporte_son_verdict(tmp_path, capsys):
    from bouzecode.ui import repl

    state = AgentState()
    reponse = ANSWER + web_deferred_annonce([{"command": "echo 812 passed"}])
    state.final_answer = reponse
    differe = DeferredChecks(answer=reponse, checks=[{"command": "echo 812 passed",
                                                       "timeout": 60}])
    fil = repl._traiter_cloture_differee(differe, state, {"_cwd": str(tmp_path)})
    fil.join(timeout=60)

    assert not fil.is_alive()
    assert state.deferred_result["statut"] == "vert"
    assert "812 passed" in state.final_answer and "NON FAITE" not in state.final_answer
    sortie = capsys.readouterr().out
    assert "812 passed" in sortie
