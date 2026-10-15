# [desc] « À traiter » du Bureau et pastilles de la navigation (SPEC §3, §4.2). [/desc]
from __future__ import annotations

from flask import Blueprint, jsonify

from ...services.work import inbox

inbox_bp = Blueprint("inbox_api", __name__)


@inbox_bp.get("/api/inbox")
def api_inbox():
    """« À traiter » du Bureau : {items:[{id, type:
    question|plan|a_relire|en_echec|agent_arrete|lancement_echoue|decision|signalement, urgence,
    depuis, titre, agent_id, key, tache?, question?, recap?, raison?, actions[]}], compte} —
    tous agents confondus, une carte par tâche, tri urgence puis ancienneté. `signalement`
    (outil Signaler, non bloquant) : +{signalement_id, gravite: info|alerte|bloquant, detail,
    action_attendue, profondeur, parents[], ticket_id}, urgence 0 bloquant / 1 alerte / 2 info,
    actions [acquitter, ouvrir]. `agent_arrete` couvre aussi un SOUS-agent arrêté dont aucun
    parent vivant ne peut s'occuper (`sous_agent: true`, `parent`)."""
    return jsonify(inbox.construire())


@inbox_bp.get("/api/nav/counts")
def api_nav_counts():
    """pastilles de la navigation → {a_moi, inbox, en_cours} — `a_moi`/`inbox` = le compte de LA
    boîte de GET /api/inbox (même mémoire, clé = génération des écritures de tâches + génération
    du parc : recalculée dès qu'une tâche est écrite ou qu'un agent change d'état ; même clé et
    plus de 3 s → servie aussitôt et recalculée en fond), `en_cours` = les agents que l'arbre
    servi montre au travail

    Pas de TTL : `a_moi`/`inbox` viennent de LA boîte, mémorisée sous la clé
    `taches_vue.cle_courante` (elle change à chaque écriture de tâche et à chaque
    changement d'état d'agent), servie aussitôt et recalculée en fond."""
    return jsonify(inbox.compteurs())
