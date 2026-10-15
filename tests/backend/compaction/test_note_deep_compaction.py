# [desc] Tests de la compaction de note : deux seuils de matière (prose, snippets vivants), le modèle juge chaque snippet [/desc]
"""La compaction de la note, vue de l'exterieur.

Contrat teste : `maybe_compact` ne fait RIEN tant que la note elle-meme n'est pas
lourde. Deux seuils independants, mesures sur la MATIERE de la note et non sur les
timings du provider :

* seuil A — la prose compactable depasse `NOTE_PROSE_TOKENS_THRESHOLD` : passe
  complete, le juge des snippets PUIS le resume de la prose ;
* seuil B — les snippets vivants depassent `LIVE_SNIPPET_TOKENS_THRESHOLD` : le
  juge seul, il n'y a pas de prose a replier.

Un seuil est un NIVEAU, pas un evenement : c'est pourquoi les tests arment la
compaction en gonflant la note (corps de snippet pour B, tours de prose pour A) et
jamais en bricolant une taille de prefixe cache. Toutes les tailles sont derivees
des constantes du module : aucun litteral ici ne peut se desynchroniser d'elles.

Il n'y a ni espacement en tours ni snippet protege : la seule garde restante empeche
un appel annexe (`_context_state` a None) de declencher sa propre compaction.
"""
from __future__ import annotations

import pytest

from bouzecode.backend.agent.providers.types import AssistantTurn, StreamStarted
from bouzecode.backend.agent.stream_interceptor import set_stream_interceptor
from bouzecode.backend.context_manager import ContextState
from bouzecode.backend.context_manager.compact_methodology import (
    CHARS_PER_TOKEN,
    LIVE_SNIPPET_TOKENS_THRESHOLD,
    NOTE_PROSE_TOKENS_THRESHOLD,
    maybe_compact,
)

#  Chemins RELATIFS : un chemin absolu vers un fichier absent est retire par la passe
#  mecanique AVANT le juge (`compact_snippets`). `C:/proj/...` n'etait absolu que sous Windows,
#  d'ou une suite verte sous Linux et rouge sous Windows.
FILES = [f"proj/module_{n}.py" for n in range(5)]


class FakeSession:
    """Le journal de la session, reduit a ce que la compaction ecrit.

    `timing_entries` reste present mais INERTE : depuis le passage aux seuils de
    matiere, le declencheur ne lit plus le prefixe cache. Il n'est conserve que
    parce que la passe prose journalise `cached_prefix_tokens` a titre de mesure.
    """

    def __init__(self, turn: int = 0):
        self.turn_count = turn
        self.compaction_log: list = []
        self.timing_entries = [{
            "phase": "llm", "in_tokens": 500,
            "cache_read_tokens": 0, "cache_creation_tokens": 0,
        }]


class Router:
    """Sert la reponse du juge ou celle du resumeur, selon le prompt recu.

    Les deux passes partagent le meme point d'interception : c'est le marqueur
    ``SNIPPETS IN MEMORY`` (present dans le seul prompt du juge) qui les
    distingue. Une `prose_answer` vide neutralise la passe prose, ce qui isole
    les caracteres retires par le juge.
    """

    def __init__(self, judge_answer: str = "", prose_answer: str = "", explode: bool = False):
        self.judge_answer, self.prose_answer = judge_answer, prose_answer
        self.explode, self.calls, self.prompts = explode, 0, []

    def __call__(self, _raw):
        def stream(model=None, system=None, messages=None, tool_schemas=None, config=None):
            prompt = messages[0]["content"]
            self.calls += 1
            self.prompts.append(prompt)
            if self.explode:
                raise ConnectionError("gateway indisponible")
            answer = self.judge_answer if "SNIPPETS IN MEMORY" in prompt else self.prose_answer
            yield StreamStarted()
            yield AssistantTurn(text=answer, tool_calls=[], in_tokens=0,
                                out_tokens=0, stop_reason="end_turn")
        return stream

    @property
    def judge_prompt(self) -> str:
        return next(p for p in self.prompts if "SNIPPETS IN MEMORY" in p)


@pytest.fixture
def router():
    def install(judge_answer: str = "", prose_answer: str = "", explode: bool = False) -> Router:
        spy = Router(judge_answer, prose_answer, explode)
        set_stream_interceptor(spy)
        return spy

    yield install
    set_stream_interceptor(None)


# ── La matiere, calibree sur les seuils du module ──────────────────────────────

_BODY_LINE = "     1\tdef entry():\n"

# De quoi franchir le seuil B a lui SEUL : un unique snippet lourd suffit, donc
# les deux autres restent courts. Gonfler les trois ferait une note de 800 000
# caracteres a decouper 14 fois pour exactement le meme contrat.
_HEAVY_LINES = int(LIVE_SNIPPET_TOKENS_THRESHOLD * CHARS_PER_TOKEN / len(_BODY_LINE)) + 200

_PROSE_LINE = "Constat : le parser lit le header avant le corps, et la doc en depend.\n"

