# [desc] Tests de la passe prose : la reflexion de la note est resumee par le modele en un bloc compacted-history [/desc]
"""La passe prose de la compaction de note.

Le juge des snippets ne touche jamais les blocs de prose, or cette prose EST la
note sur une longue session. Cette passe la confie au modele et la remplace par
un unique bloc `## compacted-history`.

Il n'y a plus de plancher de taille, de ratio de rentabilite ni d'entrees
recentes protegees : quand la compaction se declenche, c'est le modele qui
decide de ce qui merite d'etre garde.

Trois protections demeurent : une reponse vide ou une panne laisse la note
intacte ; le bloc `## User` (la mission) n'est jamais resume, seulement passe
en contexte ; et une passe qui n'a rien de neuf a replier ne coute pas d'appel.
"""
from __future__ import annotations

import pytest

from bouzecode.backend.agent.providers import AssistantTurn, StreamStarted
from bouzecode.backend.agent.stream_interceptor import set_stream_interceptor
from bouzecode.backend.context_manager.compact_prose import (
    _MAX_ATTEMPTS,
    SUMMARY_HEADER,
    compact_prose,
)


def texte(contenu) -> str:
    """Le contenu envoye au modele, a plat.

    C'est une LISTE de blocs depuis que le materiau a compacter porte le point de
    cesure du cache : le premier bloc est ce materiau, les suivants sont les
    relances. Les tests raisonnent sur le tout."""
    if isinstance(contenu, str):
        return contenu
    return "\n".join(b.get("text", "") for b in contenu)


class FakeSession:
    """Le journal de la session, reduit a ce que la passe ecrit."""

    def __init__(self, turn: int = 0):
        self.turn_count = turn
        self.compaction_log: list = []


class FakeState:
    def __init__(self):
        self.notes: dict = {}


class Model:
    """Sert la reponse du modele via le point d'interception officiel."""

    def __init__(self, answer: str, explode: bool = False):
        self.answer, self.explode, self.calls, self.prompts = answer, explode, 0, []

    def __call__(self, _raw):
        def stream(model=None, system=None, messages=None, tool_schemas=None, config=None):
            self.calls += 1
            self.prompts.append(messages[0]["content"])
            if self.explode:
                raise ConnectionError("gateway indisponible")
            yield StreamStarted()
            yield AssistantTurn(text=self.answer, tool_calls=[], in_tokens=0,
                                out_tokens=0, stop_reason="end_turn")
        return stream


@pytest.fixture
def model():
    def install(answer: str, explode: bool = False) -> Model:
        spy = Model(answer, explode)
        set_stream_interceptor(spy)
        return spy

    yield install
    set_stream_interceptor(None)


SNIPPET = ('## snippet: C:/proj/parser.py L1-3 — "entry"\n'
           "     1\tdef parse():\n"
           "     2\t    return 1\n"
           "     3\t# end")

PROSE_ENTRIES = [
    f"## Tour {n}\n" + f"Constat {n} : le parser lit le header en premier. " * 12
    for n in range(1, 7)
]

SUMMARY = ("Mission en cours : refactorer le parser.\n"
           "- parser: header lu en premier, decision gardee.\n"
           "- prochaine etape: docs.")


def _note() -> str:
    return "\n".join(["## User\nRefactor the parser.", *PROSE_ENTRIES, SNIPPET])


def _config(session: FakeSession) -> dict:
    return {"_state": session, "_depth": 0}


def _entry(session: FakeSession) -> dict:
    return next(e for e in session.compaction_log
                if e.get("phase") == "note_prose_compaction")


class TokenModel:
    """Comme ``Model``, mais la reponse porte une consommation NON NULLE.

    Le stub ordinaire annonce 0 token partout, ce qui ne peut pas prouver que la
    passe journalise ce que ses tentatives ont coute."""

    def __init__(self, answer: str):
        self.answer, self.calls = answer, 0

    def __call__(self, _raw):
        def stream(model=None, system=None, messages=None, tool_schemas=None, config=None):
            self.calls += 1
            yield StreamStarted()
            yield AssistantTurn(text=self.answer, tool_calls=[], in_tokens=1200,
                                out_tokens=300, cache_read_tokens=9000,
                                cache_creation_tokens=100, stop_reason="end_turn")
        return stream


