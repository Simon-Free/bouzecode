# [desc] Une reprise (`resume_agent`, nouvel identifiant) garde le ticket, le type de run et l'env de hook de l'agent repris, et devient le run le plus récent du ticket. [/desc]
"""Constat du 2026-09-29 : `3eb942805a2c`, reprise automatique de `d44a8566ec89` (ticket
525cb57c), est née avec `ticket_slug`/`ticket_id` vides et `run_kind` par défaut, lancée sans
l'env du hook : sa clôture n'aurait notifié aucun ticket ni réveillé son parent.

Le programme lancé est un vrai process Python qui recopie son environnement dans un fichier :
on vérifie ce que la reprise reçoit réellement, pas un appel simulé.
"""
from __future__ import annotations

import json
import sys
import time

import psutil

from bouzecode.web_v2.runtime.runner import agent_commande, agent_creation, agent_fiche
from bouzecode.web_v2.services.work import _persistence, tickets


def _programme_qui_note_son_env(sortie) -> list[str]:
    code = ("import json, os; json.dump({k: v for k, v in os.environ.items() "
            f"if k.startswith('BOUZECODE_')}}, open(r'{sortie}', 'w'))")
    return [sys.executable, "-c", code]


def test_la_reprise_herite_du_ticket_et_s_y_inscrit(monkeypatch, tmp_path):
    sortie = tmp_path / "env.json"
    monkeypatch.setattr(agent_commande, "_agent_cmd", lambda: _programme_qui_note_son_env(sortie))
    _persistence._save("proj", [{"id": "T9", "title": "t", "prompt": "p",
                                 "parent": "manager0001", "comments": [],
                                 "runs": [{"agent_id": "d44a8566ec89", "kind": "validate"}]}])
    parc = agent_fiche.AGENTS_DIR
    (parc / "d44a8566ec89.json").write_text(json.dumps({
        "agent_id": "d44a8566ec89", "prompt": "valider", "model": "m", "cwd": "", "pid": 0,
        "started_at": "2026-09-29T09:13:54Z", "returncode": -1,
        "session_path": str(parc / "d44a8566ec89.session.json"), "ipc_dir": "",
        "parent": "manager0001", "ticket_slug": "proj", "ticket_id": "T9",
        "run_kind": "validate", "profile": "coder",
    }), encoding="utf-8")

    nouveau = agent_creation.resume_agent(agent_fiche.load_agent("d44a8566ec89"), "Reprends.")
    psutil.Process(nouveau.pid).wait(timeout=20)
    for _ in range(50):  # le lanceur du venv attend son enfant, mais on reste prudent
        if sortie.exists():
            break
        time.sleep(0.1)

    fiche = agent_fiche.load_agent(nouveau.agent_id)
    assert (fiche.ticket_slug, fiche.ticket_id, fiche.run_kind) == ("proj", "T9", "validate")
    env = json.loads(sortie.read_text(encoding="utf-8"))
    assert env["BOUZECODE_TICKET_SLUG"] == "proj" and env["BOUZECODE_TICKET_ID"] == "T9"
    assert env["BOUZECODE_RUN_KIND"] == "validate"
    assert env["BOUZECODE_PARENT"] == "manager0001"
    [recent, ancien] = tickets.get_ticket("proj", "T9")["runs"]
    assert (recent["agent_id"], recent["kind"]) == (nouveau.agent_id, "validate")
    assert ancien["agent_id"] == "d44a8566ec89"
