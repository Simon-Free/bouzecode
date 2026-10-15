# [desc] Les gestes d'une micro-tâche : lancer un passage, aperçu du prompt, relancer, arrêter, intégrer le travail d'un passage, créer la tâche d'une suite. [/desc]
from __future__ import annotations

from flask import jsonify, request

from ....services.work import micros as service
from ....services.work import suites_cloture
from ....services.work import taches_actions as actions
from ..._body import json_body
from . import micros_bp
from ._commun import _micro_or_404, _refus


@micros_bp.post("/api/micros/<micro_id>/lancer")
def api_micro_lancer(micro_id: str):
    """{projet_slug?, profil?, isolation?, parent?} — lance un NOUVEAU passage (prompt = brief +
    historique des passages + retours) → {ok, ticket_id, launch_key, projet_slug, micro}.
    `parent` = agent_id de l'agent qui lance (assistant du Bureau) : le ticket lui est rattaché,
    il est réveillé à la fin ou à la question de l'agent. Dépôt : demandé, sinon celui de la
    tâche, sinon le 1er du chantier. 400 `depot_requis`/`depot_inconnu` (+suggestions), 409
    `deja_en_cours`/`archivee`, 503 `env_indisponible` (relayé tel quel depuis la création de
    ticket). Un échec laisse la tâche brouillon. `execution?` = {cible: local|rundeck,
    projets[], fichiers_non_suivis{slug:[chemins]}} : mémorisée sur la tâche, posée sur le
    ticket, injectée dans le prompt ; réponse +{execution, distant?} ; 400
    `cible_inconnue`/`fichiers_invalides`, 501 `cible_indisponible` (rundeck sans
    `bouzecode.remote`), 502 `lancement_impossible` (refus du lanceur distant) — cf.
    docs/specs/assistant_execution.md.

    lance un NOUVEAU passage d'agent sur la tâche — le brief et l'historique partent ensemble

    Dépôt : `projet_slug` demandé, sinon celui de la tâche, sinon le 1er du chantier, sinon 400
    `depot_requis` (plus AUCUN repli implicite). Un dispatch qui échoue laisse la tâche en
    brouillon et rend une erreur HTTP lisible. 409 `deja_en_cours` si un agent tourne déjà.
    `parent` (optionnel) : l'agent qui lance (l'assistant du Bureau) — le ticket lui est
    rattaché et il est réveillé quand l'agent finit ou pose une question. `execution`
    (optionnel) : {cible local|rundeck, projets, fichiers_non_suivis} ; 501
    `cible_indisponible` si rundeck est demandé sans lanceur distant installé."""
    body = json_body(request)
    try:
        return jsonify(actions.lancer(
            micro_id,
            projet_slug=(body.get("projet_slug") or "").strip(),
            profil=(body.get("profil") or "").strip(),
            isolation=(body.get("isolation") or "").strip(),
            parent=(body.get("parent") or "").strip(),
            execution=_execution(body)))
    except actions.Refus as refus:
        return _refus(refus)


def _execution(body: dict) -> dict | None:
    """`execution` = {cible: local|rundeck, projets: [slug], fichiers_non_suivis: {slug:
    [chemins]}} (cf. services/work/taches_execution.py). Absent : lancement ordinaire."""
    execution = body.get("execution")
    return execution if isinstance(execution, dict) and execution else None


@micros_bp.get("/api/micros/<micro_id>/prompt")
def api_micro_prompt(micro_id: str):
    """?retour= — aperçu du prompt du prochain passage → {prompt, passages_inclus, retours_inclus,
    caracteres}"""
    micro, erreur = _micro_or_404(micro_id)
    if erreur:
        return erreur
    return jsonify(actions.prompt_assemble(micro, request.args.get("retour") or ""))


