# [desc] Blueprint HTTP des tâches v1 (POST/GET/PATCH /api/tasks, migration) et GET /api/board (lecture pure). [/desc]
"""Les tâches du Bureau, côté HTTP.

Le docstring de CHAQUE vue est ce que sert `/api/schema` (cf. `tests/test_schema_coverage.py`) :
une vue sans docstring fait échouer la suite, ce n'est pas de la décoration.

`GET /api/board` est le chemin de lecture chaud de la page : aucun git, aucun LLM, aucun appel à
`/api/agents/tree`, et surtout AUCUNE écriture — l'état d'une tâche d'agent est dérivé à la volée
par `board.build_board()`, jamais persisté depuis une lecture.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ...services.work import _board_live, board, tasks
from .._body import json_body
from .._errors import erreur

tasks_bp = Blueprint("tasks_api", __name__)

_PATCHABLE = ("title", "intent", "next_step", "policy", "snoozed_until", "project_slug")


def _task_or_404(task_id: str):
    task = tasks.get_task(task_id)
    if task is None:
        return None, erreur("tache_inconnue", f"tâche {task_id} inconnue", 404)
    return task, None


@tasks_bp.post("/api/tasks/<task_id>/migrer")
def migrer_task(task_id: str):
    """{projet_slug?, macro_id?} — transforme une tâche héritée (créée avant la garde G1) en
    micro-tâche BROUILLON : titre → titre, pourquoi → corps. La tâche v1 est close avec outcome
    `migre` (rien n'est supprimé, elle reste lisible via ?closed=1). 409 si elle est déjà close,
    404 si inconnue. Migrer n'est PAS lancer : le brouillon ne dispatche rien."""
    from ...services.work import micros as micros_service

    task, refus = _task_or_404(task_id)
    if refus:
        return refus
    #  La tâche v1 est CLOSE par sa migration : son `closed_at` est donc la trace de
    #  migration. Une seconde migration ne doit pas fabriquer un second brouillon.
    if (task.get("closed_at") or "").strip():
        return erreur("deja_close", "cette ligne est déjà close (migrée ou archivée) : son "
                      "brouillon existe, ou elle a été écartée", 409)
    body = json_body(request)
    micro = micros_service.create_micro(
        titre=task["title"],
        #  Le pourquoi n'est PAS jeté : il devient le corps, c'est-à-dire le brief de l'agent.
        corps=(task.get("intent") or "").strip(),
        projet_slug=(body.get("projet_slug") or task.get("project_slug") or "").strip(),
        macro_id=(body.get("macro_id") or "").strip(),
        origine="humain",
    )
    #  Aucune suppression : la ligne reste consultable via `GET /api/tasks?closed=1`, avec
    #  `outcome='migre'` qui dit POURQUOI elle a quitté l'écran.
    tasks.close_task(task_id, outcome="migre")
    tasks.add_event(task_id, actor="moi", kind="state",
                    label=f"migrée en micro-tâche {micro['id']} (brouillon)")
    return jsonify({"micro": micro, "task_id": task_id}), 201


@tasks_bp.post("/api/tasks")
def create_task():
    """crée une tâche (ce que je veux obtenir) depuis la barre de capture du Bureau"""
    body = json_body(request)
    title = (body.get("title") or "").strip()
    if not title:
        return erreur("champ_requis", "title est obligatoire", 400, champs=["title"])
    owner = body.get("owner") or "agent"
    if owner not in ("agent", "moi"):
        return erreur("owner_inconnu", "owner doit valoir 'agent' ou 'moi'", 400)
    #  G1 (§4 de docs/bureau-todo-modele-et-api.md) : « rien n'entre dans la TO-DO sans son
    #  porteur ». Un porteur, c'est un dépôt PLUS (un ticket ou un pourquoi écrit). Un titre
    #  seul n'est pas un porteur — c'est exactement ce qui a produit les 14 lignes nues.
    project_slug = (body.get("project_slug") or "").strip()
    pourquoi = (body.get("intent") or body.get("pourquoi") or "").strip()
    ticket = (body.get("ticket") or "").strip()
    if not project_slug:
        return erreur("champ_requis", "project_slug est obligatoire : une tâche sans dépôt "
                      "n'a pas de porteur", 400, champs=["project_slug"])
    if not (pourquoi or ticket):
        return erreur("porteur_requis", "il faut un ticket ou un pourquoi (intent) : un titre "
                      "seul n'est pas un porteur", 400)
    task = tasks.create_task(
        title=title,
        intent=pourquoi,
        project_slug=project_slug,
        owner=owner,
        policy=body.get("policy") or "observer",
        note_anchor=(body.get("note_anchor") or "").strip(),
    )
    tasks.add_event(task["id"], actor="moi", kind="state", label="tâche créée")
    return jsonify({"task": task}), 201


@tasks_bp.get("/api/tasks")
def list_tasks():
    """liste les tâches ; ?closed=1 inclut les tâches déjà closes"""
    include_closed = request.args.get("closed") in ("1", "true", "yes")
    return jsonify({"tasks": tasks.list_tasks(include_closed=include_closed)})


@tasks_bp.patch("/api/tasks/<task_id>")
def patch_task(task_id: str):
    """modifie une tâche : titre, intention, prochaine action, politique, mise en sommeil"""
    task, error = _task_or_404(task_id)
    if error:
        return error
    body = json_body(request)
    fields = {key: body[key] for key in _PATCHABLE if key in body}
    if "state" in body:
        # L'état d'une tâche d'agent est DÉRIVÉ de ses tickets : l'écrire à la main créerait une
        # seconde vérité, qui divergerait au premier changement de statut de ticket.
        if task["owner"] != "moi":
            return erreur("state_derive", "state ne se saisit que sur une tâche owner='moi'",
                          400)
        fields["state"] = body["state"]
    if not fields:
        return erreur("champ_requis", "aucun champ modifiable dans le corps", 400,
                      champs=list(_PATCHABLE))
    updated = tasks.update_task(task_id, **fields)
    tasks.add_event(task_id, actor="moi", kind="note",
                    label="modification : " + ", ".join(sorted(fields)))
    return jsonify({"task": updated})


@tasks_bp.get("/api/board")
def get_board():
    """le Bureau en un seul appel : les tâches vivantes, leur état dérivé et leurs tickets

    Par défaut le board ne porte que le vivant (`_board_live.keep_live`) : les tâches closes et
    les tâches d'agent que personne n'a lancées restent en base mais sortent de la vue. Avec
    `?closed=1` on rend les archives telles quelles — c'est le seul appel qui les charge, et il
    n'a lieu qu'au clic sur le compteur, pour ne pas payer 218 tâches à chaque rafraîchissement."""
    if request.args.get("closed") in ("1", "true", "yes"):
        return jsonify(board.build_board(include_closed=True))
    payload = _board_live.keep_live(board.build_board())
    payload["counts"]["closes"] = tasks.count_closed_tasks()
    return jsonify(payload)
