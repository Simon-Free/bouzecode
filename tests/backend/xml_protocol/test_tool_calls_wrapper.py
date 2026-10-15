# [desc] Tests TDD du wrapper `<tool_calls>` : constantes publiques, doc enseignée, parsing du batch et garde-fou anti-faux-appels [/desc]
"""Le wrapper de batch `<tool_calls>` et le garde-fou contre les faux appels.

Session 178666a6 : le modele a ecrit ses appels en markdown (```json {"name": ...}```)
puis a fabrique ses propres "Tool result". Le parser n'a rien vu (aucun `<tool_use`),
tout est ressorti en texte visible, aucune erreur n'est remontee, et rien n'a coupe le
stream. Deux verrous ici : un wrapper explicite qui sert de stop sequence, et une erreur
explicite quand un tour ne produit aucun appel mais ressemble a un faux appel.
"""
from __future__ import annotations

import pytest


READ_SCHEMA = {
    "name": "Read",
    "description": "Read a file from disk.",
    "input_schema": {
        "type": "object",
        "properties": {"file_path": {"type": "string", "description": "Absolute file path"}},
        "required": ["file_path"],
    },
}


def _parser():
    from bouzecode.backend.xml_tool_protocol import XmlToolStreamParser
    return XmlToolStreamParser()


def _feed(parser, *chunks):
    """Renvoie (appels, textes_visibles) pour une suite de chunks + finalize()."""
    items = []
    for chunk in chunks:
        items.extend(parser.feed(chunk))
    items.extend(parser.finalize())
    calls = [i for i in items if isinstance(i, dict)]
    texts = [i for i in items if isinstance(i, str)]
    return calls, texts


# --- Volet 1 : ce que la doc enseigne ---------------------------------------

def test_the_constants_are_part_of_the_public_protocol():
    """Les backends doivent pouvoir importer la stop sequence depuis le protocole."""
    from bouzecode.backend.xml_tool_protocol import (
        TOOL_CALLS_CLOSE, TOOL_CALLS_OPEN, TOOL_CALLS_STOP,
    )
    assert TOOL_CALLS_OPEN == "<tool_calls>"
    assert TOOL_CALLS_CLOSE == "</tool_calls>"
    assert TOOL_CALLS_STOP == TOOL_CALLS_CLOSE


def test_docs_teach_the_batch_wrapper():
    from bouzecode.backend.xml_tool_protocol import build_tool_docs
    docs = build_tool_docs([READ_SCHEMA])
    assert "<tool_calls>" in docs
    assert "</tool_calls>" in docs


def test_docs_warn_that_the_stream_is_cut_at_the_closing_tag():
    """Le modele doit savoir qu'il ne PEUT pas ecrire apres `</tool_calls>` :
    c'est ce qui rend impossible d'inventer un "Tool result"."""
    from bouzecode.backend.xml_tool_protocol import build_tool_docs
    docs = build_tool_docs([READ_SCHEMA]).lower()
    assert "</tool_calls>" in docs
    assert "stop" in docs or "coup" in docs, "la doc doit annoncer la coupure du stream"


def test_docs_stay_parsable_and_teach_no_error():
    """La doc est relue par ce parser : si elle parse en erreur, elle enseigne l'erreur."""
    from bouzecode.backend.xml_tool_protocol import build_tool_docs
    calls, texts = _feed(_parser(), build_tool_docs([READ_SCHEMA]))
    assert [c for c in calls if c["name"] == "_XmlParseError"] == []
    assert [c for c in calls if c["name"] == "Read"], "l'exemple Read doit rester parsable"
    # Une balise CITÉE en code (`<tool_calls>`) reste du texte : l'effacer laissait une
    # paire de backticks vide, lue comme un code inline ouvert qui avalait les appels suivants.
    visible = "".join(texts).replace("`<tool_calls>`", "").replace("`</tool_calls>`", "")
    assert "<tool_calls>" not in visible, "les tags du wrapper ne sont jamais du texte visible"


# --- Volet 2 : le parser avale le wrapper ----------------------------------