# De quoi franchir le seuil A a lui seul : le bloc `## User` est EXCLU du compte
# de la prose compactable, la mission ne peut donc pas armer la passe a sa place.
_PROSE_REPEATS = int(NOTE_PROSE_TOKENS_THRESHOLD * CHARS_PER_TOKEN / len(_PROSE_LINE)) + 200


def _snippet(path: str, label: str, body_lines: int = 3) -> str:
    return (f'## snippet: {path} L1-3 — "{label}"\n'
            + _BODY_LINE * body_lines)


_LONG_PROSE = "".join(
    f"## Tour {n}\n" + _PROSE_LINE * (_PROSE_REPEATS // 6)
    for n in range(4, 10)
)


def _note(trailing_prose: str = "", heavy: bool = True) -> str:
    """La note de reference. `heavy` arme le seuil B via le corps du 1er snippet."""
    parts = [
        "## User\nRefactor the parser, then update the docs.\n",
        _snippet(FILES[0], "parser entry", _HEAVY_LINES if heavy else 3),
        "## Tour 3\nLe parser lit d'abord le header.\n",
        _snippet(FILES[1], "docs builder"),
        _snippet(FILES[2], "cli wiring"),
    ]
    if trailing_prose:
        parts.append(trailing_prose)
    return "\n".join(parts)


def _run(note: str, depth: int = 0, side_call: bool = False) -> tuple[ContextState, int]:
    state = ContextState(notes={"methodology": note})
    config = {"_state": FakeSession(), "_depth": depth}
    if side_call:
        config["_context_state"] = None
    return state, maybe_compact(state, "methodology", config)


def _listing(spy: Router) -> str:
    return spy.judge_prompt.split("SNIPPETS IN MEMORY")[1]


def _phases(state_log: list, phase: str) -> list[dict]:
    return [e for e in state_log if e.get("phase") == phase]


# ── Le declencheur : la matiere de la note, et rien d'autre ────────────────────

def test_a_small_note_pays_for_no_side_call(router):
    """Sous les deux seuils, la note est laissee telle quelle, sans aucun appel."""
    spy = router(judge_answer="DROP 1")
    note = _note(heavy=False)

    state, removed = _run(note)

    assert (removed, spy.calls) == (0, 0)
    assert state.notes["methodology"] == note


def test_a_heavy_snippet_load_triggers_the_judgement(router):
    """Au seuil B, le snippet designe par le modele laisse une pierre tombale."""
    spy = router(judge_answer="DROP 1")

    state, removed = _run(_note())

    note = state.notes["methodology"]
    assert spy.calls >= 1 and removed > 0
    assert "## snippet-dropped:" in note
    assert _snippet(FILES[0], "parser entry", _HEAVY_LINES) not in note
    # Les deux autres snippets survivent intacts : on compte les EN-TETES, pas
    # les lignes de corps (le corps du snippet lourd est une meme ligne repetee).
    assert note.count("## snippet: ") == 2
    assert FILES[1] in note and FILES[2] in note


def test_a_side_call_never_compacts_its_own_context(router):
    """`_context_state` a None : on est deja dans un side-call, aucune compaction imbriquee."""
    spy = router(judge_answer="DROP 1")

    _state, removed = _run(_note(), depth=1, side_call=True)

    assert (removed, spy.calls) == (0, 0)


def test_an_empty_note_is_not_worth_a_call(router):
    spy = router(judge_answer="DROP 1")

    _state, removed = _run("")

    assert (removed, spy.calls) == (0, 0)


def test_a_note_without_config_is_left_alone(router):
    """Sans config il n'y a ni journal ni garde de profondeur : on ne touche a rien."""
    spy = router(judge_answer="DROP 1")
    state = ContextState(notes={"methodology": _note()})

    assert maybe_compact(state, "methodology", None) == 0
    assert spy.calls == 0


# ── Ce que le modele recoit : tous les snippets, aucun pre-filtrage ────────────

def test_every_snippet_is_offered_including_the_freshest(router):
    """Plus de snippet protege : les trois sont soumis au jugement du modele."""
    spy = router(judge_answer="")

    _run(_note())

    listing = _listing(spy)
    for path in FILES[:3]:
        assert path in listing


def test_a_file_mentioned_again_later_is_still_offered(router):
    """Un chemin re-cite dans la prose n'est plus garde d'office."""
    spy = router(judge_answer="")

    _run(_note(f"## Tour 9\nJe reviens sur {FILES[0]} pour le fix.\n"))

    assert FILES[0] in _listing(spy)


def test_the_judge_reads_headers_but_never_snippet_bodies(router):
    """Envoyer le code gele couterait plus cher que le gain : headers seuls."""
    spy = router(judge_answer="")

    _run(_note())

    assert "def entry():" not in spy.judge_prompt


def test_the_mission_travels_with_the_question(router):
    spy = router(judge_answer="")

    _run(_note())

    assert "Refactor the parser" in spy.judge_prompt


# ── Robustesse et journalisation ──────────────────────────────────────────────

def test_a_provider_failure_leaves_the_note_untouched(router):
    """Une panne de gateway ne doit jamais couter la memoire de l'agent."""
    router(explode=True)
    note = _note()

    state, removed = _run(note)

    assert (removed, state.notes["methodology"]) == (0, note)


def test_a_silent_model_keeps_everything(router):
    """Aucune ligne DROP : tout est conserve, y compris la prose."""
    router(judge_answer="", prose_answer="")
    note = _note()

    state, removed = _run(note)

    assert (removed, state.notes["methodology"]) == (0, note)


def test_the_verdict_is_journalled_with_its_control_group(router):
    """Les gardes sont journalises a cote des supprimes : c'est le temoin."""
    router(judge_answer="DROP 2")
    state = ContextState(notes={"methodology": _note()})
    session = FakeSession()

    maybe_compact(state, "methodology", {"_state": session, "_depth": 0})

    entry = _phases(session.compaction_log, "note_deep_compaction")[0]
    assert entry["dropped"] == [FILES[1]]
    assert entry["kept"] == [FILES[0], FILES[2]]
    assert entry["chars_removed"] > 0


def test_a_removal_invalidates_the_cached_note_snapshot(router):
    """Toute suppression casse le prefixe cache : le snapshot doit tomber."""
    router(judge_answer="DROP 1")
    state = ContextState(notes={"methodology": _note()})
    state._methodology_cache_snapshot = "stale snapshot"

    removed = maybe_compact(state, "methodology",
                            {"_state": FakeSession(), "_depth": 0})

    assert removed > 0
    assert state._methodology_cache_snapshot is None


def test_a_barren_verdict_is_not_asked_again(router):
    """Meme jeu de snippets, deja juge, rien supprime : on ne repose pas la question.

    Le declencheur est un NIVEAU (matiere au-dessus du seuil), pas un evenement :
    une fois franchi il l'est a chaque tour. Mesure du 2026-08-22 sur 425 tours :
    431 passes du juge pour 89 suppressions utiles — 342 appels pour un verdict deja
    rendu. Tant que le jeu de snippets ne bouge pas, la reponse ne peut pas changer.

    Ici la premiere passe replie la prose (seuil A) sans rien couper cote snippets ;
    le seuil B reste donc franchi au tour suivant, et c'est bien le souvenir du
    verdict sterile — pas la retombee sous un seuil — qui evite le second appel."""
    spy = router(judge_answer="KEEP ALL", prose_answer="Mission en cours : refactorer le parser.")
    state = ContextState(notes={"methodology": _note(_LONG_PROSE)})
    cfg = {"_state": FakeSession(), "_depth": 0}

    maybe_compact(state, "methodology", cfg)
    maybe_compact(state, "methodology", cfg)

    juges = [p for p in spy.prompts if "SNIPPETS IN MEMORY" in p]
    assert len(juges) == 1, f"le juge a ete interroge {len(juges)} fois pour un jeu inchange"


def test_a_silent_or_cut_judge_is_not_a_verdict_and_is_asked_again(router):
    """Une reponse vide (ou coupee) n'est pas « tout garder » : pas de memo, on redemande.

    Rejeu du 2026-09-24 sur DeepSeek : le juge epuisait son budget a raisonner, rendait
    un texte vide, et ce silence etait memorise comme verdict — plus jamais repose."""
    spy = router(judge_answer="", prose_answer="Mission en cours : refactorer le parser.")
    state = ContextState(notes={"methodology": _note(_LONG_PROSE)})
    cfg = {"_state": FakeSession(), "_depth": 0}

    maybe_compact(state, "methodology", cfg)
    maybe_compact(state, "methodology", cfg)

    juges = [p for p in spy.prompts if "SNIPPETS IN MEMORY" in p]
    assert len(juges) == 2


def test_both_passes_run_in_the_same_compaction(router):
    """Le juge coupe les snippets, le resumeur reecrit la prose : un seul tour.

    La note porte ici de VRAIS tours de prose, assez pour franchir le seuil A :
    depuis 2026-08-21 la passe prose ne depense un appel que s'il y a de la matiere
    neuve a replier, et la mission (`## User`) n'en fait pas partie."""
    router(judge_answer="DROP 1", prose_answer="Mission en cours : refactorer le parser.\n- parser: le header d'abord.")
    state = ContextState(notes={"methodology": _note(_LONG_PROSE)})
    session = FakeSession()

    removed = maybe_compact(state, "methodology", {"_state": session, "_depth": 0})

    note = state.notes["methodology"]
    assert removed > 0
    juge = _phases(session.compaction_log, "note_deep_compaction")[0]
    assert juge["chars_removed"] > 0, "le juge n'a pas coupe : rien a enterrer"
    # La pierre tombale du juge est de la MATIERE pour la passe prose, pas un
    # residu permanent : elle entre dans le resume et disparait de la note. Ce
    # test exigeait l'inverse, ce qui figeait le defaut mesure le 2026-08-23
    # (88 pierres tombales, 37,8 % d'une note de 116 549 caracteres, jamais
    # retirees par aucune des deux passes).
    assert "## snippet-dropped:" not in note
    assert "## compacted-history" in note
    assert _phases(session.compaction_log, "note_deep_compaction")
    assert _phases(session.compaction_log, "note_prose_compaction")
