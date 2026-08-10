# [desc] Le journal des notes ne stocke que des deltas, et sait toujours relire les sessions d'avant. [/desc]
"""Le journal de la note ne garde QUE des deltas, et la note reste reconstituable.

LE DÉFAUT (2026-07-30) : chaque entrée portait aussi `notes`, l'intégralité de la note à ce
tour. Sur une session de 270 tours, 384 copies d'une note dont l'état final fait 248 Ko — soit
**55 Mo pour ce seul champ**, la moitié d'un JSON de session de 113 Mo. L'instantané n'était
gardé que pour un consommateur qui ne le lit plus.

Le contenu d'un tour reste entièrement reconstituable : il se RECALCULE en repliant le journal
au lieu d'être recopié. Ces tests figent les deux garanties qui rendent ça sûr — la
reconstruction est exacte, et les sessions écrites AVANT le changement se relisent encore.
"""
from bouzecode.backend.context_manager.methodology import (
    reconstruct_methodology_from_timeline,
)
from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = ('<tool_use name="Methodology" id="m{n}"><param name="content">'
        'note du tour {n}</param></tool_use>')
CLOSE = "C'est fait."


def test_le_journal_ne_recopie_plus_la_note_entiere_a_chaque_tour():
    """Aucune entrée ne porte d'instantané complet — c'était la moitié du poids des sessions."""
    result = bouzecode(["deux tours"], mock_llm=MockLLM([
        METH.format(n=1) + '\n<tool_use name="Bash" id="b1">'
                           '<param name="command">echo un</param></tool_use>',
        CLOSE,
    ]))

    timeline = result.state.notes_timeline
    assert timeline, "le tour doit être journalisé"
    assert all("notes" not in entry for entry in timeline)
    assert all("delta" in entry for entry in timeline)


def test_la_note_courante_se_reconstitue_en_repliant_le_journal():
    """L'invariant qui autorise à jeter les instantanés : le repli rend la note vivante."""
    from bouzecode.backend.context_manager import METHODOLOGY_NOTE

    result = bouzecode(["deux tours"], mock_llm=MockLLM([
        METH.format(n=1) + '\n<tool_use name="Bash" id="b1">'
                           '<param name="command">echo un</param></tool_use>',
        CLOSE,
    ]))

    vivante = result.state.context_state.notes[METHODOLOGY_NOTE]
    assert reconstruct_methodology_from_timeline(result.state.notes_timeline) == vivante


def test_une_session_ecrite_avant_le_changement_se_relit_encore():
    """Repli HÉRITÉ : une entrée sans `delta` est un remplacement complet. Sans lui, une vieille
    session rechargée donnerait une note VIDE, et le delta du tour suivant serait faux."""
    ancien = [
        {"turn": 1, "notes": "bloc A"},
        {"turn": 2, "notes": "bloc A\n\nbloc B"},
    ]

    assert reconstruct_methodology_from_timeline(ancien) == "bloc A\n\nbloc B"


def test_un_journal_mixte_ancien_puis_delta_se_replie_correctement():
    """Cas de la MIGRATION : une session commencée avant le changement et poursuivie après."""
    mixte = [
        {"turn": 1, "notes": "bloc A"},                                  # héritée
        {"turn": 2, "delta": {"added": ["bloc B"], "removed": []}},      # nouvelle
    ]

    assert reconstruct_methodology_from_timeline(mixte) == "bloc A\n\nbloc B"


def test_une_compaction_reste_un_remplacement_complet():
    """Une compaction est journalisée en `removed` + `added` : le repli repart de zéro."""
    journal = [
        {"turn": 1, "delta": {"added": ["bloc A", "bloc B"], "removed": []}},
        {"turn": 2, "delta": {"added": ["resume compacte"], "removed": ["bloc A", "bloc B"]}},
    ]

    assert reconstruct_methodology_from_timeline(journal) == "resume compacte"
