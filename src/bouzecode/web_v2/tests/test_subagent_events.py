"""T4 — Marqueur inline « N agent(s) lancé(s) ».

Test user-centric au point d'entrée le plus proche de l'utilisateur : l'endpoint HTTP
réel GET /api/sessions/agent/<coder_id>/blocks. On écrit sur disque un vrai agent codeur
(avec ticket_slug/ticket_id), sa session (une livraison FinalAnswer « Session closing »),
et un vrai ticket avec runs work + validate. Aucun mock : AGENTS_DIR est monkeypatché vers
du tmp, le store de tickets est isolé par la fixture autouse, la résolution passe par le
vrai runner.

Le ticket est semé par `tickets._save` (UPSERT SQLite). Il l'était avant par un fichier
legacy `{slug}.json` : depuis la migration SQLite ce fichier n'est plus qu'une source
d'import LAZY, et `_persistence._migrated` — un `set` de PROCESS, jamais réinitialisé entre
tests — mémorise le slug dès le premier accès. Le 1er test du module migrait donc la graine,
et les DEUX suivants voyaient un store VIDE : leurs assertions (« aucun marqueur ») étaient
vraies sans rien observer. Prouvé par mutation : réintroduire le run validate dans
`test_no_markers_without_child_runs` laissait le module VERT.

Fixtures DÉRIVÉES du ticket réel 05794a28 ([A2] Traçabilité sous-agents) :
run work=b0236d1106e6, sous-agent validate=4bef5710e376, verdict KO, completed.
"""
import json
import os

import pytest

CODER_ID = "b0236d1106e6"
VALIDATOR_ID = "4bef5710e376"
TICKET_SLUG = "bouzecode"
TICKET_ID = "05794a28-t4-fixture"


def _write_coder_agent(agents_dir):
    """Vrai {id}.json codeur + session avec UNE livraison FinalAnswer « Session closing »."""
    data = {
        "agent_id": CODER_ID,
        "prompt": "Implémente la traçabilité inline des sous-agents.",
        "model": "claude-sonnet",
        "cwd": "/tmp",
        "pid": 999_999_999,
        "started_at": "2026-07-06T10:30:00Z",
        "returncode": 0,
        "session_path": str(agents_dir / f"{CODER_ID}.session.json"),
        "stdout_path": str(agents_dir / f"{CODER_ID}.out.log"),
        "ticket_slug": TICKET_SLUG,
        "ticket_id": TICKET_ID,
        "run_kind": "work",
    }
    (agents_dir / f"{CODER_ID}.json").write_text(json.dumps(data), encoding="utf-8")
    session = {
        "messages": [
            {"role": "user", "content": "Fais le boulot."},
            {"role": "assistant", "content": "Je livre.", "tool_calls": [
                {"id": "call_fa", "name": "FinalAnswer", "input": {"answer": "voilà"}},
            ]},
            {"role": "tool", "tool_call_id": "call_fa", "name": "FinalAnswer",
             "content": "Session closing\n\nRapport de livraison du codeur."},
        ]
    }
    (agents_dir / f"{CODER_ID}.session.json").write_text(
        json.dumps(session), encoding="utf-8")
    (agents_dir / f"{CODER_ID}.out.log").write_text("log", encoding="utf-8")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from bouzecode.web_v2.runtime import runner
    from bouzecode.web_v2.services.work import tickets

    agents_dir = tmp_path / "web_agents"
    agents_dir.mkdir()
    monkeypatch.setattr(runner, "AGENTS_DIR", agents_dir)
    runner._list_agents_cache.clear()

    _write_coder_agent(agents_dir)

    # Vrai ticket dans le VRAI store : runs work (codeur) + validate (sous-agent KO, terminé).
    ticket = {
        "id": TICKET_ID,
        "title": "[A2] Traçabilité sous-agents inline",
        "created_at": "2026-07-06T10:29:00Z",
        "runs": [
            {"agent_id": VALIDATOR_ID, "kind": "validate", "model": "",
             "started_at": "2026-07-06T10:39:00", "verdict": "KO", "completed": True},
            {"agent_id": CODER_ID, "kind": "work", "model": "",
             "started_at": "2026-07-06T10:30:00", "verdict": None},
        ],
    }
    tickets._save(TICKET_SLUG, [ticket])
    # Les deux tests suivants n'assertent que des ABSENCES de marqueur : sans ce garde-fou, un
    # store vide les rendrait verts sans rien prouver (c'est exactement ce qui arrivait quand la
    # graine était un `{slug}.json` legacy — cf. le docstring du module).
    assert tickets.get_ticket(TICKET_SLUG, TICKET_ID) is not None, "graine non semée dans le store"
    runner._list_agents_cache.clear()
    return agents_dir


