"""Regression: a model that recites an injected reminder must not have that recitation
reach the consumers as its own text.

Focus conversation ba0d2431 (2026-08-17): the model opened each turn with
`<thinking>` and then copied the reminder from the very `<thinking>` the reminder
cites, so both Focus's event bridge and bouzecode's own ThinkingStreamParser
opened a reasoning block on it. All 20 turns persisted the turn protocol instead
of the reasoning. 19 of the 20 reproduced the reminder's 1271 trailing characters
byte for byte; the 20th wrote "par FinalAnswer" for "via FinalAnswer" — a model
paraphrasing, which is what rules out a code path as the source.
"""

from bouzecode.backend.agent.providers.backends.prompt_echo import drop_prompt_echo
from bouzecode.backend.agent.providers.types import TextChunk, ToolCallParsed

# Extrait du rappel injecté à l'époque (le rappel frais a été retiré le 2026-10-05) : le
# garde-fou reste branché sur dispatch pour tout texte qu'on injecterait à l'avenir.
INJECTED_REMINDER = (
    "[RAPPEL — à chaque tour]\n"
    "Format de CHAQUE tour : <thinking>court</thinking> puis les outils.\n"
    "Structure de CHAQUE tour, dans l'ordre, en UN seul batch :\n"
    "  1. Methodology EN PREMIER, à CHAQUE tour SANS EXCEPTION.\n"
    "PARALLÉLISE l'indépendant : N actions sans dépendance → N tool_use en UN tour.\n"
    "Clôture uniquement via FinalAnswer(...)."
)
REAL_THINKING = "\n<thinking>\n  L'utilisateur veut corriger sa requête SQL.\n</thinking>\n"
# Ce que le modèle a réellement émis : la balise, puis la copie du rappel à
# partir de l'endroit où cette balise apparaît dedans, puis son vrai raisonnement.
RECITED = INJECTED_REMINDER[INJECTED_REMINDER.find("<thinking>"):]


def text_of(*chunks: str, texts=(INJECTED_REMINDER,)) -> str:
    events = (TextChunk(c) for c in chunks)
    return "".join(e.text for e in drop_prompt_echo(events, texts))


def test_the_recited_reminder_is_dropped():
    kept = text_of(RECITED + REAL_THINKING)
    assert "Structure de CHAQUE tour" not in kept
    assert "Methodology EN PREMIER" not in kept
    assert "PARALLÉLISE l'indépendant" not in kept


def test_the_real_reasoning_survives():
    kept = text_of(RECITED + REAL_THINKING)
    assert "L'utilisateur veut corriger sa requête SQL." in kept
    assert "<thinking>" in kept


def test_ordinary_text_passes_through_untouched():
    answer = "Voici la correction : ajoute t.TRAIN_NO au GROUP BY.\nC'est tout.\n"
    assert text_of(answer) == answer


def test_the_reminder_survives_being_split_across_chunks():
    """Le flux coupe où il veut, y compris au milieu d'une ligne injectée."""
    middle = len(RECITED) // 2
    kept = text_of(RECITED[:middle], RECITED[middle:] + REAL_THINKING)
    assert "Structure de CHAQUE tour" not in kept
    assert "L'utilisateur veut corriger sa requête SQL." in kept


def test_a_held_fragment_is_flushed_before_a_tool_call():
    """Un fragment retenu ne doit jamais passer APRÈS l'évènement suivant."""
    events = [TextChunk("Structure de CHAQUE"), ToolCallParsed("Read", {}, "t1")]
    out = list(drop_prompt_echo(iter(events), (INJECTED_REMINDER,)))
    assert isinstance(out[0], TextChunk)
    assert out[0].text == "Structure de CHAQUE"
    assert out[-1] is events[1]


def test_an_unterminated_fragment_is_never_swallowed():
    kept = text_of("Structure de CHAQUE tour, dans l'ordre")
    assert kept == "Structure de CHAQUE tour, dans l'ordre"


def test_nothing_is_dropped_when_no_text_was_injected():
    assert text_of(RECITED, texts=()) == RECITED


def test_a_paraphrased_line_is_kept():
    """Le garde-fou est exact par choix : il n'invente pas de ressemblance.

    Le tour 17 de ba0d2431 a écrit « par FinalAnswer » au lieu de « via ». Cette
    ligne-là passe, et c'est le comportement voulu — supprimer du texte approchant
    reviendrait à effacer du contenu légitime.
    """
    assert "par FinalAnswer(...)." in text_of("Clôture uniquement par FinalAnswer(...).\n")
