# [desc] Une clôture acceptée et une clôture refusée s'affichent différemment dans la conversation. [/desc]
"""Affichage d'une réponse finale : acceptée, refusée, ou pas une clôture du tout.

Quand l'agent appelle FinalAnswer, le validateur accepte ou refuse la clôture. La
conversation doit montrer les deux cas différemment : un bloc « Réponse finale » d'un
côté, un bloc « Clôture refusée » de l'autre — et ne rien changer aux résultats
d'outils ordinaires.

Tout est observé par les surfaces publiques : le rendu d'un message et la route qui
sert les blocs d'une session.
"""
from __future__ import annotations

import json

import pytest

from bouzecode.web_v2.services import message_view
from bouzecode.web_v2.services.sessions import store

ACCEPTED = (
    "Session closing — final answer delivered:\n"
    "Tous les fichiers ont été modifiés et les tests passent."
)
REFUSED = (
    "CLÔTURE REFUSÉE par le validateur — il manque : tests non lancés\n"
    "Termine ce qui manque (coche ta todolist) puis rappelle FinalAnswer."
)
EMPTY_ANSWER = "Error: 'answer' is empty"
WRITE_RESULT = "File written successfully (42 bytes)."


def _tool_result(name: str, content: str) -> dict:
    return {"role": "tool", "name": name, "content": content}


# --- Rendu d'un message isolé -------------------------------------------------

def test_an_accepted_closure_is_shown_as_the_final_answer():
    """Une clôture acceptée s'affiche dans un bloc « Réponse finale » qui reprend le texte."""
    html = message_view.render_message(_tool_result("FinalAnswer", ACCEPTED))

    assert 'class="block final-answer"' in html
    assert "Réponse finale" in html
    assert "tests passent" in html


def test_a_refused_closure_is_shown_with_the_missing_work():
    """Une clôture refusée s'affiche dans un bloc distinct qui dit ce qui manque."""
    html = message_view.render_message(_tool_result("FinalAnswer", REFUSED))

    assert 'class="block final-answer-refused"' in html
    assert "Clôture refusée" in html
    assert "tests non lancés" in html


def test_an_ordinary_tool_result_keeps_its_usual_panel():
    """Le résultat d'un outil ordinaire garde son panneau habituel, pas un bloc de clôture."""
    html = message_view.render_message(_tool_result("Write", WRITE_RESULT))

    # le panneau porte la classe 'tr' (seule OU combinée, ex 'tr pui-tool-panel')
    assert 'class="tr"' in html or 'class="tr ' in html
    assert "résultat Write" in html
    assert "final-answer" not in html


# --- La session lue par l'interface -------------------------------------------

# Ordre des messages tel que servi par la route : les index sont utilisés tels quels
# dans les assertions pour que le test se lise comme la conversation elle-même.
USER = 0
ASSISTANT_FIRST_TRY = 1
CLOSURE_REFUSED = 2
ASSISTANT_SECOND_TRY = 3
CLOSURE_ACCEPTED = 4
ORDINARY_TOOL = 5
CLOSURE_WITHOUT_ANSWER = 6


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Client Flask servant une session : une clôture refusée, puis acceptée."""
    session = {
        "messages": [
            {"role": "user", "content": "Do something"},
            {"role": "assistant", "content": "Done.",
             "tool_calls": [{"name": "FinalAnswer", "input": {"answer": "All done"}}]},
            _tool_result("FinalAnswer", REFUSED),
            {"role": "assistant", "content": "Fixing...",
             "tool_calls": [{"name": "FinalAnswer", "input": {"answer": "Really done now"}}]},
            _tool_result("FinalAnswer", ACCEPTED),
            _tool_result("Write", WRITE_RESULT),
            _tool_result("FinalAnswer", EMPTY_ANSWER),
        ]
    }
    session_file = tmp_path / "session.json"
    session_file.write_text(json.dumps(session), encoding="utf-8")

    ref = store.SessionRef(key="test-session", kind="daily", path=session_file)
    monkeypatch.setattr(store, "resolve", lambda key: ref)
    monkeypatch.setattr(store, "load_session_json", lambda path: json.loads(path.read_text("utf-8")))
    monkeypatch.setattr(store, "session_meta_full", lambda data: {})

    from bouzecode.web_v2.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_the_session_marks_which_closure_was_accepted_and_which_was_refused(client):
    """Lire une session en texte brut indique, pour chaque clôture, si elle a été acceptée."""
    resp = client.get("/api/sessions/test-session/blocks?plain=1")
    assert resp.status_code == 200
    blocks = resp.get_json()["blocks"]

    assert blocks[CLOSURE_REFUSED]["kind"] == "final_answer_refused"
    assert blocks[CLOSURE_ACCEPTED]["kind"] == "final_answer"


def test_messages_that_are_not_closures_carry_no_verdict(client):
    """Un message ordinaire — et un FinalAnswer sans réponse — ne portent aucun verdict."""
    blocks = client.get("/api/sessions/test-session/blocks?plain=1").get_json()["blocks"]

    for index in (USER, ASSISTANT_FIRST_TRY, ORDINARY_TOOL, CLOSURE_WITHOUT_ANSWER):
        assert "kind" not in blocks[index], f"le message {index} ne devrait porter aucun verdict"


def test_the_rendered_session_shows_both_closure_blocks(client):
    """La session rendue en HTML montre le bloc refusé puis le bloc de réponse finale."""
    blocks = client.get("/api/sessions/test-session/blocks").get_json()["blocks"]

    assert "final-answer-refused" in blocks[CLOSURE_REFUSED]["html"]
    assert "final-answer" in blocks[CLOSURE_ACCEPTED]["html"]
    assert "Réponse finale" in blocks[CLOSURE_ACCEPTED]["html"]
