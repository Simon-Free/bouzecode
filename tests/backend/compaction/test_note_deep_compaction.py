# [desc] The judged compaction pass: rare, snippet-only, tombstoned, idempotent. [/desc]
"""La compaction profonde de la note : rare, ciblée, et jamais muette.

Toute suppression paie un `cache_create` complet, donc elle se déclenche sur la
**taille du préfixe caché** — ce que la re-création coûterait vraiment.

L'asymétrie qui règle tout : un snippet perdu à tort coûte une relecture, une
décision perdue à tort coûte une boucle. Seuls les blocs `## snippet:` sont
candidats ; la prose et les snippets les plus frais ne le sont jamais.
"""
from __future__ import annotations

import pytest

from bouzecode.backend.agent.providers.types import AssistantTurn, StreamStarted
from bouzecode.backend.agent.stream_interceptor import set_stream_interceptor
from bouzecode.backend.context_manager import ContextState
from bouzecode.backend.context_manager.compact_methodology import maybe_compact

FILES = [f"C:/proj/module_{n}.py" for n in range(5)]


class FakeSession:
    """Le journal de la session, réduit à ce que le déclencheur lit."""

    def __init__(self, cached_tokens: int, turn: int = 0):
        self.turn_count = turn
        self.compaction_log: list = []
        self.timing_entries = [{
            "phase": "llm", "in_tokens": 500,
            "cache_read_tokens": cached_tokens, "cache_creation_tokens": 0,
        }]


class Judge:
    """Sert la réponse du juge via le point d'interception officiel."""

    def __init__(self, answer: str, explode: bool = False):
        self.answer, self.explode, self.calls, self.prompts = answer, explode, 0, []

    def __call__(self, _raw):
        def stream(model=None, system=None, messages=None, tool_schemas=None, config=None):
            self.calls += 1
            self.prompts.append(messages[0]["content"])
            if self.explode:
                raise ConnectionError("passerelle indisponible")
            yield StreamStarted()
            yield AssistantTurn(text=self.answer, tool_calls=[], in_tokens=0,
                                out_tokens=0, stop_reason="end_turn")
        return stream


@pytest.fixture
def judge():
    def install(answer: str, explode: bool = False) -> Judge:
        spy = Judge(answer, explode)
        set_stream_interceptor(spy)
        return spy

    yield install
    set_stream_interceptor(None)


DECISION = ("## Tour 4 — piste abandonnée\n"
            "J'ai essayé de passer par le cache disque : ça échoue, le lock est repris "
            "par le reaper. Ne pas recommencer.\n")


def _snippet(path: str, label: str, lines: int = 450) -> str:
    body = "\n".join(f"{i:>5}  code_{i} = {i}" for i in range(1, lines + 1))
    return f'## snippet: {path} L1-{lines} — "{label}"\n{body}'


def _note() -> str:
    blocks = ["## User @2026-07-28 10:00:00\nRépare le bouton reprendre."]
    for n, path in enumerate(FILES):
        blocks.append(_snippet(path, f"lecture {n}"))
        if n == 1:
            blocks.append(DECISION)
    return "\n\n".join(blocks)


def _run(note: str, cached_tokens: int, turn: int = 0) -> tuple[ContextState, int]:
    state = ContextState(notes={"methodology": note})
    removed = maybe_compact(state, "methodology",
                            {"_state": FakeSession(cached_tokens, turn)})
    return state, removed


def _listing(spy: Judge) -> str:
    return spy.prompts[0].split("SNIPPETS IN MEMORY")[1]


def test_a_cheap_cached_prefix_is_left_alone(judge):
    """Sous le seuil de préfixe caché, aucune compaction et aucun appel au juge."""
    spy = judge("DROP 1\nDROP 2")
    state, removed = _run(_note(), cached_tokens=10_000)

    assert removed == 0
    assert spy.calls == 0
    assert state.notes["methodology"] == _note()


