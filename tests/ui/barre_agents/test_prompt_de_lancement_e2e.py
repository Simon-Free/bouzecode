# [desc] `bouzecode --prompt-file x.txt` dans une console : le prompt devient le 1er message du TUI (sous-agents dans la barre, pas de fenetres) et le REPL reste ouvert ; sans console ou avec `-p`, l'ancien run non interactif est inchange. [/desc]
"""Vrai REPL face au faux LLM HTTP (faux_llm_agents.py). Aucune fenetre de terminal ne peut
s'ouvrir : le lanceur de l'ancien mode est remplace par un releve qui refuse."""
from __future__ import annotations

import contextlib
import sys
import threading

import pytest

from bouzecode.backend.multi_agent.en_process.fiche import PRINCIPAL

from .faux_llm_agents import FauxLlmAgents
from .test_tui_sous_agents_e2e import _attendre, _tui_pilote, config_contre_le_faux_llm


@pytest.fixture
def fenetres_ouvertes(monkeypatch) -> list:
    """Chaque sous-agent que l'ancien mode aurait ouvert dans une fenetre de terminal."""
    ouvertes = []

    def releve_sans_ouvrir(params, config):
        ouvertes.append(params.get("name"))
        return "Error: fenetre de terminal interdite dans ce test"

    monkeypatch.setattr("bouzecode.backend.multi_agent.lancement_terminal._spawn_terminal_agent",
                        releve_sans_ouvrir)
    return ouvertes


def _premier_message_utilisateur(state) -> str:
    return next(str(m.get("content")) for m in state.messages if m.get("role") == "user")


def test_prompt_de_lancement_en_console_ouvre_le_tui_avec_ses_sous_agents(
        monkeypatch, tmp_path, fenetres_ouvertes):
    """L'utilisateur lance bouzecode avec un prompt dans son terminal : main le traite comme un
    1er message tape, son sous-agent tourne dans la barre (aucune fenetre), puis l'invite
    se rouvre pour la suite de la conversation."""
    monkeypatch.chdir(tmp_path)
    prompt = "[principal:repos] lance q"
    with FauxLlmAgents() as llm, \
            _tui_pilote(monkeypatch, llm, tmp_path, prompt) as (clavier, ecran, config):
        registre, ecran_agents = config["_tui_agents"], config["_attente_lot"].__self__
        principal = registre.fiche(PRINCIPAL).state
        _attendre(lambda: principal.final_answer == "main a fini", "main livre",
                  etat=lambda: [str(m.get("content"))[:80] for m in principal.messages[-3:]])

        assert _premier_message_utilisateur(principal) == prompt
        assert [f.description for f in registre.sous_agents()] == ["q"]
        assert not config.get("close_requires_final_answer"), "session interactive"
        _attendre(lambda: ecran_agents.session().app.is_running, "invite rouverte apres le tour")
    assert fenetres_ouvertes == []


def _run_non_interactif(monkeypatch, dossier, prompt: str, console: bool, option_p: bool):
    """repl() avec un prompt de lancement ; rend (code de sortie, config, saisies lues)."""
    from bouzecode.ui.repl import repl

    saisies = []
    monkeypatch.setattr(sys.stdin, "isatty", lambda: console, raising=False)
    monkeypatch.setattr("builtins.input", lambda invite="": saisies.append(invite) or "/exit")
    with FauxLlmAgents() as llm:
        config = config_contre_le_faux_llm(monkeypatch, llm, dossier)
        if option_p:
            config["_non_interactif"] = True  # ce que pose cli.py pour `-p`
        rendu = {}

        def lancer():
            with contextlib.suppress(SystemExit):
                rendu["code"] = repl(config, initial_prompt=prompt)

        fil = threading.Thread(target=lancer, daemon=True)
        fil.start()
        fil.join(60)
        assert not fil.is_alive(), "le run non interactif n'a pas rendu la main"
    return rendu.get("code"), config, saisies


@pytest.mark.parametrize("console, option_p", [(False, False), (True, True)],
                         ids=["stdin_sans_console", "option_p"])
def test_sans_console_ou_avec_p_le_run_reste_non_interactif(
        monkeypatch, tmp_path, fenetres_ouvertes, console, option_p):
    """Sans console, ou avec `-p` : le prompt est joue seul, FinalAnswer exigee, sortie
    avec son code — ni barre des sous-agents, ni invite."""
    monkeypatch.chdir(tmp_path)
    code, config, saisies = _run_non_interactif(monkeypatch, tmp_path, "[enfant:B] livre",
                                                console, option_p)

    assert code == 0, "run livre par FinalAnswer"
    assert config.get("close_requires_final_answer") is True
    assert "_tui_agents" not in config
    assert saisies == [], "le REPL interactif n'aurait pas du demander de saisie"
    assert fenetres_ouvertes == []
