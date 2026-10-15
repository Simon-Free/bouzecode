"""Le declencheur de compaction : DEUX seuils, mesures sur la note elle-meme.

Le declencheur mesurait le prefixe cache TOTAL (systeme + documentation des outils
+ note), dont 52 % est statique et qu'aucune passe ne peut toucher. Il confiait
donc 18 % du volume a la passe de prose en lui demandant de faire redescendre
l'ensemble : plafond `prose / 5` = 3 979 caracteres en mediane pour un modele qui
n'ecrit jamais moins de ~5 000. Mesure sur 305 passes : 78 % retiraient ZERO
caractere, et une compaction a efface trois tours de note (session 299279a7).

Deux declencheurs independants remplacent ce test :

* **A — prose** : la prose COMPACTABLE de la note depasse `NOTE_PROSE_TOKENS_THRESHOLD`
  → compaction complete (`judge_and_prune` puis `compact_prose`). Les snippets sont
  exclus du CALCUL du seuil, jamais de son ACTION.
* **B — snippets** : les snippets VIVANTS seuls depassent `LIVE_SNIPPET_TOKENS_THRESHOLD`
  → `judge_and_prune` seul. Lancer la passe de prose sur 5 000 tokens de prose
  rejouerait le bug qu'on corrige.

Ce que ces tests verrouillent avant tout : la mesure du seuil et la selection des
candidats de `compact_prose` partagent le MEME code (`_is_prose`, `_is_mission`).
Toute divergence entre ce qui arme et ce qui est compactable recree le bug.
"""

from __future__ import annotations

import pytest

from bouzecode.backend.context_manager.compact_methodology import (
    CHARS_PER_TOKEN,
    LIVE_SNIPPET_TOKENS_THRESHOLD,
    NOTE_PROSE_TOKENS_THRESHOLD,
    compactable_prose_tokens,
    live_snippet_tokens,
    maybe_compact,
    should_compact,
    should_prune_snippets,
)


class FakeSession:
    """Le journal de la session, reduit a ce que le declencheur lit et ecrit."""

    def __init__(self, cached_tokens: int = 0):
        self.turn_count = 0
        self.compaction_log: list = []
        self.timing_entries = [{
            "phase": "llm", "in_tokens": 500,
            "cache_read_tokens": cached_tokens, "cache_creation_tokens": 0,
        }]


class FakeContextState:
    def __init__(self, text: str):
        self.notes = {"methodology": text}
        self._methodology_cache_snapshot = "some snapshot"


def _config(depth: int = 0, cached_tokens: int = 0, **extra) -> dict:
    return {"_state": FakeSession(cached_tokens), "_depth": depth, **extra}


# --- Fabriques de note ---------------------------------------------------------


def _snippets(chars: int) -> str:
    """Des blocs `## snippet:` VIVANTS totalisant environ `chars` caracteres."""
    blocks, total = [], 0
    n = 0
    while total < chars:
        n += 1
        body = "\n".join(f"   {i:3d}\tligne de code numero {i} du fichier lu"
                         for i in range(1, 21))
        block = f'## snippet: proj/mod{n}.py L1-20 — "lecture {n}"\n{body}'
        blocks.append(block)
        total += len(block) + 1
    return "\n".join(blocks)


def _users(chars: int) -> str:
    """Des blocs `## User` totalisant environ `chars` caracteres."""
    blocks, total = [], 0
    n = 0
    while total < chars:
        n += 1
        block = f"## User @2026-08-26 1{n}:00:00\n" + (
            f"Consigne numero {n} : refactorer le parser sans casser le cache. " * 8)
        blocks.append(block)
        total += len(block) + 1
    return "\n".join(blocks)


def _prose(chars: int) -> str:
    """De la prose ordinaire (des tours de raisonnement) totalisant ~`chars` car."""
    blocks, total = [], 0
    n = 0
    while total < chars:
        n += 1
        block = f"## Tour {n}\n" + (
            f"Constat {n} : le parser lit le header en premier, decision gardee. " * 8)
        blocks.append(block)
        total += len(block) + 1
    return "\n".join(blocks)


PROSE_CHARS_AT_THRESHOLD = int(NOTE_PROSE_TOKENS_THRESHOLD * CHARS_PER_TOKEN) + 5_000
SNIPPET_CHARS_AT_THRESHOLD = int(LIVE_SNIPPET_TOKENS_THRESHOLD * CHARS_PER_TOKEN) + 5_000


# --- §5.1 / §5.2 : ce qui n'arme PAS le seuil A -------------------------------


