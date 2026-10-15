# [desc] Un message posé pendant le tour (courrier du parent, relance du harnais) arrive APRÈS les résultats du lot en cours sans les retirer du fil envoyé au modèle. [/desc]
"""Essai du 2026-09-25 (DeepSeek) : `relever_courrier` et les relances de `loop_turn` ajoutaient
un message user derrière les résultats d'outils. Le fil minimal (`minimal_payload`) lisait ce
message comme la fin du lot et n'envoyait que lui (keep=0 dans debug_payloads) : l'enfant
40ea29e4 a perdu les 3 résultats de son tour 35 en recevant le message de son parent."""
from __future__ import annotations

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m{n}"><param name="content">note {n}</param></tool_use>'
BASH = '<tool_use name="Bash" id="b{n}"><param name="command">echo {n}</param></tool_use>'


def _lot(n: int) -> str:
    return METH.format(n=n) + "\n" + BASH.format(n=n)


def _fil(appel: dict) -> str:
    return str(appel["messages"])


def test_le_message_du_parent_arrive_avec_les_resultats_du_lot_qu_il_suit():
    """Le parent écrit pendant le 1er lot : l'appel suivant porte son message ET la sortie du lot."""
    courrier: list[str] = []

    def bash(tc):
        if tc["id"] == "b1":
            courrier.append("[Message de ton agent parent] commite avant de continuer")
        return f"sortie {tc['id']} 20/20 OK"

    def relever():
        lus = list(courrier)
        courrier.clear()
        return lus

    llm = MockLLM([_lot(1), _lot(2), "fini."])
    bouzecode(["travaille"], mock_llm=llm, mock_tools={"Bash": bash},
              config_overrides={"_inbox_pop": relever})

    fil = _fil(llm.recorded_calls[1])
    assert "commite avant de continuer" in fil
    assert "sortie b1 20/20 OK" in fil, "le résultat du lot a été retiré du fil par le courrier"


def test_la_relance_d_un_tour_meta_seul_porte_la_relance_sans_rejouer_la_methodology():
    """Un tour qui n'écrit que sa note est relancé : la relance est sur le fil, mais pas l'appel
    Methodology ni son résultat (la note est dans le system ; rejouée, elle faisait refuser
    claude-opus-5-5 le 2026-10-07) — et donc aucun tool_result orphelin."""
    llm = MockLLM([METH.format(n=1), _lot(2), "fini."])
    bouzecode(["travaille"], mock_llm=llm, mock_tools={"Bash": "ok"})

    fil = _fil(llm.recorded_calls[1])
    assert "ce tour n'a produit ni travail" in fil
    assert "'role': 'tool'" not in fil


def test_un_nouveau_message_de_l_utilisateur_apres_une_reponse_finale_ferme_toujours_le_lot():
    """Contrôle : un vrai nouveau tour utilisateur (après une réponse finale) ne traîne pas l'ancien lot."""
    llm = MockLLM([_lot(1), "fini.", "re-fini."])
    bouzecode(["travaille", "et maintenant ?"], mock_llm=llm, mock_tools={"Bash": "sortie ancienne"})

    fil = _fil(llm.recorded_calls[2])
    assert "et maintenant ?" in fil
    assert "sortie ancienne" not in fil