def test_an_attempt_that_does_not_shorten_stops_the_loop():
    """Deux reponses de meme longueur hors plafond: la troisieme est inutile.

    Le modele a montre son plancher. Redemander une fois de plus paie un appel
    pour une longueur deja connue -- 78 % des passes mesurees le 2026-08-25
    refusaient apres avoir paye leurs trois tentatives."""
    session = FakeSession()
    note = _note()
    # Une reponse aussi longue que son entree: toujours au-dessus du plafond.
    spy = TokenModel("Mission en cours : refactorer le parser.\n" + note)
    set_stream_interceptor(spy)
    try:
        out, removed = compact_prose(note, FakeState(), _config(session))
    finally:
        set_stream_interceptor(None)

    assert spy.calls == 2, "la 3e tentative ne raccourcirait rien"
    assert spy.calls < _MAX_ATTEMPTS
    # Un resume hors plafond ne rentre jamais dans la note.
    assert (out, removed) == (note, 0)


def test_the_journal_carries_what_each_attempt_cost():
    """Sans les tokens par tentative, un refus reste indiagnosticable.

    Et sans ``trigger_prose_tokens`` / ``cached_prefix_tokens`` on ne peut pas
    dire ce qui a arme la passe, ni ce que l'ancien declencheur aurait vu."""
    session = FakeSession()
    session.timing_entries = [{
        "phase": "llm", "in_tokens": 500,
        "cache_read_tokens": 41_000, "cache_creation_tokens": 0,
    }]
    spy = TokenModel(SUMMARY)
    set_stream_interceptor(spy)
    try:
        compact_prose(_note(), FakeState(), _config(session))
    finally:
        set_stream_interceptor(None)

    entry = _entry(session)
    assert entry["attempts"] == 1
    assert entry["attempt_tokens"] == [{
        "in_tokens": 1200, "out_tokens": 300,
        "cache_read_tokens": 9000, "cache_creation_tokens": 100,
    }]
    assert entry["trigger_prose_tokens"] > 0
    assert entry["cached_prefix_tokens"] == 41_000


# ── Ce que la passe produit ───────────────────────────────────────────────────

def test_the_prose_becomes_one_synthesis_block(model):
    spy = model(SUMMARY)
    session = FakeSession()

    new_note, removed = compact_prose(_note(), FakeState(), _config(session))

    assert spy.calls == 1 and removed > 0
    assert SUMMARY_HEADER in new_note
    assert "parser: header lu en premier" in new_note
    assert "Constat 1 :" not in new_note


def test_the_snippets_are_left_to_the_judge(model):
    """La passe prose ne touche jamais un bloc snippet."""
    model(SUMMARY)

    new_note, _removed = compact_prose(_note(), FakeState(), _config(FakeSession()))

    assert SNIPPET in new_note


def test_snippet_bodies_are_never_sent_to_the_model(model):
    spy = model(SUMMARY)

    compact_prose(_note(), FakeState(), _config(FakeSession()))

    assert "def parse():" not in texte(spy.prompts[0])


def test_the_prose_is_summarisable_and_the_recent_entries_are_not_spared(model):
    """Plus d'entrees recentes protegees : le dernier tour part au resume."""
    spy = model(SUMMARY)

    compact_prose(_note(), FakeState(), _config(FakeSession()))

    assert "## Tour 6" in texte(spy.prompts[0])


def test_the_mission_survives_as_a_statement_not_as_raw_text(model):
    """Ce qui doit survivre, c'est le BUT — pas le libelle du message.

    Incident du 2026-08-21 : un agent a vu son enonce disparaitre en cours de route
    et a du s'arreter pour demander ce qu'il devait livrer. La parade a d'abord ete
    de garder les blocs `## User` verbatim, ce qui les entassait toute la session.
    Desormais ils se compactent comme le reste, et c'est la ligne `Mission en cours :`
    qui porte la garantie."""
    model(SUMMARY)

    new_note, _removed = compact_prose(_note(), FakeState(), _config(FakeSession()))

    assert "Mission en cours : refactorer le parser." in new_note
    assert "## User\nRefactor the parser." not in new_note   # compacte, pas recopie