def test_a_note_made_only_of_live_snippets_never_fires_the_prose_trigger():
    """§5.1 — 200 000 caracteres de snippets vivants : la passe de prose n'y peut rien.

    C'est le coeur du correctif : armer sur une matiere que `compact_prose` ne
    touche pas, c'est ce qui produisait 78 % de passes steriles.
    """
    note = _snippets(200_000)
    state = FakeContextState(note)
    assert compactable_prose_tokens(note) == 0
    assert should_compact(state, "methodology", _config()) is False


def test_a_note_made_only_of_user_blocks_never_fires_the_prose_trigger():
    """§5.2 — les blocs `## User` sont exclus du calcul (`_is_mission`)."""
    note = _users(200_000)
    state = FakeContextState(note)
    assert compactable_prose_tokens(note) == 0
    assert should_compact(state, "methodology", _config()) is False


# --- §5.3 : ce qui arme le seuil A --------------------------------------------


def test_prose_over_the_threshold_fires_whatever_the_snippets_weigh():
    """§5.3 — seule la prose compte, et elle suffit."""
    prose_only = _prose(PROSE_CHARS_AT_THRESHOLD)
    assert compactable_prose_tokens(prose_only) >= NOTE_PROSE_TOKENS_THRESHOLD
    assert should_compact(FakeContextState(prose_only), "methodology", _config()) is True

    with_snippets = prose_only + "\n" + _snippets(60_000)
    assert should_compact(FakeContextState(with_snippets), "methodology", _config()) is True


def test_prose_just_under_the_threshold_does_not_fire():
    """La borne est un `>=` : juste en dessous, on ne paie rien."""
    note = _prose(int(NOTE_PROSE_TOKENS_THRESHOLD * CHARS_PER_TOKEN) - 20_000)
    assert compactable_prose_tokens(note) < NOTE_PROSE_TOKENS_THRESHOLD
    assert should_compact(FakeContextState(note), "methodology", _config()) is False


# --- §5.5 : les pierres tombales sont de la prose -----------------------------


TOMBSTONES = "\n".join([
    '## snippet-dropped: proj/old.py L1-40 — "lecture epuisee" (1 940 chars)',
    '## snippet ERROR: proj/gone.py — file not found',
    '## snippet-stale: proj/mod.py L1-20 — edited since snapshot',
] * 40)


def test_tombstones_count_as_compactable_prose():
    """§5.5 — non-regression du correctif du 2026-08-23.

    `## snippet-dropped:`, `## snippet ERROR` et `## snippet-stale:` sont de la
    prose au sens de `_is_prose` : elles pesaient 37,8 % d'une note reelle. Les
    exclure du calcul rendrait a nouveau ce volume invisible au declencheur.
    """
    assert compactable_prose_tokens(TOMBSTONES) > 0
    assert live_snippet_tokens(TOMBSTONES) == 0


def test_live_snippet_tokens_counts_only_live_blocks():
    """La mesure B ne voit que la matiere de `judge_and_prune`."""
    note = _prose(5_000) + "\n" + TOMBSTONES + "\n" + _snippets(30_000)
    live = live_snippet_tokens(note)
    assert live > 0
    assert live < int(len(note) / CHARS_PER_TOKEN)


# --- §5.6 : les gardes conservees ---------------------------------------------


def test_a_side_call_never_compacts_its_own_context():
    """§5.6 — un appel annexe (config copiee, `_context_state` mis a None) court-circuite
    les DEUX declencheurs."""
    huge_prose = FakeContextState(_prose(PROSE_CHARS_AT_THRESHOLD))
    huge_snips = FakeContextState(_snippets(SNIPPET_CHARS_AT_THRESHOLD))
    annexe = _config(depth=1, _context_state=None)
    assert should_compact(huge_prose, "methodology", annexe) is False
    assert should_prune_snippets(huge_snips, "methodology", annexe) is False


def test_a_sub_agent_compacts_its_own_note():
    """Un sous-agent a `_depth` >= 1 mais SA note (`_context_state`) : les deux
    declencheurs lui sont ouverts, comme a l'agent principal."""
    huge_prose = FakeContextState(_prose(PROSE_CHARS_AT_THRESHOLD))
    huge_snips = FakeContextState(_snippets(SNIPPET_CHARS_AT_THRESHOLD))
    assert should_compact(huge_prose, "methodology",
                          _config(depth=1, _context_state=huge_prose)) is True
    assert should_prune_snippets(huge_snips, "methodology",
                                 _config(depth=2, _context_state=huge_snips)) is True


def test_no_config_means_no_trigger():
    state = FakeContextState(_prose(PROSE_CHARS_AT_THRESHOLD))
    assert should_compact(state, "methodology", None) is False
    assert should_prune_snippets(state, "methodology", None) is False
    assert maybe_compact(state, "methodology", None) == 0


def test_an_empty_note_is_never_compacted():
    state = FakeContextState("")
    assert should_compact(state, "methodology", _config()) is False
    assert should_prune_snippets(state, "methodology", _config()) is False
    assert maybe_compact(state, "methodology", _config()) == 0


