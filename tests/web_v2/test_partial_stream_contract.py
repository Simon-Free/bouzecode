"""P12 — « je veux suivre un agent token par token pendant qu'il répond ».

Contrat de bout en bout : le runner écrit ``<session>.partial.json``
(``backend.agent.partial_stream.write_partial``), la route
``GET /api/sessions/<key>/partial`` le relit et le front (session.js /
conversations.js) rend ``{phase, text, thinking}``.

Aucun JSON n'est inventé à la main : les partiels sont produits par le VRAI
producteur (write_partial, ou la boucle d'agent avec ``mock_llm``) puis relus
par la vraie route.
"""
import json

import pytest

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM
from bouzecode.backend.agent import partial_stream as ps

# Toute réponse mock inclut Methodology, sinon l'enforcement relance un tour.
METHODOLOGY_CALL = (
    '<tool_use name="Methodology" id="m1"><param name="content">test</param></tool_use>'
)


@pytest.fixture(autouse=True)
def _fresh_agent_process():
    """L'état d'écriture de partial_stream est global au processus : on repart à neuf."""
    _simulate_a_fresh_agent_process()
    yield
    _simulate_a_fresh_agent_process()


def _simulate_a_fresh_agent_process():
    """Un agent relancé, c'est un nouveau processus : compteurs d'écriture à zéro."""
    ps._last_write_at = 0.0
    ps._last_len = 0
    ps._seq = 0


class _SessionRef:
    """Ce que ``store.resolve`` rend à la route : un objet porteur du chemin session."""

    def __init__(self, path):
        self.path = path
        self.agent = None


@pytest.fixture()
def client():
    from bouzecode.web_v2.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


@pytest.fixture()
def watched_session(tmp_path, monkeypatch):
    """Une session d'agent web dont la route sert le partiel ; rend (chemin, GET)."""
    from bouzecode.web_v2.routes import sessions as sessions_routes

    session = tmp_path / "abcd1234.session.json"
    monkeypatch.setattr(
        sessions_routes, "_resolve_or_404", lambda key: (_SessionRef(session), None)
    )
    return session


def _read_partial(client):
    response = client.get("/api/sessions/agent%2Fabcd1234/partial")
    assert response.status_code == 200
    return response.get_json()


# ---------------------------------------------------------------------------
# Contrat producteur -> route : les champs récents `phase` et `thinking`
# ---------------------------------------------------------------------------

def test_partial_exposes_the_reasoning_while_the_model_thinks(client, watched_session):
    """Pendant que le modèle réfléchit, le suivi live sert la réflexion et pas encore de texte."""
    config = {"_session_file": str(watched_session)}

    ps.write_partial(config, turn=1, text="", thinking="Je pèse le pour et le contre", phase="thinking", force=True)

    body = _read_partial(client)
    assert body["phase"] == "thinking"
    assert body["thinking"] == "Je pèse le pour et le contre"
    assert body["text"] == ""
    assert body["turn"] == 1


def test_partial_switches_to_the_answer_and_keeps_the_reasoning(client, watched_session):
    """Quand la réponse commence à s'écrire, la phase bascule sur le texte sans perdre la réflexion."""
    config = {"_session_file": str(watched_session)}

    ps.write_partial(config, turn=1, text="", thinking="mon raisonnement", phase="thinking", force=True)
    ps.write_partial(config, turn=1, text="La réponse est 42", thinking="mon raisonnement", phase="text", force=True)

    body = _read_partial(client)
    assert body["phase"] == "text"
    assert body["text"] == "La réponse est 42"
    assert body["thinking"] == "mon raisonnement", "la réflexion reste consultable une fois repliée"