def test_a_summary_without_the_mission_is_sent_back_then_salvaged(model):
    """On redemande trois fois la ligne d'ouverture, puis on l'ECRIT plutot que de jeter.

    Les deux tests de sortie ne meritent pas la meme sanction. Depasser le plafond
    est un echec de compaction : rien a sauver. Omettre la ligne d'ouverture n'en est
    pas un : le resume est bon, il lui manque une phrase que la passe sait ecrire
    elle-meme depuis le bloc `## User` qu'elle a deja en main.

    Mesure du 2026-08-23 (agent f52cb5297f4f) : aux tours 128-130 la passe rendait
    6 565 / 5 243 / 6 728 caracteres pour des plafonds de 20 441 / 20 913 / 21 234 —
    un facteur 17, dans le budget trois fois sur trois — et les trois ont ete jetees
    faute de cette seule ligne. Rejoue hors ligne sur la meme entree, le modele la
    produisait une fois sur trois : le portillon n'est pas fiable, et il coutait la
    totalite du gain."""
    spy = model("- parser: header lu en premier.")      # court, mais sans la mission
    note = _note()

    new_note, removed = compact_prose(note, FakeState(), _config(FakeSession()))

    assert spy.calls == _MAX_ATTEMPTS
    assert "DID NOT OPEN WITH THE MISSION" in texte(spy.prompts[-1])
    assert removed > 0, "un resume dans le plafond ne doit plus etre jete"
    assert "Mission en cours : Refactor the parser." in new_note
    assert "- parser: header lu en premier." in new_note


def test_the_mission_is_given_to_the_model_as_context(model):
    """Non resumee, mais presente : le resume doit rester oriente vers le but."""
    spy = model(SUMMARY)

    compact_prose(_note(), FakeState(), _config(FakeSession()))

    prompt = texte(spy.prompts[0])
    assert "MISSION" in prompt and "Refactor the parser." in prompt


def test_a_pass_with_nothing_new_costs_no_call(model):
    """Replier son propre resume sans prose neuve, c'est payer pour rien.

    Mesure du 2026-08-21 : 11 des ~20 passes d'une session ont retire 0 ou 1
    caractere, chacune au prix d'un appel complet au modele."""
    spy = model(SUMMARY)
    note = (f"{SUMMARY_HEADER} (12 entries compacted, 30000 chars -> 7189)\n\n"
            + "x" * 7189 + "\n## Tour 7\nune ligne.\n")

    new_note, removed = compact_prose(note, FakeState(), _config(FakeSession()))

    assert (removed, spy.calls, new_note) == (0, 0, note)


def test_an_already_compacted_history_can_be_compacted_again(model):
    """Une note deja resumee redevient candidate : plus d'exception d'historique."""
    spy = model(SUMMARY)
    note = f"{SUMMARY_HEADER} (3 entries compacted, 900 chars -> 120)\n\nvieux resume\n"

    _new_note, removed = compact_prose(note + "\n".join(PROSE_ENTRIES),
                                       FakeState(), _config(FakeSession()))

    assert spy.calls == 1 and removed > 0
    assert "vieux resume" in texte(spy.prompts[0])


def test_a_note_made_only_of_snippets_costs_no_call(model):
    spy = model(SUMMARY)

    new_note, removed = compact_prose(SNIPPET, FakeState(), _config(FakeSession()))

    assert (removed, spy.calls, new_note) == (0, 0, SNIPPET)


# ── Ce qui protege la note ────────────────────────────────────────────────────

def test_an_empty_answer_leaves_the_note_untouched(model):
    """Reecrire la note avec rien effacerait la memoire de l'agent."""
    model("   ")
    note = _note()
    session = FakeSession()

    new_note, removed = compact_prose(note, FakeState(), _config(session))

    assert (removed, new_note) == (0, note)
    assert _entry(session)["chars_removed"] == 0


