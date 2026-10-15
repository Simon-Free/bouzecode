# [desc] Une compaction réelle (résumé de prose par un faux serveur Anthropic, filet d'élagage) sur une note qui porte des blocs « ## Harnais » : ils ressortent à l'identique, à leur place, et ne sont jamais envoyés au résumeur. [/desc]
"""Les notes de contexte empilées (contexte_fige.empiler_note_de_contexte) ne se compactent pas.

Elles portent le contrat de worktree (récolte, branche de travail) : un résumé pourrait le
reformuler ou le perdre. La passe de prose les laisse à leur place et ne les envoie pas au
modèle ; le filet d'élagage ne les retire jamais. Le résumé passe par le vrai pipeline
(maybe_compact → loop_turn.stream → dispatch → client Anthropic) jusqu'à un serveur local.
"""
from __future__ import annotations

from bouzecode.backend.context_manager.compact_filet import elaguer_si_necessaire
from bouzecode.backend.context_manager.compact_methodology import (
    CHARS_PER_TOKEN, NOTE_PROSE_TOKENS_THRESHOLD, maybe_compact,
)
from bouzecode.backend.context_manager.compact_prose import SUMMARY_HEADER
from bouzecode.backend.context_manager.contexte_fige import empiler_note_de_contexte
from bouzecode.backend.context_manager.methodology import _append_block
from bouzecode.backend.context_manager.state import METHODOLOGY_NOTE, ContextState
from tests import cache_conversation_helpers
from tests.mock_anthropic_server import start_mock_anthropic

NOTE_ENTREE = ("[harnais] Tu travailles désormais dans le worktree C:/wt/solo-3, branche "
               "agent/solo-3.\n- Ta branche de travail est `agent/solo-3`.\n"
               "## Structure du plan\n- récolte avant de rendre la main")
NOTE_SORTIE = "[harnais] Tu n'es plus dans le worktree C:/wt/solo-3 : retour à C:/depot."
RESUME = "Mission en cours : corriger l'import pptx.\nimport.py lu ; le bug est ligne 42."


def _note_avec_harnais(etapes: int) -> tuple[ContextState, list[str]]:
    """Une mission, de la prose d'étapes, et deux notes de harnais empilées au milieu."""
    state = ContextState()
    _append_block(state, "## User @x\nCorrige l'import pptx.")
    taille = int(NOTE_PROSE_TOKENS_THRESHOLD * CHARS_PER_TOKEN * 1.1 / etapes) + 1
    for numero in range(etapes):
        _append_block(state, f"## Étape {numero}\n" + "x" * taille)
        if numero == etapes // 3:
            empiler_note_de_contexte(state, NOTE_ENTREE)
        if numero == 2 * etapes // 3:
            empiler_note_de_contexte(state, NOTE_SORTIE)
    note = state.notes[METHODOLOGY_NOTE]
    blocs = [b.strip() for b in note.split("\n\n## ") if b.startswith("Harnais @")]
    return state, ["## " + b for b in blocs]


def test_le_resume_de_la_note_garde_les_blocs_harnais_intacts(monkeypatch):
    url, serveur = start_mock_anthropic([RESUME] * 3)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", url)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(cache_conversation_helpers, "LIVE_API_ALLOWED", True)  # localhost
    state, blocs_harnais = _note_avec_harnais(etapes=6)
    assert len(blocs_harnais) == 2 and "### Structure du plan" in blocs_harnais[0]

    retire = maybe_compact(state, METHODOLOGY_NOTE, {"model": "claude-opus-5"})

    note = state.notes[METHODOLOGY_NOTE]
    assert retire > 0 and SUMMARY_HEADER in note, "la compaction a bien eu lieu"
    assert "## Étape" not in note
    for bloc in blocs_harnais:
        assert note.count(bloc) == 1, "bloc ## Harnais ressorti à l'identique"
    assert note.index(SUMMARY_HEADER) < note.index(blocs_harnais[0]) < note.index(blocs_harnais[1])
    envoye = str(serveur.recorded_calls)
    assert len(serveur.recorded_calls) == 1 and "[harnais]" not in envoye


def test_le_filet_d_elagage_ne_retire_jamais_un_bloc_harnais():
    """Compaction en échec (aucun résumé) : l'élagage mécanique retire la vieille prose,
    jamais les blocs ## Harnais, même les plus anciens."""
    state, blocs_harnais = _note_avec_harnais(etapes=40)
    _append_block(state, "## Étape finale\n" + "x" * int(
        NOTE_PROSE_TOKENS_THRESHOLD * CHARS_PER_TOKEN * 1.5))

    note = elaguer_si_necessaire(state.notes[METHODOLOGY_NOTE], None)

    assert "## élagage de secours" in note and "## Étape 0\n" not in note
    for bloc in blocs_harnais:
        assert note.count(bloc) == 1