BATCH = (
    "<tool_calls>"
    '<tool_use name="Read" id="r1"><param name="file_path">a.py</param></tool_use>'
    '<tool_use name="Bash" id="b1"><param name="command">ls</param></tool_use>'
    "</tool_calls>"
)


def test_a_wrapped_batch_yields_every_call_and_no_wrapper_text():
    calls, texts = _feed(_parser(), BATCH)
    assert [c["name"] for c in calls] == ["Read", "Bash"]
    joined = "".join(texts)
    assert "tool_calls" not in joined
    assert joined.strip() == ""


def test_the_wrapper_survives_being_split_across_chunks():
    """Le tag peut arriver coupe en deux par le SSE : rien ne doit fuir en texte."""
    calls, texts = _feed(
        _parser(),
        "<tool_ca", "lls>",
        '<tool_use name="Read" id="r1"><param name="file_path">a.py</param>',
        "</tool_use>",
        "</tool_ca", "lls>",
    )
    assert [c["name"] for c in calls] == ["Read"]
    assert "tool_calls" not in "".join(texts)
    assert "lls>" not in "".join(texts)


def test_an_unclosed_wrapper_still_delivers_its_calls():
    """Anthropic n'inclut PAS la stop sequence dans la sortie : le texte recu se
    termine sur `</tool_use>`. Le parser ne doit jamais exiger la fermeture."""
    calls, _ = _feed(
        _parser(),
        "<tool_calls>",
        '<tool_use name="Read" id="r1"><param name="file_path">a.py</param></tool_use>',
    )
    assert [c["name"] for c in calls] == ["Read"]


def test_prose_before_the_wrapper_is_kept_as_visible_text():
    calls, texts = _feed(_parser(), "Je lis le fichier.\n" + BATCH)
    assert [c["name"] for c in calls] == ["Read", "Bash"]
    assert "Je lis le fichier." in "".join(texts)


# --- Volet 3 : un faux appel n'est plus accepte en silence ------------------

FAKE_MARKDOWN_TURN = """\
I'll start by loading the project configuration.

**Tool call:**
```json
{"name": "LoadProjectConfig", "args": {"path": "C:/proj"}, "id": "toolu_01ABC"}
```

**Tool result:**
```json
{"available_skills": [{"name": "demoapp-business-rules"}], "registered": true}
```

Great, the skill says `$MaxLeg` was removed in 2025.1.
"""


def test_a_markdown_tool_call_is_reported_as_an_error_not_swallowed_as_prose():
    """Le mode d'echec exact de la session 178666a6."""
    calls, _ = _feed(_parser(), FAKE_MARKDOWN_TURN)
    errors = [c for c in calls if c["name"] == "_XmlParseError"]
    assert errors, "un faux appel markdown doit remonter une erreur au modele"
    msg = errors[0]["input"]["_error"]
    assert "tool_calls" in msg or "tool_use" in msg, "l'erreur doit enseigner le bon format"


def test_the_error_is_raised_even_when_only_a_fake_result_is_present():
    calls, _ = _feed(_parser(), "**Tool result:**\n```json\n{\"ok\": true}\n```\n")
    assert [c for c in calls if c["name"] == "_XmlParseError"]


def test_a_real_call_never_triggers_the_fake_format_error():
    """Pas de faux positif : des qu'un vrai appel sort, le tour est valide meme si
    la prose parle de "Tool call" (une session de diagnostic le fait)."""
    turn = "Voici ce que j'ai vu : **Tool call:** en markdown dans la session.\n" + BATCH
    calls, _ = _feed(_parser(), turn)
    assert [c for c in calls if c["name"] == "_XmlParseError"] == []
    assert [c["name"] for c in calls] == ["Read", "Bash"]


def test_ordinary_prose_stays_error_free():
    calls, texts = _feed(_parser(), "Je n'ai pas d'outil a appeler ici, je reponds simplement.")
    assert calls == []
    assert "simplement" in "".join(texts)


def test_a_json_block_without_call_keys_is_not_a_fake_call():
    """Un vrai bloc json documentaire ne doit pas etre pris pour un faux appel."""
    calls, _ = _feed(_parser(), "Config:\n```json\n{\"max_tokens\": 8192}\n```\n")
    assert calls == []