def test_partial_written_by_an_older_agent_is_still_readable(client, watched_session):
    """Un agent d'avant l'ajout de phase/thinking reste lisible : la route comble les champs manquants."""
    legacy = {"turn": 4, "seq": 12, "text": "texte d'un agent resté à l'ancien format"}
    watched_session.with_suffix(".partial.json").write_text(json.dumps(legacy), encoding="utf-8")

    body = _read_partial(client)
    assert body["text"] == "texte d'un agent resté à l'ancien format"
    assert body["phase"] == "text", "sans phase, le front doit afficher du texte, pas un bloc réflexion"
    assert body["thinking"] == ""


def test_an_unknown_session_has_no_live_view(client):
    """Suivre une session qui n'existe pas répond 404, pas un partiel vide."""
    response = client.get("/api/sessions/agent%2Fnobody/partial")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Cas limites : rien à suivre, tour terminé, agent mort, tour qui repart
# ---------------------------------------------------------------------------

def test_nothing_to_follow_when_the_agent_is_idle(client, watched_session):
    """Aucun partiel sur le disque : la route dit « rien en cours » et le front retire son bloc."""
    assert not watched_session.with_suffix(".partial.json").exists()

    assert _read_partial(client) == {"text": None}


def test_the_live_text_stops_being_served_once_the_turn_is_over(client, watched_session):
    """Le tour fini, le partiel s'efface : le message persisté est la seule source, donc pas de doublon."""
    config = {"_session_file": str(watched_session)}
    ps.write_partial(config, turn=1, text="réponse en cours d'écriture", force=True)
    assert _read_partial(client)["text"] == "réponse en cours d'écriture"

    ps.clear_partial(config)

    assert _read_partial(client) == {"text": None}


def test_an_agent_killed_mid_turn_leaves_its_last_partial_behind(client, watched_session):
    """Un agent tué en plein tour n'efface pas son partiel : la route sert encore le dernier texte connu."""
    config = {"_session_file": str(watched_session)}
    ps.write_partial(config, turn=2, text="je commençais à répondre quand", force=True)

    # Mort brutale : aucun clear_partial ne passe (le processus disparaît).
    body = _read_partial(client)
    assert body["text"] == "je commençais à répondre quand"
    # Le front ne l'affiche que tant que l'état est "running" (session.js:226,
    # conversations.js:1962) : c'est ce qui empêche ce reliquat de rester à l'écran.


def test_the_sequence_keeps_growing_from_one_turn_to_the_next(client, watched_session):
    """D'un tour à l'autre du même agent, le numéro de séquence avance : le front voit du neuf."""
    config = {"_session_file": str(watched_session)}
    ps.write_partial(config, turn=1, text="premier tour", force=True)
    seq_first_turn = _read_partial(client)["seq"]
    ps.clear_partial(config)

    ps.write_partial(config, turn=2, text="second tour", force=True)

    assert _read_partial(client)["seq"] > seq_first_turn


def test_the_sequence_restarts_when_the_agent_is_relaunched(client, watched_session):
    """Un agent relancé repart de seq=1 alors que le tour a avancé : seq recule, il ne date pas la session."""
    config = {"_session_file": str(watched_session)}
    ps.write_partial(config, turn=1, text="avant le crash", force=True)
    ps.write_partial(config, turn=1, text="avant le crash, un peu plus loin", force=True)
    seq_before_relaunch = _read_partial(client)["seq"]

    _simulate_a_fresh_agent_process()  # relance de l'agent sur le MÊME --session-file
    ps.write_partial(config, turn=5, text="après la reprise", force=True)

    body = _read_partial(client)
    assert body["seq"] < seq_before_relaunch, "seq est propre au processus, pas à la session"
    assert body["turn"] == 5
    # Sans conséquence visible aujourd'hui : ni session.js ni conversations.js ne lisent
    # `seq` — ils comparent directement le texte. Toute future optimisation « ne
    # re-rendre que si seq a changé » serait fausse ici.


# ---------------------------------------------------------------------------
# La vraie boucle d'agent produit-elle bien ces partiels ? (mock_llm)
# ---------------------------------------------------------------------------