def test_an_expensive_cached_prefix_drops_what_the_judge_names(judge):
    """Au-delà du seuil, le snippet désigné part et laisse une pierre tombale."""
    judge("DROP 1")
    state, removed = _run(_note(), cached_tokens=60_000)
    note = state.notes["methodology"]

    assert removed > 0
    assert "## snippet-dropped:" in note
    assert FILES[0] in note, "la pierre tombale doit nommer le fichier à relire"
    assert "Re-run Snippet" in note, "et dire comment le récupérer"
    assert f'{FILES[0]} L1-450 — "lecture 0"\n  ' not in note, "le corps doit avoir disparu"


def test_decisions_and_the_user_request_are_never_candidates(judge):
    """Le juge a beau tout vouloir jeter : la prose et la demande initiale restent."""
    spy = judge("\n".join(f"DROP {n}" for n in range(1, 10)))
    state, _removed = _run(_note(), cached_tokens=60_000)
    note = state.notes["methodology"]

    assert "Ne pas recommencer." in note
    assert "Répare le bouton reprendre." in note
    assert "piste abandonnée" not in _listing(spy), "la prose n'est pas proposée au juge"


def test_the_freshest_snippets_are_never_offered(judge):
    """Un snippet tout juste posé n'est jamais candidat — sinon on mange la mémoire fraîche."""
    spy = judge("")
    _run(_note(), cached_tokens=60_000)

    listing = _listing(spy)
    assert FILES[0] in listing and FILES[1] in listing
    for recent in FILES[2:]:
        assert recent not in listing, "les 3 derniers snippets sont protégés"


def test_a_file_the_agent_came_back_to_is_protected_from_the_judge(judge):
    """Un fichier renommé plus loin dans la note n'est même pas soumis au juge."""
    note = _note() + f"\n\n## Tour 9 — je retourne dans {FILES[0]} pour le correctif\n"
    spy = judge("DROP 1")
    _run(note, cached_tokens=60_000)

    listing = _listing(spy)
    assert FILES[0] not in listing, "un snippet re-cité plus tard n'est jamais candidat"
    assert FILES[1] in listing


def test_a_second_pass_does_not_keep_whittling_the_note(judge):
    """Idempotence : ce que le juge a vu et gardé n'est jamais rejugé."""
    judge("")  # le juge garde tout
    state, first = _run(_note(), cached_tokens=60_000, turn=10)
    after_first = state.notes["methodology"]

    spy = judge("DROP 1\nDROP 2")
    second = maybe_compact(state, "methodology", {"_state": FakeSession(60_000, turn=200)})

    assert first == 0
    assert second == 0
    assert spy.calls == 0, "plus aucun candidat : le juge n'est même pas rappelé"
    assert state.notes["methodology"] == after_first


def test_two_compactions_are_spaced_by_a_break_even(judge):
    """Compacter deux fois de suite ne rembourserait jamais le premier cache_create."""
    spy = judge("")
    state, _ = _run(_note(), cached_tokens=60_000, turn=10)
    maybe_compact(state, "methodology", {"_state": FakeSession(60_000, turn=12)})

    assert spy.calls == 1, "deux tours plus tard, on ne rappelle pas le juge"


def test_the_verdict_is_journalled_with_its_own_control_group(judge):
    """La session garde qui a été jeté ET qui a été gardé, sous les mêmes critères.

    C'est le signal de vérification : si les chemins jetés sont relus plus
    souvent que les chemins gardés dans les tours suivants, la compaction est
    trop agressive — et cela se mesure dans les logs de session.
    """
    judge("DROP 1")
    session = FakeSession(60_000, turn=7)
    state = ContextState(notes={"methodology": _note()})
    maybe_compact(state, "methodology", {"_state": session})

    entry = next(e for e in session.compaction_log
                 if e.get("phase") == "note_deep_compaction")
    assert entry["turn"] == 7
    assert entry["dropped"] == [FILES[0]]
    assert entry["kept"] == [FILES[1]], "le groupe témoin est enregistré lui aussi"
    assert entry["chars_removed"] > 0


def test_a_provider_failure_leaves_the_note_intact(judge):
    """Une passerelle en panne ne doit jamais abîmer la mémoire de travail."""
    judge("", explode=True)
    state, removed = _run(_note(), cached_tokens=60_000)

    assert removed == 0
    assert state.notes["methodology"] == _note()
