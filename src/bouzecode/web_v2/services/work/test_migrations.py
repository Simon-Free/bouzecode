"""Tests de la migration one-shot des sous-agents hérités orphelins (A1).

User-centric : on écrit de VRAIS fichiers agent JSON + un VRAI store de tickets sur
disque (dans des dossiers temporaires), on appelle migrate_orphan_validators() puis on
relit l'agent depuis le disque pour vérifier que son parent a été réécrit vers le codeur.
Aucun mock : on redirige les DIR de runner/tickets vers des tmp_path via monkeypatch."""

from __future__ import annotations

import json
from pathlib import Path

from ...runtime import runner
from . import _persistence, migrations, tickets


def _write_agent(agents_dir: Path, agent_id: str, parent: str, cwd: str = "") -> None:
    agents_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "agent_id": agent_id,
        "parent": parent,
        "cwd": cwd,
        "pid": 0,
        "model": "test-model",
        "prompt": f"prompt {agent_id}",
        "session_path": "",
        "started_at": "2026-07-06T00:00:00",
        "returncode": 0,
        "run_kind": "validate_tests" if parent.startswith("dispatcher:") else "work",
    }
    (agents_dir / f"{agent_id}.json").write_text(json.dumps(data), encoding="utf-8")


def _write_ticket(tickets_dir: Path, slug: str, ticket: dict, archived: bool = False) -> None:
    """Sème UN ticket dans le VRAI store (SQLite). Semait avant un fichier
    `<slug>.json` : ce format legacy n'existe plus, et la migration qui le lisait
    ne voyait donc jamais rien — le test restait vert sur du code MORT."""
    _persistence._save(slug, [{**ticket, "archived": archived}])


def _redirect_dirs(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    agents_dir = tmp_path / "agents"
    tickets_dir = tmp_path / "tickets"
    monkeypatch.setattr(runner, "AGENTS_DIR", agents_dir)
    # `_persistence.TICKETS_DIR` est la SOURCE (la base est ouverte par `_db_path()`) ;
    # `tickets.TICKETS_DIR` n'en est qu'un ré-export. Sans le patch de la source, ce test
    # lirait/écrirait le store de PRODUCTION.
    monkeypatch.setattr(_persistence, "TICKETS_DIR", tickets_dir)
    monkeypatch.setattr(tickets, "TICKETS_DIR", tickets_dir)
    # Vide le cache disque de list_agents (état partagé entre tests).
    runner._list_agents_cache.clear()
    runner._agent_file_cache.clear()
    return agents_dir, tickets_dir


def test_migrate_reparents_legacy_validator_to_its_coder(monkeypatch, tmp_path):
    agents_dir, tickets_dir = _redirect_dirs(monkeypatch, tmp_path)
    # Codeur (run work) + validateur hérité du MÊME ticket, parent littéral.
    _write_agent(agents_dir, "coder-1", parent="dispatcher:manual", cwd=str(tmp_path / "wt"))
    _write_agent(agents_dir, "validator-1", parent="dispatcher:validate", cwd=str(tmp_path / "wt"))
    _write_ticket(tickets_dir, "proj", {
        "id": "t1", "title": "T", "runs": [
            {"agent_id": "validator-1", "kind": "validate_tests"},
            {"agent_id": "coder-1", "kind": "work"},
        ],
    })

    migrated = migrations.migrate_orphan_validators()

    assert migrated == 1
    reloaded = runner.load_agent("validator-1")
    assert reloaded is not None
    # Acceptance : plus aucun node à parent "dispatcher:validate" — il pointe le codeur.
    assert reloaded.parent == "coder-1"


def test_migrate_handles_archived_ticket(monkeypatch, tmp_path):
    agents_dir, tickets_dir = _redirect_dirs(monkeypatch, tmp_path)
    _write_agent(agents_dir, "coder-2", parent="dispatcher:manual")
    _write_agent(agents_dir, "merger-2", parent="dispatcher:auto-merge")
    _write_ticket(tickets_dir, "proj", {
        "id": "t2", "title": "T", "runs": [
            {"agent_id": "merger-2", "kind": "validate_refacto"},
            {"agent_id": "coder-2", "kind": "work"},
        ],
    }, archived=True)

    migrations.migrate_orphan_validators()

    assert runner.load_agent("merger-2").parent == "coder-2"


def test_migrate_is_idempotent(monkeypatch, tmp_path):
    agents_dir, tickets_dir = _redirect_dirs(monkeypatch, tmp_path)
    _write_agent(agents_dir, "coder-3", parent="dispatcher:manual")
    _write_agent(agents_dir, "validator-3", parent="dispatcher:validate")
    _write_ticket(tickets_dir, "proj", {
        "id": "t3", "title": "T", "runs": [
            {"agent_id": "validator-3", "kind": "validate_tests"},
            {"agent_id": "coder-3", "kind": "work"},
        ],
    })

    first = migrations.migrate_orphan_validators()
    runner._list_agents_cache.clear()
    runner._agent_file_cache.clear()
    second = migrations.migrate_orphan_validators()

    assert first == 1
    assert second == 0  # rien à migrer au 2e passage
    assert runner.load_agent("validator-3").parent == "coder-3"


def test_migrate_leaves_orphan_without_coder_for_front_fallback(monkeypatch, tmp_path):
    agents_dir, tickets_dir = _redirect_dirs(monkeypatch, tmp_path)
    # Validateur hérité SANS ticket correspondant (ticket disparu) : la migration ne
    # touche pas → le fallback front (branche/worktree) prendra le relais.
    _write_agent(agents_dir, "orphan-4", parent="dispatcher:validate")

    migrated = migrations.migrate_orphan_validators()

    assert migrated == 0
    assert runner.load_agent("orphan-4").parent == "dispatcher:validate"
