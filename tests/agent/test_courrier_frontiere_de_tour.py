# [desc] Un message écrit PENDANT le tour d'un agent entre dans la conversation à la frontière de tour suivante (après le lot d'outils en cours), comme dans Claude Code ; un parent bloqué sur son enfant est réveillé par ce courrier. [/desc]
"""Conversation complète contre un modèle scripté : la boîte aux lettres (`_inbox_pop`,
posée en mode web par `ui/repl.py`) est relevée par `loop.run` après chaque lot d'outils."""
from __future__ import annotations

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m{n}"><param name="content">note {n}</param></tool_use>'
BASH = '<tool_use name="Bash" id="b{n}"><param name="command">echo {n}</param></tool_use>'


def _lot(n: int) -> str:
    return METH.format(n=n) + "\n" + BASH.format(n=n)


class _Boite:
    """La boîte d'un agent : ce que l'utilisateur y dépose pendant qu'un outil tourne."""

    def __init__(self):
        self.courrier: list[str] = []

    def relever(self) -> list[str]:
        lus, self.courrier = self.courrier, []
        return lus


def test_un_message_ecrit_pendant_le_lot_d_outils_arrive_au_tour_suivant():
    boite = _Boite()

    def bash(tc):
        if tc["id"] == "b1":  # l'utilisateur écrit PENDANT que le 1er outil tourne
            boite.courrier.append("finalement, appelle le fichier FINAL.md")
        return f"sortie {tc['id']}"

    llm = MockLLM([_lot(1), _lot(2), "J'ai tenu compte de FINAL.md."])
    result = bouzecode(["écris un fichier"], mock_llm=llm, mock_tools={"Bash": bash},
                       config_overrides={"_inbox_pop": boite.relever})

    roles = [(m["role"], str(m.get("content", ""))[:40]) for m in result.messages]
    arrivee = next(i for i, m in enumerate(result.messages)
                   if m["role"] == "user" and "FINAL.md" in str(m.get("content")))
    # Après le résultat du 1er lot, AVANT la réponse suivante du modèle : pas à la fin du travail.
    assert result.messages[arrivee - 1]["role"] == "tool", roles
    assert result.messages[arrivee + 1]["role"] == "assistant", roles
    assert "b2" in str(result.messages[arrivee + 1].get("tool_calls")), roles
    # Le 2e appel au modèle l'a vu (dans sa note : c'est là que vivent les énoncés).
    assert "FINAL.md" in str(llm.recorded_calls[1]["system"]) + str(llm.recorded_calls[1]["messages"])
    assert "FINAL.md" not in str(llm.recorded_calls[0]["system"]) + str(llm.recorded_calls[0]["messages"])
    notes = result.state.context_state.notes
    assert any("FINAL.md" in str(v) for v in notes.values()), "le message entre dans la Methodology"


def test_sans_courrier_rien_ne_change():
    boite = _Boite()
    result = bouzecode(["écris un fichier"], mock_llm=MockLLM([_lot(1), "fini."]),
                       mock_tools={"Bash": "ok"}, config_overrides={"_inbox_pop": boite.relever})
    assert [m["role"] for m in result.messages if m["role"] == "user"] == ["user"]


def test_un_parent_bloque_sur_son_enfant_est_reveille_par_le_courrier():
    """`Agent(background=false)` relit ses enfants ; un message arrivé entre-temps le réveille —
    l'enfant continue en fond, le parent lira le message à sa frontière de tour."""
    from bouzecode.backend.multi_agent import attente_web, enfants

    lectures = []

    def lire():
        lectures.append(1)
        return [{"ticket_id": "T1", "etat": "en_cours", "actif": True}]

    courrier = iter([False, False, True])
    try:
        enfants.attendre_ticket("T1", lire, sleep=lambda s: None, now=lambda: 0.0,
                                reveil=lambda: next(courrier))
    except attente_web.AttenteInterrompue as reveil:
        assert str(reveil) == "T1"
    else:
        raise AssertionError("le parent aurait dû être réveillé")
    assert len(lectures) == 1, "réveillé pendant l'attente du 1er intervalle de sondage"

    rendu = attente_web._wait_for_child(
        lambda *_a: (_ for _ in ()).throw(attente_web.AttenteInterrompue("T1")), "T1", "demo",
        "Enfant T1 lancé.", config := {})
    assert "INTERROMPUE" in rendu and "continue EN FOND" in rendu
    assert config["_bg_agent_launched"] is True


def test_le_reveil_ecoute_le_courrier_et_l_interruption():
    from bouzecode.backend.multi_agent import attente_web

    assert attente_web._reveil({}) is None
    assert attente_web._reveil({"_inbox_peek": lambda: False, "_cancel_peek": lambda: True})() is True
    assert attente_web._reveil({"_inbox_peek": lambda: False})() is False