def test_a_missing_note_key_is_never_compacted():
    state = FakeContextState(_prose(PROSE_CHARS_AT_THRESHOLD))
    assert should_compact(state, "other_note", _config()) is False
    assert should_prune_snippets(state, "other_note", _config()) is False


# --- §5.4 : ce que chaque seuil DECLENCHE -------------------------------------


class PassSpy:
    """Remplace les deux passes payantes et enregistre l'ordre des appels."""

    def __init__(self):
        self.order: list[str] = []

    def judge(self, note, context_state, config):
        self.order.append("judge")
        # Le juge remplace un snippet par une pierre tombale : la note raccourcit.
        pruned = note.replace(_SNIPPET_TO_PRUNE, _TOMBSTONE_OF_IT)
        return pruned, len(note) - len(pruned)

    def prose(self, note, context_state, config):
        self.order.append("prose")
        return note + "", 0


_SNIPPET_TO_PRUNE = ('## snippet: proj/spent.py L1-4 — "lecture epuisee"\n'
                     "     1\tdef spent():\n"
                     "     2\t    return 0\n"
                     "     3\t# a jeter\n"
                     "     4\t# vraiment\n")
_TOMBSTONE_OF_IT = '## snippet-dropped: proj/spent.py L1-4\n'


@pytest.fixture
def passes(monkeypatch):
    """Installe le spy a la place de `judge_and_prune` / `compact_prose`.

    `maybe_compact` les importe DANS la fonction, donc on patche les modules
    d'origine (pas d'attribut sur `compact_methodology`).
    """
    from bouzecode.backend.context_manager import compact_judge, compact_prose

    spy = PassSpy()
    monkeypatch.setattr(compact_judge, "judge_and_prune", spy.judge)
    monkeypatch.setattr(compact_prose, "compact_prose", spy.prose)
    return spy


def test_threshold_a_runs_the_judge_then_the_prose_pass(passes):
    """§5.4 — seuil A : compaction COMPLETE, snippets inclus.

    Les snippets sont exclus du CALCUL du seuil A, jamais de son ACTION : une
    fois arme, on nettoie tout dans le meme `cache_create`, qui est de toute
    facon du des qu'un caractere bouge. Ce test verrouille l'ordre et le fait
    que le snippet epuise est bien elague alors qu'il ne compte pas dans le seuil.
    """
    note = _prose(PROSE_CHARS_AT_THRESHOLD) + "\n" + _SNIPPET_TO_PRUNE
    state = FakeContextState(note)

    removed = maybe_compact(state, "methodology", _config())

    assert passes.order == ["judge", "prose"]
    assert removed > 0
    assert _SNIPPET_TO_PRUNE not in state.notes["methodology"]
    assert _TOMBSTONE_OF_IT in state.notes["methodology"]


def test_threshold_b_alone_runs_the_judge_only(passes):
    """§5.4 bis — snippets seuls au-dessus de B : pas de passe de prose.

    Une prose de 5 000 tokens confiee a la passe, c'est exactement le bug
    corrige : un plafond a 1 000 tokens pour un modele qui n'ecrit jamais moins
    de ~1 900. On ne l'appelle donc pas.
    """
    note = (_prose(5_000) + "\n" + _snippets(SNIPPET_CHARS_AT_THRESHOLD)
            + "\n" + _SNIPPET_TO_PRUNE)
    state = FakeContextState(note)

    assert should_compact(state, "methodology", _config()) is False
    assert should_prune_snippets(state, "methodology", _config()) is True

    removed = maybe_compact(state, "methodology", _config())

    assert passes.order == ["judge"]
    assert removed > 0
    assert _TOMBSTONE_OF_IT in state.notes["methodology"]


def test_both_thresholds_take_path_a_once(passes):
    """§5.4 ter — A contient B : un seul `judge_and_prune`, pas deux."""
    note = (_prose(PROSE_CHARS_AT_THRESHOLD) + "\n"
            + _snippets(SNIPPET_CHARS_AT_THRESHOLD) + "\n" + _SNIPPET_TO_PRUNE)
    state = FakeContextState(note)

    assert should_compact(state, "methodology", _config()) is True
    assert should_prune_snippets(state, "methodology", _config()) is True

    maybe_compact(state, "methodology", _config())

    assert passes.order == ["judge", "prose"]


def test_no_threshold_crossed_makes_no_call_at_all(passes):
    """§5.4 quater — sous les deux seuils, zero appel LLM et zero caractere retire."""
    note = _prose(5_000) + "\n" + _snippets(10_000)
    state = FakeContextState(note)

    assert maybe_compact(state, "methodology", _config()) == 0
    assert passes.order == []
    assert state.notes["methodology"] == note
