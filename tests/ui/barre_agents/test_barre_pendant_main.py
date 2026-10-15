# [desc] Pendant un tour de main (invite fermee), la barre des sous-agents reste visible en pied du spinner, du texte en direct (rich.Live) et de la reflexion, puis s'efface ; sans sous-agent, la sortie est inchangee. [/desc]
"""Sortie texte capturee : ce que le terminal recoit pendant que main travaille."""
from __future__ import annotations

import io
import time
from types import SimpleNamespace

import pytest
from rich.console import Console

from bouzecode.backend.agent.state import AgentState
from bouzecode.backend.multi_agent.en_process.fiche import FicheAgent
from bouzecode.backend.multi_agent.en_process.registre import RegistreAgents
from bouzecode.ui import rendering, spinner
from bouzecode.ui.barre_agents import rendu
from bouzecode.ui.barre_agents.clavier import Navigation

LIGNE_ALPHA = "◯ ▶ general-purpose  alpha"


class _Sortie:
    """Ce que le terminal a recu : stdout (spinner, reflexion) puis la console rich."""

    def __init__(self, capsys):
        self._capsys, self._stdout, self.rich = capsys, "", io.StringIO()

    def texte(self) -> str:
        self._stdout += self._capsys.readouterr().out
        return self._stdout + self.rich.getvalue()


@pytest.fixture
def ecran(monkeypatch, capsys):
    """stdout (capsys) et la console rich captures ; etat de rendu remis a neuf."""
    sortie = _Sortie(capsys)
    monkeypatch.setattr(rendering, "console", Console(file=sortie.rich, force_terminal=True,
                                                      width=100, height=40))
    for nom, valeur in (("_RICH_LIVE", True), ("_current_live", None), ("_live_overflow", False),
                        ("_accumulated_text", []), ("_overflow_lines_buf", [])):
        monkeypatch.setattr(rendering, nom, valeur)
    monkeypatch.setattr(rendu, "_source_pied", None)
    monkeypatch.setattr(rendu, "_pied_dessine", False)
    monkeypatch.setattr(rendu, "_pensee", [])
    return sortie


def _attendre(condition) -> None:
    """Boucle bornee sur un etat observable (2 s), jamais une duree fixe."""
    fin = time.monotonic() + 2.0
    while not condition():
        assert time.monotonic() < fin, "etat jamais atteint"
        time.sleep(0.02)


def _avec_un_sous_agent():
    """La barre telle que le REPL la pose : main + un sous-agent qui travaille."""
    registre = RegistreAgents()
    registre.declarer_principal(AgentState(), "claude-opus-5")
    registre.ajouter(FicheAgent(id="a", description="alpha", profondeur=1, state=AgentState(),
                                tache=SimpleNamespace(_cancel_flag=False)))
    vue = Navigation()
    rendu.definir_pied(lambda: [t for _s, t in rendu.lignes(registre, vue, 100)])


def test_la_barre_suit_le_spinner_pendant_les_outils_de_main(ecran):
    _avec_un_sous_agent()
    spinner._start_tool_spinner()
    _attendre(lambda: ecran.texte().count(LIGNE_ALPHA) >= 2)
    spinner._stop_tool_spinner()
    texte = ecran.texte()
    assert texte.count(LIGNE_ALPHA) >= 2  # redessinee a chaque image du spinner
    assert "● main" in texte
    assert texte.endswith(rendu.EFFACER_BLOC)  # a l'arret, le bloc entier est efface


def test_sans_sous_agent_le_spinner_ne_change_pas(ecran):
    spinner._start_tool_spinner()
    _attendre(lambda: "⠋" in ecran.texte())  # premiere image dessinee
    spinner._stop_tool_spinner()
    assert "\x1b[J" not in ecran.texte() and "main" not in ecran.texte()


def test_la_barre_est_le_pied_du_texte_en_direct_et_disparait_a_la_fin(ecran):
    _avec_un_sous_agent()
    rendering.stream_text("Bonjour, je délègue.")
    assert LIGNE_ALPHA in ecran.texte()
    rendering.flush_response()
    texte = ecran.texte()
    #  Le dernier rendu du Live (laisse a l'ecran) est le texte SEUL.
    assert texte.rfind("Bonjour, je délègue.") > texte.rfind(LIGNE_ALPHA)
    assert rendering._current_live is None


def test_la_reflexion_s_ecrit_au_dessus_de_la_barre(ecran):
    _avec_un_sous_agent()
    rendering.stream_thinking("je pèse les options\nla suite")
    texte = ecran.texte()
    assert texte.index("je pèse les options") < texte.index(LIGNE_ALPHA)
    assert "la suite" not in texte  # ligne entamee : ecrite a la fin du bloc
    rendering.end_thinking_block()
    assert ecran.texte().rstrip("\x1b[0m").endswith("la suite")
    assert rendu.EFFACER_BLOC in ecran.texte().split("je pèse les options")[1]
