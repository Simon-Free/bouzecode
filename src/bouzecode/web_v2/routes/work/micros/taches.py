# [desc] Les micro-tâches du Bureau : créer (brouillon), lister, lire, modifier, précisions (append-only, validées par l'humain), prêt, état, classement. [/desc]
from __future__ import annotations

from flask import jsonify, request

from ....services.work import classement
from ....services.work import micros as service
from ....services.work import taches_actions as actions
from ..._body import json_body
from . import micros_bp
from ._commun import _fail, _micro_or_404, _refus


@micros_bp.post("/api/micros")
def api_micro_create():
    """{titre, corps?, macro_id?|macro_titre?, projet_slug?, origine?, decision?, branche_cible?} —
    naît BROUILLON, ne dispatche rien ; 400 sans titre. `branche_cible` (sinon lue dans le titre
    / brief d'un « Fusionner / Intégrer la branche agent/XXXX ») : le brouillon est archivé
    automatiquement quand cette branche est intégrée"""
    body = json_body(request)
    corps = (body.get("corps") or "").strip()
    #  Le Bureau n'a plus qu'UNE zone de saisie : le corps. Quand il est seul, le titre en est
    #  dérivé (première ligne non vide) au lieu de refuser la capture par un 400.
    titre = (body.get("titre") or "").strip() or service.titre_depuis_corps(corps)
    if not titre:
        return _fail("Une tâche a besoin d'un titre.", code="titre_requis")
    macro_id = (body.get("macro_id") or "").strip()
    macro_titre = (body.get("macro_titre") or "").strip()
    #  Un agent qui nomme sa macro par son TITRE ne doit plus fabriquer une section de plus :
    #  on résout sur le titre normalisé, donc deux orthographes retombent sur le même id.
    if not macro_id and macro_titre:
        macro_id = service.ensure_macro(macro_titre)["id"]
    origine = (body.get("origine") or "humain").strip()
    if origine not in service.ORIGINES:
        return _fail(f"origine inconnue : {origine!r} (attendu {', '.join(service.ORIGINES)})",
                     code="origine_inconnue")
    micro = service.create_micro(titre=titre,
                                 corps=corps,
                                 macro_id=macro_id,
                                 projet_slug=(body.get("projet_slug") or "").strip(),
                                 origine=origine,
                                 decision=bool(body.get("decision")),
                                 branche_cible=body.get("branche_cible"))
    return jsonify({"micro": micro}), 201


@micros_bp.get("/api/micros")
def api_micros_list():
    """les micro-tâches persistantes (filtres ?macro_id= &etat= &projet=)"""
    return jsonify({"micros": service.list_micros(
        #  `None` et `""` ne veulent PAS dire la même chose : `""` filtre sur les micros SANS
        #  macro, l'absence d'argument ne filtre rien. Passer `""` par défaut cachait toutes
        #  les micros rattachées à un chantier.
        macro_id=(request.args.get("macro_id").strip()
                  if request.args.get("macro_id") is not None else None),
        etat=(request.args.get("etat") or "").strip(),
        projet=(request.args.get("projet") or "").strip())})


@micros_bp.get("/api/micros/<micro_id>")
def api_micro_detail(micro_id: str):
    """titre, corps, précisions, tickets, et le `prompt` qui partirait à l'agent"""
    micro, erreur = _micro_or_404(micro_id)
    if erreur:
        return erreur
    return jsonify({"micro": micro})


@micros_bp.patch("/api/micros/<micro_id>")
def api_micro_patch(micro_id: str):
    """{titre?, corps?, macro_id?, projet_slug?, decision?} — on revient dessus autant qu'on veut"""
    _, erreur = _micro_or_404(micro_id)
    if erreur:
        return erreur
    body = json_body(request)
    champs = {clef: body[clef]
              for clef in ("titre", "corps", "macro_id", "projet_slug", "decision")
              if clef in body}
    if "titre" in champs and not str(champs["titre"]).strip():
        return _fail("Un titre vide effacerait la tâche de la liste.", code="titre_vide")
    if not champs:
        return _fail("rien à modifier", code="rien_a_modifier")
    return jsonify({"micro": service.update_micro(micro_id, **champs)})


@micros_bp.post("/api/micros/<micro_id>/precisions")
def api_micro_precision(micro_id: str):
    """{texte, auteur?, transmettre?, interrompre?, sous_agents?} — ajout APPEND-ONLY au brief ;
    transmettre = la donner aussi à l'agent en cours (lue à sa prochaine frontière de tour, ou
    tour coupé si interrompre)

    ajoute une précision : APPEND-ONLY, jamais un écrasement. `transmettre: true` la donne
    aussi à l'agent en cours (lue à sa prochaine frontière de tour ; `interrompre: true` coupe
    son tour ; `sous_agents: true` l'étend à ses sous-agents joignables)."""
    _, erreur = _micro_or_404(micro_id)
    if erreur:
        return erreur
    body = json_body(request)
    texte = (body.get("texte") or "").strip()
    if not texte:
        return _fail("texte est obligatoire", code="texte_requis")
    try:
        resultat = actions.preciser(micro_id, texte, auteur=(body.get("auteur") or "humain").strip(),
                                    transmettre=bool(body.get("transmettre")),
                                    interrompre=bool(body.get("interrompre")),
                                    sous_agents=bool(body.get("sous_agents")))
    except actions.Refus as refus:
        return _refus(refus)
    #  Un renvoi identique récent n'a rien créé : 200, et `doublon` le dit.
    return jsonify(resultat), 200 if resultat.get("doublon") else 201


