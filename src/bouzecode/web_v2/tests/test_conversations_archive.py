"""Archivage des conversations USER + purge automatique des conversations de test.

ARCHIVER = RANGER, PAS DÉPLACER. Ces tests exigeaient auparavant que l'archivage sorte les
artefacts de l'agent vers `_trash/` ; ce déplacement a été retiré du produit parce qu'il rendait
un manager VIVANT injoignable (`load_agent` → None → 404 sur /continue, ~4 h le 2026-07-28).
Le contrat vérifié ici est donc le contrat actuel : l'agent est INSCRIT au registre des archivés,
ses artefacts restent en place (il reste joignable), et il disparaît des listes seulement s'il
est fini. La PURGE des tests, elle, déplace toujours vraiment — et reste inerte sous pytest sauf
levée explicite du garde-fou (`autoriser_la_destruction`).
"""
import json
import os

import pytest

from bouzecode.web_v2.tests.production_isolation import autoriser_la_destruction


def _write_agent(agents_dir, agent_id, prompt, *, running=False):
    pid = os.getpid() if running else 999_999_999
    data = {
        "agent_id": agent_id,
        "prompt": prompt,
        "model": "claude-sonnet",
        "cwd": "/tmp",
        "pid": pid,
        "started_at": f"2026-06-01T10:00:0{len(agent_id) % 10}Z",
        "returncode": None if running else 0,
        "session_path": str(agents_dir / f"{agent_id}.session.json"),
        "stdout_path": str(agents_dir / f"{agent_id}.out.log"),
    }
    (agents_dir / f"{agent_id}.json").write_text(json.dumps(data), encoding="utf-8")
    (agents_dir / f"{agent_id}.session.json").write_text(
        json.dumps({"messages": []}), encoding="utf-8"
    )
    (agents_dir / f"{agent_id}.out.log").write_text("log", encoding="utf-8")


@pytest.fixture()
def agents_dir(tmp_path, monkeypatch):
    from bouzecode.web_v2.runtime.runner import agent_fiche

    d = tmp_path / "web_agents"
    d.mkdir()
    monkeypatch.setattr(agent_fiche, "AGENTS_DIR", d)
    agent_fiche._list_agents_cache.clear()
    from bouzecode.web_v2.services.sessions import purge
    monkeypatch.setattr(purge, "TRASH_DIR", d / "_trash")

    # test conversations (non-running) → auto-purgeables
    _write_agent(d, "aaaaaa", "test typology sur projet foo")
    _write_agent(d, "bbbbbb", "Test ping rapide")
    # vraie conversation USER (archivable manuellement, jamais auto-purgée)
    _write_agent(d, "cccccc", "Corriger le bug de parsing dans parser.py")
    # test conversation MAIS en cours d'exécution (jamais touchée)
    _write_agent(d, "dddddd", "test running keep", running=True)
    agent_fiche._list_agents_cache.clear()
    return d


@pytest.fixture()
def client(agents_dir):
    from bouzecode.web_v2.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# --- Archivage d'une conversation USER ------------------------------------

def _visible_keys(agents_dir) -> set[str]:
    """Les conversations que la sidebar affiche encore (mêmes filtres que /api/sessions)."""
    from bouzecode.web_v2.runtime.runner import agent_fiche
    from bouzecode.web_v2.services.sessions import store

    agent_fiche._list_agents_cache.clear()
    return {row["key"] for row in store.list_agent_sessions(include_tests=True)}


def test_archive_user_conversation(client, agents_dir):
    """Une conversation user finie qu'on archive quitte la liste — sans quitter le disque."""
    from bouzecode.web_v2.services.sessions import purge

    resp = client.post("/api/conversations/cccccc/archive")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["archived"] == ["cccccc"]
    # Le rangement vit dans le REGISTRE, pas dans une corbeille.
    assert purge.load_deleted()["agent/cccccc"]["reason"] == "archived"
    # Les artefacts restent EN PLACE : c'est ce qui garde l'agent joignable.
    assert (agents_dir / "cccccc.json").exists()
    assert (agents_dir / "cccccc.session.json").exists()
    assert not (agents_dir / "_trash").exists()
    # ... et l'agent, fini, disparaît bien de la liste des conversations.
    assert "agent/cccccc" not in _visible_keys(agents_dir)