def _spy_on_published_partials(monkeypatch):
    """Espionne la couture runner -> partial_stream : enregistre puis délègue au vrai writer."""
    import bouzecode.backend.agent.loop_turn as loop_turn

    published = []
    real_write_partial = loop_turn.write_partial

    def recording_write_partial(config, turn, text, *, thinking="", phase="text", force=False):
        published.append({"turn": turn, "phase": phase, "text": text, "thinking": thinking})
        real_write_partial(config, turn, text, thinking=thinking, phase=phase, force=force)

    monkeypatch.setattr(loop_turn, "write_partial", recording_write_partial)
    return published


def test_the_running_loop_publishes_the_reasoning_then_the_answer(tmp_path, monkeypatch):
    """Un agent qui réfléchit puis répond publie d'abord des partiels « thinking », ensuite « text »."""
    published = _spy_on_published_partials(monkeypatch)
    session = tmp_path / "abcd1234.session.json"
    mock = MockLLM([
        {"thinking": ["Je pèse le pour et le contre."], "text": f"La réponse est 42.\n{METHODOLOGY_CALL}"},
        "La réponse est 42.",  # tour de clôture, sans tool call
    ])

    bouzecode(
        ["Combien font six fois sept ?"],
        mock_llm=mock,
        config_overrides={"_session_file": str(session)},
    )

    assert any(
        p["phase"] == "thinking" and "Je pèse le pour et le contre." in p["thinking"]
        for p in published
    ), f"aucun partiel de réflexion publié : {published}"
    assert any(
        p["phase"] == "text" and "La réponse est 42." in p["text"] for p in published
    ), f"aucun partiel de texte publié : {published}"
    phases = [p["phase"] for p in published]
    assert phases.index("thinking") < phases.index("text"), "la réflexion doit précéder le texte"


def test_a_finished_agent_leaves_no_live_text_to_follow(client, tmp_path, monkeypatch):
    """Une fois l'agent terminé, plus rien à suivre : le partiel a été nettoyé par la boucle."""
    from bouzecode.web_v2.routes import sessions as sessions_routes

    published = _spy_on_published_partials(monkeypatch)
    session = tmp_path / "abcd1234.session.json"
    mock = MockLLM([f"Voici ma réponse.\n{METHODOLOGY_CALL}", "Voici ma réponse."])

    bouzecode(
        ["Dis quelque chose"],
        mock_llm=mock,
        config_overrides={"_session_file": str(session)},
    )

    assert published, "garde-fou : sans partiel publié, l'absence de fichier ne prouverait rien"
    assert not session.with_suffix(".partial.json").exists()
    monkeypatch.setattr(
        sessions_routes, "_resolve_or_404", lambda key: (_SessionRef(session), None)
    )
    assert _read_partial(client) == {"text": None}


# ---------------------------------------------------------------------------
# Bug documenté : le relais partiel -> message persisté laisse un trou
# ---------------------------------------------------------------------------

@pytest.mark.xfail(
    strict=True,
    reason=(
        "BUG (clignotement) : loop_turn.py:255 appelle clear_partial dès la fin du stream, "
        "alors que le message assistant n'est persisté qu'au TurnDone consommé plus tard "
        "(ui/repl.py:444). Le front interroge /partial toutes les 250 ms (session.js:228) mais "
        "/blocks seulement toutes les 1500 ms (session.js:129) : le texte final disparaît de "
        "l'écran pendant jusqu'à ~1,25 s avant que la vraie bulle n'arrive."
    ),
)
def test_the_final_text_stays_visible_until_the_persisted_message_arrives(client, watched_session):
    """Le texte final ne doit pas s'effacer entre la fin de la génération et l'arrivée de la bulle."""
    config = {"_session_file": str(watched_session)}
    ps.write_partial(config, turn=1, text="La réponse finale, complète.", force=True)

    ps.clear_partial(config)  # fin du stream, côté producteur
    assert not watched_session.exists(), "le message complet n'est pas encore sur le disque"

    assert _read_partial(client)["text"] == "La réponse finale, complète."