@micros_bp.post("/api/micros/<micro_id>/relancer")
def api_micro_relancer(micro_id: str):
    """{retour?, mode?: continuer|nouvel_agent, projet_slug?, profil?, isolation?, parent?,
    execution?} — nouvelle itération : le retour rejoint l'historique ; `continuer` l'envoie à
    l'agent du dernier passage (défaut s'il est joignable), `nouvel_agent` lance un passage avec
    le contexte assemblé. 409 `non_joignable`/`deja_en_cours`/`archivee`.

    nouvelle itération avec un retour : même agent (`continuer`) ou nouvel agent

    `mode` par défaut : `continuer` si l'agent du dernier passage est joignable, sinon
    `nouvel_agent`. Le retour est ajouté à l'historique de la tâche dans les deux cas."""
    body = json_body(request)
    try:
        return jsonify(actions.relancer(
            micro_id,
            retour=(body.get("retour") or "").strip(),
            mode=(body.get("mode") or "").strip(),
            projet_slug=(body.get("projet_slug") or "").strip(),
            profil=(body.get("profil") or "").strip(),
            isolation=(body.get("isolation") or "").strip(),
            parent=(body.get("parent") or "").strip(),
            execution=_execution(body)))
    except actions.Refus as refus:
        return _refus(refus)


@micros_bp.post("/api/micros/<micro_id>/arreter")
def api_micro_arreter(micro_id: str):
    """arrête l'agent (ou le lancement) actif de la tâche → {ok, arretes[], erreurs[], micro} ; 409
    `rien_a_arreter`, 502 `arret_refuse`"""
    try:
        return jsonify(actions.arreter(micro_id))
    except actions.Refus as refus:
        return _refus(refus)


@micros_bp.post("/api/micros/<micro_id>/passages/<ticket_id>/integrer")
def api_micro_integrer(micro_id: str, ticket_id: str):
    """intègre EN FOND le travail d'un passage : client de POST
    /api/projects/{slug}/tickets/{id}/integrate (même service, MÊMES codes relayés tels quels) →
    202 {ok, state: integrating, message} ; 409 `rien_a_integrer` (aucun fichier de code en
    avance) / `agent_actif` / `conflit_en_cours` / `pas_isole` / `transition_refusee`, 404
    `passage_inconnu`

    intègre (merge, EN FOND) le travail d'un passage dans la branche de base de son dépôt :
    client de `POST /api/projects/{slug}/tickets/{id}/integrate`, mêmes codes d'erreur → 202"""
    try:
        return jsonify(actions.integrer(micro_id, ticket_id)), 202
    except actions.Refus as refus:
        return _refus(refus)


@micros_bp.post("/api/micros/<micro_id>/passages/<ticket_id>/suites")
def api_micro_suite(micro_id: str, ticket_id: str):
    """crée la tâche d'un point « reste à faire / à décider » du récap d'un passage resté sans
    tâche {libelle, decision} → 201 {ok, micro, deja:false} ; 200 {deja:true} si le point a déjà
    sa tâche ; 404 `passage_inconnu` / `tache_inconnue`, 400 `libelle_requis`

    crée la tâche d'un point « reste à faire / à décider » du récap d'un passage, restée sans
    tâche ; idempotent (`deja: true` si le point a déjà sa tâche)"""
    body = json_body(request)
    try:
        resultat = suites_cloture.creer(micro_id, ticket_id, body.get("libelle") or "",
                                        bool(body.get("decision")))
    except actions.Refus as refus:
        return _refus(refus)
    return jsonify(resultat), 200 if resultat["deja"] else 201


@micros_bp.post("/api/micros/<micro_id>/passages/<ticket_id>/revert")
def api_micro_revert(micro_id: str, ticket_id: str):
    """demande le rollback d'un passage intégré {motif?} : crée la tâche qui ordonne
    `git revert -m 1 <merge_commit>` → 201 {ok, micro, deja:false, merge_commit} ; 200
    {deja:true} si déjà demandé ; 404 `passage_inconnu` / `tache_inconnue`, 409 `pas_integre`"""
    from ....services.work import rollback
    body = json_body(request)
    try:
        resultat = rollback.demander(micro_id, ticket_id, str(body.get("motif") or ""))
    except actions.Refus as refus:
        return _refus(refus)
    return jsonify(resultat), 200 if resultat["deja"] else 201
