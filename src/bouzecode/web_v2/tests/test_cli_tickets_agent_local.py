# [desc] Bout en bout SANS serveur : `bouzecode tickets creer` lance un VRAI agent local (process bouzecode contre un faux LLM sur un vrai socket), `tickets suivre` constate sa fin comme le watchdog et sort selon la clôture (0 FinalAnswer, 4 prose obstinée). [/desc]
from __future__ import annotations

import pytest

from bouzecode.web_v2.services.work import tickets
from bouzecode.web_v2.tests.cli_tickets_aides import cli, cli_json, depot_demo
from bouzecode.web_v2.tests.faux_llm_refus import MODELE, PROXYS
from bouzecode.web_v2.tests.faux_llm_scripte import FauxLlmScripte, final_answer


@pytest.fixture()
def env_du_faux_llm(monkeypatch):
    """Les agents lancés héritent de l'environnement : faux LLM, aucun proxy, et un serveur web
    injoignable pour leur hook de fin (le vrai 5056 ne doit jamais rien recevoir d'un test)."""
    for variable in PROXYS:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "cle-factice")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "cle-factice")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("BOUZECODE_WEB_BASE_URL", "http://127.0.0.1:9")

    def pointer(llm) -> None:
        monkeypatch.setenv("ANTHROPIC_BASE_URL", llm.url)
    return pointer


def _creer_et_suivre(capsys, tmp_path) -> tuple[str, int, str]:
    depot_demo(tmp_path)
    code, corps = cli_json(capsys, "tickets", "creer", "--projet", "demo", "--titre", "b",
                           "--prompt", "Ajoute b.txt", "--isolation", "shared",
                           "--modele", MODELE)
    assert code == 0, corps
    assert corps["via"] == "process" and corps["key"].startswith("agent/")
    ticket_id = corps["ticket_id"]
    code, texte, _ = cli(capsys, "tickets", "suivre", "demo", ticket_id, "--intervalle", "0.5",
                         "--delai", "100")
    return ticket_id, code, texte


def test_un_agent_qui_livre_par_finalanswer_sort_en_0(tmp_path, capsys, env_du_faux_llm):
    with FauxLlmScripte([final_answer("b.txt ajoute.")]) as llm:
        env_du_faux_llm(llm)
        ticket_id, code, texte = _creer_et_suivre(capsys, tmp_path)
    assert code == 0, texte
    assert "run_ended" in texte and "delivered" in texte
    assert tickets.get_ticket("demo", ticket_id)["state"] == "delivered"


def test_un_agent_qui_finit_en_prose_sort_en_4(tmp_path, capsys, env_du_faux_llm):
    with FauxLlmScripte(["Voila, c'est fait."]) as llm:
        env_du_faux_llm(llm)
        ticket_id, code, texte = _creer_et_suivre(capsys, tmp_path)
    assert code == 4, texte
    ticket = tickets.get_ticket("demo", ticket_id)
    assert ticket["state"] == "idle_no_delivery"
    assert ticket["state_reason"]["code"] == "final_answer_never_called"