@micros_bp.post("/api/micros/<micro_id>/precisions/<precision_id>/valider")
def api_micro_precision_valider(micro_id: str, precision_id: str):
    """{texte?} — l'arbitrage humain : garder tel quel ou corriger"""
    _, erreur = _micro_or_404(micro_id)
    if erreur:
        return erreur
    texte = (json_body(request).get("texte") or "").strip()
    precision = service.valider_precision(micro_id, precision_id, texte=texte or None)
    if precision is None:
        return _fail(f"précision {precision_id} inconnue sur {micro_id}", 404, "precision_inconnue")
    return jsonify({"precision": precision, "micro": service.get_micro(micro_id)})


@micros_bp.delete("/api/micros/<micro_id>/precisions/<precision_id>")
def api_micro_precision_jeter(micro_id: str, precision_id: str):
    """jette une précision non validée"""
    _, erreur = _micro_or_404(micro_id)
    if erreur:
        return erreur
    if not service.supprimer_precision(micro_id, precision_id):
        return _fail(f"précision {precision_id} inconnue sur {micro_id}", 404, "precision_inconnue")
    return jsonify({"ok": True, "micro": service.get_micro(micro_id)})


@micros_bp.post("/api/micros/<micro_id>/pret")
def api_micro_pret(micro_id: str):
    """geste explicite ; 400 si titre vide ou si ni projet ni macro"""
    micro, erreur = _micro_or_404(micro_id)
    if erreur:
        return erreur
    if not (micro.get("titre") or "").strip():
        return _fail("un brief sans titre n'est pas prêt", code="titre_requis")
    if not ((micro.get("projet_slug") or "").strip() or (micro.get("macro_id") or "").strip()):
        return _fail("il faut un projet ou une macro-tâche : sans ça, personne ne sait où travailler",
                     code="projet_requis")
    return jsonify({"micro": service.marquer_etat(micro_id, "prete")})


@micros_bp.post("/api/micros/<micro_id>/etat")
def api_micro_etat(micro_id: str):
    """{etat, pourquoi?, auteur?} — faite · abandonnee (arrête d'abord l'agent actif → `arretes`) ·
    brouillon (Rouvrir, aussi depuis faite/abandonnee ; date la réouverture du classement
    motivé, sans l'effacer). 409 `transition_refusee` / `agent_actif`

    faite, abandonnée, ou retour en brouillon (« Rouvrir »)

    Abandonner une tâche dont l'agent tourne ARRÊTE d'abord cet agent (réponse `arretes`).
    Rouvrir ou classer « faite » pendant qu'un agent tourne est refusé (409 `agent_actif`).
    La raison éventuelle (`pourquoi`) DEVIENT une précision : un échec enrichit le brief."""
    body = json_body(request)
    try:
        return jsonify(actions.changer_etat(micro_id, (body.get("etat") or "").strip(),
                                            pourquoi=(body.get("pourquoi") or "").strip(),
                                            auteur=(body.get("auteur") or "").strip()))
    except actions.Refus as refus:
        return _refus(refus)


@micros_bp.post("/api/micros/<micro_id>/classer")
def api_micro_classer(micro_id: str):
    """{motif: faite|doublon|caduque, commentaire?, de?, auteur?: humain|assistant} — classe la
    tâche sans la lancer en disant pourquoi (faite → faite ; doublon/caduque → abandonnee ; `de`
    = la tâche qui l'a faite / dont c'est le doublon, obligatoire pour doublon). Rend {micro,
    classement, archives}. 409 `agent_actif` (agent en cours : arrête-le ou attends sa
    livraison) / `deja_classee` ; 400 `lien_requis` / `motif_inconnu` ; 404 `lien_inconnu`

    classe une tâche sans la lancer, en disant pourquoi : `motif` faite (fait ailleurs ;
    `de` = la tâche qui l'a fait, optionnel) | doublon (`de` obligatoire) | caduque, avec un
    `commentaire` et l'`auteur` (humain | assistant). 409 `agent_actif` si un agent travaille
    dessus, 409 `deja_classee` si elle est déjà classée. « Rouvrir » (/etat brouillon) garde
    l'historique."""
    body = json_body(request)
    try:
        return jsonify(classement.marquer(
            micro_id, (body.get("motif") or "").strip(),
            commentaire=(body.get("commentaire") or "").strip(),
            lien_id=(body.get("de") or "").strip(),
            auteur=(body.get("auteur") or "").strip()))
    except actions.Refus as refus:
        return _refus(refus)
