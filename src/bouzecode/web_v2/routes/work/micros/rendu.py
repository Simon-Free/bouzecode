# [desc] Flask endpoints to submit and fetch the human report (rendu) for a micro-task, moving it to "À vérifier" [/desc]
from __future__ import annotations

from flask import jsonify, request

from ....services.work import rendu_humain
from ....services.work import taches_actions as actions
from ..._body import json_body
from . import micros_bp
from ._commun import _micro_or_404, _refus


@micros_bp.post("/api/micros/<micro_id>/rendu")
def api_micro_rendu(micro_id: str):
    """{answer (## 1. … ## 6.), recap{symptoms,explanation,tests?,changes[{file,summary}]},
    tests_detail{nombre,niveau,verts,chemin?}, commits[{sha,branche?}], taches_terminees[],
    taches_restantes[{titre,corps?,decision?,options?}], related_files[{path,label?,kind?}]?,
    auteur?, projet_slug?} — 400
    `rendu_incomplet` {manquants} ou `commit_inconnu` ; 201 {ticket_id} : la tâche passe
    « À vérifier » comme après la livraison d'un agent."""
    _micro, err = _micro_or_404(micro_id)
    if err:
        return err
    try:
        res = rendu_humain.enregistrer(micro_id, json_body(request))
    except actions.Refus as refus:
        return _refus(refus)
    return jsonify({"ok": True, **res}), 201


@micros_bp.get("/api/micros/<micro_id>/rendu")
def api_micro_rendu_lire(micro_id: str):
    """Le dernier rendu humain enregistré (null s'il n'y en a pas)."""
    _micro, err = _micro_or_404(micro_id)
    if err:
        return err
    return jsonify({"rendu": rendu_humain.dernier(micro_id)})
