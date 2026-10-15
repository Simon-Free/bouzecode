# [desc] La fermeture du lot citée en prose, dans un thinking, entre guillemets ou backticks, ou sans ouverture de lot, ne coupe plus la génération ; seule une vraie fermeture lève batch_closed. [/desc]
"""Session a3b38124 (21/09) : le modèle écrit dans son <thinking> « arrêt volontaire sur
</tool_calls> » ; le parser y voit une fermeture « top level » (il ne regardait que les
appels ouverts), le client raccroche au milieu de la réflexion, et le harness répond « NO
tool call from your previous turn was recorded ». Une vraie fermeture est HORS thinking,
HORS code (backticks, fence), HORS guillemets, et suit une ouverture de lot (ou au moins un
appel complet).

Comme dans test_batch_close_client_side, la balise n'est jamais tapée littéralement.
"""
import pytest

from bouzecode.backend.xml_tool_protocol import (
    TOOL_CALLS_CLOSE,
    TOOL_CALLS_OPEN,
    XmlToolStreamParser,
)
# Importé au chargement, avant que la garde anti-appel réel ne rebranche le streamer.
from tests.backend.providers.anthropic_sse_replay import (
    sse, opening, replay_stream, tool_calls_of, turn_of,
)

CALL = '<tool_use name="Read" id="r1"><param name="file_path">a.py</param></tool_use>'
BATCH = f"{TOOL_CALLS_OPEN}\n{CALL}\n{TOOL_CALLS_CLOSE}"


def _feed(parser, *chunks):
    items = []
    for c in chunks:
        items += parser.feed(c)
    return items


def _calls(items):
    return [it for it in items if isinstance(it, dict) and it.get("name") != "_XmlParseError"]


def test_session_a3b38124_citation_dans_le_thinking_ne_coupe_pas():
    thinking = ("<thinking>\n  Ce qui manque : savoir si l'usage est disponible quand loop_turn "
                f"force 0 (cas probable : arrêt volontaire sur {TOOL_CALLS_CLOSE}), puis vérifier.\n"
                "</thinking>\n\n")
    parser = XmlToolStreamParser()
    # Découpage réaliste : la balise arrive coupée en deux deltas.
    moitie = thinking.index(TOOL_CALLS_CLOSE) + 5
    _feed(parser, thinking[:moitie], thinking[moitie:])
    assert parser.batch_closed is False, "une citation dans le thinking n'est pas une fermeture"
    calls = _calls(_feed(parser, "Je lis le fichier.\n", BATCH))
    assert parser.batch_closed is True
    assert [c["name"] for c in calls] == ["Read"]


@pytest.mark.parametrize("prose", [
    f"Le client s'arrête sur `{TOOL_CALLS_CLOSE}` puis attend l'usage.\n",
    f"Le client s'arrête sur ``{TOOL_CALLS_CLOSE}`` puis attend l'usage.\n",
    f"Exemple :\n```xml\n{TOOL_CALLS_OPEN}\n{CALL}\n{TOOL_CALLS_CLOSE}\n```\nFin de l'exemple.\n",
    f'La balise "{TOOL_CALLS_CLOSE}" ferme le lot.\n',
    f"La balise « {TOOL_CALLS_CLOSE} » ferme le lot.\n",
    f"La balise “{TOOL_CALLS_CLOSE}” ferme le lot.\n",
    f"La balise '{TOOL_CALLS_CLOSE}' ferme le lot.\n",
], ids=["backticks", "double-backticks", "fence", "guillemets-droits", "chevrons",
        "guillemets-anglais", "apostrophes"])
def test_citation_en_prose_ne_coupe_pas_puis_vrai_lot_coupe(prose):
    parser = XmlToolStreamParser()
    _feed(parser, prose)
    assert parser.batch_closed is False
    calls = _calls(_feed(parser, BATCH))
    assert parser.batch_closed is True
    assert [c["name"] for c in calls] == ["Read"]


def test_fermeture_sans_ouverture_ni_appel_ne_coupe_pas():
    parser = XmlToolStreamParser()
    _feed(parser, f"Le lot se ferme par {TOOL_CALLS_CLOSE} tout simplement, je continue.\n")
    assert parser.batch_closed is False


def test_appels_sans_ouverture_puis_fermeture_coupe_encore():
    """Tolérance historique : un modèle qui oublie l'ouverture mais a émis un appel complet
    ferme bien son lot."""
    parser = XmlToolStreamParser()
    calls = _calls(_feed(parser, f"{CALL}\n", TOOL_CALLS_CLOSE))
    assert parser.batch_closed is True
    assert [c["name"] for c in calls] == ["Read"]


def test_vrai_lot_en_plusieurs_deltas():
    parser = XmlToolStreamParser()
    texte = f"Je lis.\n{BATCH}"
    for i in range(0, len(texte), 7):
        parser.feed(texte[i:i + 7])
    assert parser.batch_closed is True


def test_bout_en_bout_le_streamer_ne_raccroche_pas_sur_la_citation(monkeypatch):
    """Le vrai stream_anthropic, rejoué : la citation dans le thinking ne fait plus
    raccrocher, l'appel qui suit est reçu."""
    thinking = (f"<thinking>\narrêt volontaire sur {TOOL_CALLS_CLOSE} dans le client\n"
                "</thinking>\n")
    events = sse(*opening(),
                 {"type": "content_block_start", "index": 0,
                  "content_block": {"type": "text", "text": ""}},
                 *[{"type": "content_block_delta", "index": 0,
                    "delta": {"type": "text_delta", "text": t}}
                   for t in (thinking, "Je lis.\n", BATCH)],
                 {"type": "content_block_stop", "index": 0},
                 {"type": "message_delta", "delta": {"stop_reason": "end_turn",
                                                     "stop_sequence": None},
                  "usage": {"output_tokens": 42}})
    yielded = replay_stream(monkeypatch, events, native_tools=None)
    assert [c.name for c in tool_calls_of(yielded)] == ["Read"]
    assert turn_of(yielded).out_tokens == 42
