# [desc] Tests for the agent bar's history display, five-agent scrolling, keyboard navigation, /clear, and input shrinking [/desc]
from __future__ import annotations

import io
from types import SimpleNamespace

from prompt_toolkit.data_structures import Size
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output.vt100 import Vt100_Output

from bouzecode.backend.agent.state import AgentState
from bouzecode.backend.commands.core.basic import cmd_clear
from bouzecode.backend.multi_agent.en_process.fiche import ERREUR, FINI, FicheAgent
from bouzecode.backend.multi_agent.en_process.registre import RegistreAgents
from bouzecode.ui.barre_agents import rendu
from bouzecode.ui.barre_agents.clavier import Navigation

T0 = 1_000_000.0


def _registre():
    registre = RegistreAgents()
    registre.declarer_principal(AgentState(), "claude-opus-5")
    return registre


def _fiche(id_, **champs):
    champs.setdefault("profondeur", 1)
    return FicheAgent(id=id_, description=id_, debut=T0, state=AgentState(),
                      tache=SimpleNamespace(_cancel_flag=False), **champs)


def _ids(registre):
    return [f.id for f in rendu.ordre(registre)]


def test_les_termines_passent_dans_l_historique_apres_les_actifs():
    registre = _registre()
    registre.ajouter(_fiche("fini", etat=FINI, fin=T0 + 1))
    registre.ajouter(_fiche("actif"))
    registre.ajouter(_fiche("rate", etat=ERREUR, fin=T0 + 2))
    assert _ids(registre) == ["main", "actif", "fini", "rate"]
    lignes = rendu.texte(registre, Navigation(), maintenant=T0 + 9).splitlines()
    assert "actif" in lignes[1]
    assert lignes[2].strip() == "── historique (2) ──"
    assert "fini" in lignes[3] and "rate" in lignes[4]


def test_au_plus_cinq_agents_affiches_avec_fleche_vers_les_suivants():
    registre = _registre()
    for i in range(4):
        registre.ajouter(_fiche(f"actif{i}"))
    for i in range(4):
        registre.ajouter(_fiche(f"fini{i}", etat=FINI, fin=T0 + 1))
    nav = Navigation()
    lignes = rendu.texte(registre, nav, maintenant=T0 + 9).splitlines()
    agents = [l for l in lignes[1:] if "general-purpose" in l]
    assert len(agents) == 5
    assert lignes[-1].strip() == "▼ 3 de plus"
    assert not any("▲" in l for l in lignes)

    ids = _ids(registre)
    nav.entrer_focus(ids)
    for _ in range(7):
        nav.descendre(ids)
    lignes = rendu.texte(registre, nav, maintenant=T0 + 9).splitlines()
    assert lignes[1].strip() == "▲ 3 de plus"
    assert "actif3" in lignes[2]
    assert lignes[3].strip() == "── historique (4) ──"
    assert any(l.startswith("❯") and "fini3" in l for l in lignes)
    assert not any("▼" in l for l in lignes)
    assert len([l for l in lignes if "general-purpose" in l]) == 5


def test_fleche_haut_depuis_main_rend_la_main_a_la_zone_de_texte():
    nav = Navigation()
    ids = ["main", "a", "b"]
    assert nav.entrer_focus(ids) and nav.selection == 1
    nav.monter(ids)
    assert nav.focus and nav.selection == 0
    nav.monter(ids)
    assert not nav.focus


def test_clear_tue_les_actifs_et_efface_les_termines():
    registre = _registre()
    actif = registre.ajouter(_fiche("actif"))
    registre.ajouter(_fiche("fini", etat=FINI, fin=T0 + 1))
    state = AgentState()
    config = {"_tui_agents": registre, "model": "x"}
    cmd_clear("", state, config)
    assert actif.tache._cancel_flag is True
    assert registre.sous_agents() == []
    assert rendu.texte(registre, Navigation()) == ""
    #  Le fil de l'agent tue retrouve encore sa fiche pour finir proprement.
    registre.changer("actif", etat=FINI)
    assert registre.fiche("actif").etat == FINI and registre.sous_agents() == []


def test_la_zone_de_saisie_retrecit_apres_un_message_long():
    import asyncio
    from bouzecode.ui.paste_input import _new_session

    async def scenario():
        sortie = io.StringIO()
        output = Vt100_Output(sortie, lambda: Size(rows=40, columns=60), term="xterm")
        with create_pipe_input() as entree:
            session = _new_session(InMemoryHistory(), input=entree, output=output)
            app = session.app
            session.message = "> "

            def dessiner():
                app.before_render.fire()
                app.renderer.render(app, app.layout)

            session.default_buffer.text = "x" * 600
            dessiner()
            haute = app.renderer._last_screen.height
            session.default_buffer.text = "court"
            dessiner()
            return haute, app.renderer._last_screen.height

    haute, basse = asyncio.run(scenario())
    assert haute >= 10
    assert basse < 3