@pytest.mark.parametrize(
    "state, hidden",
    [
        ("running", False),                  # travaille → protégé de l'archivage
        ("awaiting_input", False),           # attend l'humain → protégé
        ("awaiting_plan_validation", False), # attend l'humain → protégé
        ("idle", True),                      # warm oisif → archivable (demande user)
        ("starting", True),                  # démarrage → archivable
        ("finished", True),                  # terminé → archivable
    ],
)
def test_hidden_by_archive_only_protects_working_or_awaiting_states(
    monkeypatch, state, hidden
):
    """L'archivage MANUEL ne doit épargner QUE les agents qui travaillent ou attendent
    l'humain. Un warm oisif (`idle`) ou un `starting` doit pouvoir être masqué — l'user
    veut ranger ces conversations (bug 9d0789f2fdca/63343a4b4a4a). Régression : ne pas
    ré-inclure `idle` dans les états protégés."""
    from bouzecode.web_v2.runtime.runner import agent_fiche
    from bouzecode.web_v2.services.sessions import store, visibility

    agent = agent_fiche.Agent("zzzzzz", "p", "claude-sonnet", "/tmp", 999999999, "2026-06-01T10:00:00Z")
    monkeypatch.setattr(store, "agent_status", lambda _a: {"state": state})
    deleted = {"agent/zzzzzz": {"reason": "archived"}}
    assert visibility.hidden_by_archive(agent, deleted) is hidden
    # Non inscrit au registre = jamais caché, quel que soit l'état.
    assert visibility.hidden_by_archive(agent, {}) is False


@pytest.mark.parametrize(
    "state, returncode, hidden",
    [
        # Agent ORPHELIN (process mort, returncode posé) qui affiche encore une
        # question pendante : l'archivage MANUEL doit pouvoir le ranger. Bug vécu :
        # après restart serveur, 9d0789f2fdca / 63343a4b4a4a / "Suite du ticket 3..."
        # étaient "Nécessitant une action" (awaiting_*) mais leur process était mort,
        # donc l'utilisateur ne pouvait pas les archiver.
        ("awaiting_input", 0, True),
        ("awaiting_plan_validation", 0, True),
        ("awaiting_input", 137, True),
        # Agent VIVANT (returncode None) qui attend l'humain : reste protégé pour ne
        # pas reproduire l'incident 2026-07-28 (agent en cours rendu injoignable).
        ("awaiting_input", None, False),
        ("awaiting_plan_validation", None, False),
        # Un agent qui TOURNE est forcément vivant : toujours protégé.
        ("running", None, False),
    ],
)
def test_hidden_by_archive_orphan_awaiting_is_archivable(
    monkeypatch, state, returncode, hidden
):
    """Un agent en attente d'action dont le PROCESS EST MORT (returncode posé) doit
    pouvoir être archivé manuellement. La protection `ARCHIVE_PROTECTED_STATES` ne vaut
    QUE pour un agent VIVANT (returncode None) : sinon un awaiting orphelin reste
    éternellement non-archivable après un restart serveur."""
    from bouzecode.web_v2.runtime.runner import agent_fiche
    from bouzecode.web_v2.services.sessions import store, visibility

    agent = agent_fiche.Agent("orphan", "p", "claude-sonnet", "/tmp", 999999999, "2026-06-01T10:00:00Z")
    monkeypatch.setattr(
        store, "agent_status", lambda _a: {"state": state, "returncode": returncode}
    )
    deleted = {"agent/orphan": {"reason": "archived"}}
    assert visibility.hidden_by_archive(agent, deleted) is hidden


