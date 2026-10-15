# [desc] Tests that Ctrl+C interrupts only the viewed sub-agent and is not intercepted on the main view [/desc]
from __future__ import annotations

from types import SimpleNamespace

from prompt_toolkit.keys import Keys

from bouzecode.ui.barre_agents.clavier import Navigation, touches


class FauxRegistre:
    def __init__(self):
        self.interrompus: list[str] = []

    def interrompre(self, ident):
        self.interrompus.append(ident)

    def sous_agents(self):
        return ["alpha"]


def _ecran():
    registre = FauxRegistre()
    session = SimpleNamespace(default_buffer=SimpleNamespace(text=""))
    return SimpleNamespace(registre=registre, nav=Navigation(), session=lambda: session)


def _ctrl_c(cles):
    return [b for b in cles.bindings if b.keys == (Keys.ControlC,)]


def test_ctrl_c_dans_la_vue_d_un_sous_agent_l_interrompt_lui_seul():
    ecran = _ecran()
    ecran.nav.vue = "alpha"
    actifs = [b for b in _ctrl_c(touches(ecran)) if b.filter()]
    assert actifs, "aucun binding Ctrl+C actif dans la vue d'un sous-agent"
    actifs[0].handler(SimpleNamespace(app=None))
    assert ecran.registre.interrompus == ["alpha"]


def test_ctrl_c_sur_main_n_est_pas_intercepte():
    ecran = _ecran()
    assert not [b for b in _ctrl_c(touches(ecran)) if b.filter()]