@pytest.fixture()
def client(env):
    from bouzecode.web_v2.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_launch_and_completion_markers_in_coder_feed(client):
    """La conv du codeur expose un marqueur de lancement + un de complétion, cliquables."""
    resp = client.get(f"/api/sessions/agent/{CODER_ID}/blocks")
    assert resp.status_code == 200
    html = "".join(b.get("html", "") for b in resp.get_json()["blocks"])

    # Marqueur de lancement : un seul sous-agent → « 1 agent lancé — Validateur ».
    assert "1 agent lancé" in html
    assert "Validateur" in html
    # Cliquable → ouvre l'onglet du sous-agent validateur.
    assert f'data-open-key="agent/{VALIDATOR_ID}"' in html
    # Marqueur de complétion avec le verdict.
    assert "verdict KO" in html
    assert "terminé" in html


def _write_validator_agent(agents_dir):
    """Vrai {id}.json du VALIDATEUR (run_kind=validate, MÊME ticket que le codeur)."""
    data = {
        "agent_id": VALIDATOR_ID,
        "prompt": "Valide le travail du codeur.",
        "model": "claude-sonnet",
        "cwd": "/tmp",
        "pid": 999_999_998,
        "started_at": "2026-07-06T10:39:00Z",
        "returncode": 0,
        "session_path": str(agents_dir / f"{VALIDATOR_ID}.session.json"),
        "stdout_path": str(agents_dir / f"{VALIDATOR_ID}.out.log"),
        "ticket_slug": TICKET_SLUG,
        "ticket_id": TICKET_ID,
        "run_kind": "validate",
    }
    (agents_dir / f"{VALIDATOR_ID}.json").write_text(json.dumps(data), encoding="utf-8")
    session = {
        "messages": [
            {"role": "user", "content": "Valide."},
            {"role": "assistant", "content": "Verdict KO.", "tool_calls": [
                {"id": "call_v", "name": "FinalAnswer", "input": {"answer": "KO"}},
            ]},
            {"role": "tool", "tool_call_id": "call_v", "name": "FinalAnswer",
             "content": "Session closing\n\nVerdict KO."},
        ]
    }
    (agents_dir / f"{VALIDATOR_ID}.session.json").write_text(
        json.dumps(session), encoding="utf-8")
    (agents_dir / f"{VALIDATOR_ID}.out.log").write_text("log", encoding="utf-8")


def test_validator_feed_has_no_subagent_markers(client, env):
    """RÉGRESSION « le validateur lance un validateur » : ouvrir la conversation du
    VALIDATEUR (qui partage le ticket du codeur) ne doit produire AUCUN marqueur
    subagent — sinon le run validate se retrouverait affiché comme son propre enfant."""
    _write_validator_agent(env)
    from bouzecode.web_v2.runtime import runner
    runner._list_agents_cache.clear()

    resp = client.get(f"/api/sessions/agent/{VALIDATOR_ID}/blocks")
    assert resp.status_code == 200
    html = "".join(b.get("html", "") for b in resp.get_json()["blocks"])
    assert "agent lancé" not in html
    assert "subagent-event" not in html


def test_no_markers_without_child_runs(client, env):
    """Un codeur dont le ticket n'a AUCUN sous-agent distinct ne produit aucun marqueur."""
    from bouzecode.web_v2.services.work import tickets

    # Réécrit le ticket sans run validate (uniquement le run work du codeur).
    ticket = {
        "id": TICKET_ID, "title": "x", "created_at": "2026-07-06T10:29:00Z",
        "runs": [{"agent_id": CODER_ID, "kind": "work", "model": "",
                  "started_at": "2026-07-06T10:30:00", "verdict": None}],
    }
    tickets._save(TICKET_SLUG, [ticket])

    resp = client.get(f"/api/sessions/agent/{CODER_ID}/blocks")
    html = "".join(b.get("html", "") for b in resp.get_json()["blocks"])
    assert "agent lancé" not in html
    assert "subagent-event" not in html