def test_the_material_to_compact_stays_in_cache_across_attempts(model):
    """Une tentative de plus ne doit PAS re-envoyer le materiau.

    C'est ce qui rend le reessai abordable : le bloc a compacter porte le point de
    cesure du cache et ne bouge pas d'un appel a l'autre, donc il est relu a 0,1x ;
    seuls la tentative ratee et le nombre de caracteres a couper sont des tokens
    neufs. Sans ca, redemander couterait un prefixe entier a chaque fois."""
    entree = "\n".join(PROSE_ENTRIES)
    spy = model("Mission en cours : refactorer le parser.\n" + "x" * int(len(entree) * 0.3))   # au-dessus du plafond

    compact_prose(_note(), FakeState(), _config(FakeSession()))

    # Une de moins que le plafond : la reponse ne raccourcit pas d'un appel a
    # l'autre, donc la boucle s'arrete des qu'elle l'a constate (voir
    # `test_an_attempt_that_does_not_shorten_stops_the_loop`).
    assert spy.calls == _MAX_ATTEMPTS - 1
    premiers = [contenu[0] for contenu in spy.prompts]
    # Le bloc cache est identique a chaque tentative, et c'est lui qui porte la cesure.
    assert all(b == premiers[0] for b in premiers)
    assert premiers[0]["cache_control"] == {"type": "ephemeral"}
    # Le materiau n'est PAS re-envoye dans les blocs de relance.
    relances = [b for contenu in spy.prompts[1:] for b in contenu[1:]]
    assert relances, "une relance doit porter au moins un bloc"
    assert all("cache_control" not in b for b in relances)
    assert all("## Tour 1" not in b["text"] for b in relances)


def test_a_summary_at_thirty_percent_is_refused(model):
    """Le plafond est a 20 % : 30 % ne passe plus.

    Ce cas serait passe tant que le plafond etait a 50 %. Il epingle la valeur
    demandee le 2026-08-23 : compacter a 20 %, pas a 50."""
    entree = "\n".join(PROSE_ENTRIES)
    spy = model("Mission en cours : refactorer le parser.\n" + "x" * int(len(entree) * 0.3))
    note = _note()

    new_note, removed = compact_prose(note, FakeState(), _config(FakeSession()))

    assert (removed, new_note) == (0, note)
    # On redemande de compacter, on n'abandonne pas — mais on s'arrete a la
    # deuxieme tentative, la longueur rendue n'ayant pas bouge.
    assert spy.calls == _MAX_ATTEMPTS - 1
    assert "Compact it FURTHER" in texte(spy.prompts[-1])


def test_a_summary_that_keeps_too_much_is_refused(model):
    """Garder 80 % de son entree n'est pas compacter.

    La note vit dans le prefixe cache : la reecrire force une regravure complete.
    Une passe qui ne gagne que 20 % coute donc plus qu'elle ne rapporte, et l'ancien
    code l'acceptait — mesure du 2026-08-22 : 83 % de retention en mediane, note montee
    a 79 000 tokens malgre 418 passes. Refuser laisse la note intacte, donc SANS
    invalider le cache."""
    entree = "\n".join(PROSE_ENTRIES)
    spy = model("Mission en cours : refactorer le parser.\n" + "x" * int(len(entree) * 0.8))
    note = _note()
    session = FakeSession()

    new_note, removed = compact_prose(note, FakeState(), _config(session))

    assert (removed, new_note) == (0, note)
    # Chaque tentative redemande de couper davantage, jusqu'a ce que le modele
    # rende deux fois la meme longueur : la troisieme serait payee pour rien.
    assert spy.calls == _MAX_ATTEMPTS - 1
    assert _entry(session)["chars_removed"] == 0


def test_a_summary_longer_than_the_prose_is_refused(model):
    """Un resume plus gros que l'original ne rembourse pas le cache_create."""
    model("x" * 20_000)
    note = _note()

    new_note, removed = compact_prose(note, FakeState(), _config(FakeSession()))

    assert (removed, new_note) == (0, note)


def test_a_provider_failure_never_raises(model):
    model("", explode=True)
    note = _note()

    new_note, removed = compact_prose(note, FakeState(), _config(FakeSession()))

    assert (removed, new_note) == (0, note)


# ── Journalisation ────────────────────────────────────────────────────────────

def test_the_attempt_is_journalled(model):
    model(SUMMARY)
    session = FakeSession(turn=42)

    _new_note, removed = compact_prose(_note(), FakeState(), _config(session))

    entry = _entry(session)
    assert entry["turn"] == 42
    assert entry["chars_removed"] == removed
    assert entry["blocks_summarised"] == len(PROSE_ENTRIES) + 1  # + le bloc `## User`
    assert entry["summary_chars"] == len(SUMMARY)


def test_a_successful_pass_is_counted_on_the_state(model):
    model(SUMMARY)
    state = FakeState()

    compact_prose(_note(), state, _config(FakeSession()))

    assert state._prose_compactions == 1