def test_archive_keeps_a_running_agent_visible(client, agents_dir):
    """Ranger une conversation qui tourne encore ne la fait pas disparaître de la liste."""
    resp = client.post("/api/conversations/dddddd/archive")
    assert resp.status_code == 200
    assert resp.get_json()["archived"] == ["dddddd"]
    # La vivacité PRIME sur le drapeau : l'agent reste listé, donc on peut lui répondre.
    assert "agent/dddddd" in _visible_keys(agents_dir)
    assert (agents_dir / "dddddd.json").exists()


def test_archive_unknown(client):
    resp = client.post("/api/conversations/zzzzzz/archive")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["archived"] == []
    assert body["skipped"][0]["agent_id"] == "zzzzzz"
    assert "inconnu" in body["skipped"][0]["reason"].lower()


# --- Archive-tree : agent + descendants en UN SEUL appel batch -------------

def test_archive_tree_batch(client, agents_dir):
    """Archiver un agent = archiver TOUT son arbre. Le frontend résout les
    descendants (via /api/agents/tree) puis envoie agent + descendants en UN
    SEUL appel batch POST /api/conversations/archive body {keys:[...]}. On
    prouve ici que la route batch archive bien les 3 (parent + 2 enfants) en un
    appel, en réutilisant les préfixes "agent/<id>" tels que le front les émet."""
    from bouzecode.web_v2.runtime.runner import agent_fiche

    # parent + 2 enfants (non-running → archivables). Le lien parent/enfant vit
    # côté agents (tree) ; ici on simule ce que le front a déjà résolu : la liste
    # complète des keys de l'arbre.
    _write_agent(agents_dir, "parent", "Corriger le bug de parsing dans parser.py")
    _write_agent(agents_dir, "child1", "sous-tâche 1 de parent")
    _write_agent(agents_dir, "child2", "sous-tâche 2 de parent")
    agent_fiche._list_agents_cache.clear()

    resp = client.post(
        "/api/conversations/archive",
        json={"keys": ["agent/parent", "agent/child1", "agent/child2"]},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    # Les 3 ids de l'arbre archivés en un seul appel.
    assert set(body["archived"]) == {"parent", "child1", "child2"}
    # Tout l'arbre quitte la liste ; aucun artefact ne quitte le disque.
    visible = _visible_keys(agents_dir)
    for aid in ("parent", "child1", "child2"):
        assert f"agent/{aid}" not in visible
        assert (agents_dir / f"{aid}.json").exists()
    assert not (agents_dir / "_trash").exists()


def test_archive_batch_single_key_still_works(client, agents_dir):
    """Le comportement single (1 key dans le batch) n'est pas cassé."""
    resp = client.post(
        "/api/conversations/archive", json={"keys": ["agent/cccccc"]}
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["archived"] == ["cccccc"]
    assert "agent/cccccc" not in _visible_keys(agents_dir)
    assert (agents_dir / "cccccc.json").exists()


# --- Auto-purge des conversations de test ---------------------------------

def test_auto_purge_tests(client, agents_dir, monkeypatch):
    """Purge automatiquement aaaaaa+bbbbbb (test, non-running), conserve
    cccccc (user) et dddddd (test mais running).

    La purge est le seul geste qui déplace VRAIMENT des artefacts : `destruction_permitted`
    la rend inerte sous pytest depuis les dégâts du 2026-07-28, d'où la levée explicite du
    garde-fou. Le parc visé est celui, jetable, de la fixture."""
    autoriser_la_destruction(monkeypatch)

    # La route `POST /api/conversations/auto-purge-tests` est retirée (R11 : plus aucune page ne
    # la déclenche) ; le service reste, appelé directement.
    from bouzecode.web_v2.services.sessions import purge
    body = purge.auto_purge_test_agents()
    assert set(body["purged"]) == {"aaaaaa", "bbbbbb"}
    for aid in ("aaaaaa", "bbbbbb"):
        assert not (agents_dir / f"{aid}.json").exists()
        assert (agents_dir / "_trash" / aid / f"{aid}.json").exists()
    # user + running conservés
    assert (agents_dir / "cccccc.json").exists()
    assert (agents_dir / "dddddd.json").exists()