# ── Le budget de sortie de l'appel ────────────────────────────────────────────

class ConfigSpy:
    """Capture la CONFIG que la passe envoie au modele, appel par appel.

    C'est la seule facon de voir le budget de sortie reellement demande : il est
    pose par la passe elle-meme, juste avant l'appel."""

    def __init__(self, answer: str):
        self.answer, self.configs = answer, []

    def __call__(self, _raw):
        def stream(model=None, system=None, messages=None, tool_schemas=None, config=None):
            self.configs.append(dict(config or {}))
            yield StreamStarted()
            yield AssistantTurn(text=self.answer, tool_calls=[], in_tokens=0,
                                out_tokens=0, stop_reason="end_turn")
        return stream


# ~3,5 caracteres par token : ce qu'il faut pour convertir un plafond exprime en
# CARACTERES (le ceiling) en budget de sortie exprime en TOKENS.
CHARS_PAR_TOKEN = 3.5


def _grosse_note() -> tuple[str, int]:
    """Une note dont le plafond de resume depasse 4096 tokens, avec ce plafond.

    30 entrees de 4 000 caracteres : le plafond a 20 % vaut ~24 000 caracteres,
    soit ~7 000 tokens a ecrire. Une session longue y arrive naturellement."""
    entrees = [f"## Tour {n}\n" + f"Constat {n} : le parser lit le header. " * 100
               for n in range(1, 31)]
    mission = "## User\nRefactor the parser."
    note = "\n".join([mission, *entrees])
    ceiling = int((len(mission) + sum(len(e) for e in entrees)) * 0.2)
    return note, ceiling


def test_the_answer_budget_follows_the_ceiling():
    """Le budget de sortie doit permettre d'ECRIRE un resume au plafond.

    Le plafond fonctionnel de la passe est `_MAX_SUMMARY_RATIO` (20 % de l'entree,
    en caracteres), pas un nombre de tokens fixe. Avec 4096 tokens en dur, toute
    note dont la prose depasse ~72 000 caracteres voyait ses TROIS tentatives
    coupees par le fournisseur avant d'atteindre le plafond -- trois appels payes
    pour un refus mecanique, et un warning `stop_reason=max_tokens` qui accusait
    a tort le tour de l'agent."""
    note, ceiling = _grosse_note()
    spy = ConfigSpy(SUMMARY)
    set_stream_interceptor(spy)
    try:
        compact_prose(note, FakeState(), _config(FakeSession()))
    finally:
        set_stream_interceptor(None)

    assert spy.configs, "la passe doit avoir appele le modele"
    budget = spy.configs[0]["max_tokens"]
    assert budget >= ceiling / CHARS_PAR_TOKEN, (
        f"budget {budget} tokens trop court pour ecrire {ceiling} caracteres")


def test_the_answer_budget_never_exceeds_the_session_budget():
    """Le side-call ne demande jamais plus que le budget de la session."""
    note, _ceiling = _grosse_note()
    spy = ConfigSpy(SUMMARY)
    set_stream_interceptor(spy)
    try:
        compact_prose(note, FakeState(),
                      {**_config(FakeSession()), "max_tokens": 8000})
    finally:
        set_stream_interceptor(None)

    assert spy.configs[0]["max_tokens"] <= 8000


def test_the_side_call_says_who_it_is():
    """Un appel annexe doit se nommer, sinon sa troncature accuse l'agent.

    Incident du 2026-09-09 : l'utilisateur a lu `stop_reason=max_tokens (cap=4096)`
    et a cru son propre tour coupe, alors que son tour disposait de 64 000 tokens.
    Le message venait de cette passe. Sans etiquette, le warning ne peut pas dire
    quel appel a ete tronque -- ni que relever `config['max_tokens']` n'y changera
    rien, la passe ecrasant cette valeur juste avant d'appeler."""
    spy = ConfigSpy(SUMMARY)
    set_stream_interceptor(spy)
    try:
        compact_prose(_note(), FakeState(), _config(FakeSession()))
    finally:
        set_stream_interceptor(None)

    label = spy.configs[0].get("_call_label", "")
    assert label, "l'appel annexe doit porter un libelle"
    assert "compact" in label.lower()
