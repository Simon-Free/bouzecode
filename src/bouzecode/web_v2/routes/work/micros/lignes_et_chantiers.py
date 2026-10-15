# [desc] Le Bureau rangé par chantier (`/api/lignes`) et les macro-tâches (chantiers) : créer, lister, réordonner, modifier, supprimer, rattacher un dépôt. [/desc]
from __future__ import annotations

from flask import jsonify, request

from ....services.work import bureau_lignes
from ....services.work import micros as service
from ..._body import json_body
from . import micros_bp
from ._commun import _fail, _macro_or_404, _micro_or_404


@micros_bp.get("/api/lignes")
def api_lignes():
    """le Bureau, rangé par chantier : {chantiers[], non_rattachees[], stats} — chaque tâche porte
    `statut_ui` (brouillon|a_decider|en_cours|a_repondre|a_relire|en_echec|faite|abandonnee),
    `segment`, `passages[]` (un par agent lancé : etat du lexique, récap fait/reste/à décider +
    `recap.suites` {reste, a_decider} : la tâche qui porte chaque point {id, titre, statut_ui,
    libelle_statut, lien: creee|existante|manuelle|titre} ou null, branche, integre, joignable),
    `projet_defaut`, `joignable`, `agent_actif`, `raison_echec`, `archive_auto` ({texte,
    branche, ticket_id, at} : tâche faite archivée automatiquement, sinon null), `classement`
    ({motif: faite|doublon|caduque, libelle, commentaire, auteur, at, lien: {id, titre}|null} :
    pourquoi une tâche classée l'a été, sinon null), `classements` (historique, rouverts compris
    : + rouvert_at, rouvert_par). Mémorisé ≤ 3 s. Contrat : docs/refonte_ui/api_contract.md §2.1

    toute la matière du Bureau en UNE liste, rangée par chantier (macro-tâche)

    Aucun paramètre : pas de fenêtre de temps (une ligne persistante ne doit pas
    s'évaporer parce qu'elle a huit jours), pas de filtre par statut (l'écran a déjà
    toutes les lignes en mémoire et filtre sans aller-retour). Le statut de chaque
    ligne est DÉDUIT ici, jamais saisi : `en_cours`, `inactif` + sa raison
    (`a_faire`, `a_decider`, `figee`, `a_relire`), ou `archive`."""
    #  La liste est ALLÉGÉE par défaut : sans `?complet=1`, les champs qui ne s'affichent
    #  qu'une fois la tâche dépliée (passages complets, brief, tickets…) ne sont pas servis
    #  — 2504 Ko retéléchargés toutes les 5 s. Le détail arrive par /api/lignes/<id>.
    #  `?detail=<id>,<id>` : les tâches DÉPLIÉES à l'écran sont servies COMPLÈTES. Sans ça,
    #  ce qu'on est en train de LIRE (passages, récap) se figerait au premier dépli.
    complets = {part.strip() for part in (request.args.get("detail") or "").split(",")
                if part.strip()}
    return jsonify(bureau_lignes.collect_lignes(
        leger=(request.args.get("complet") or "") != "1", complets=complets))


@micros_bp.get("/api/lignes/<micro_id>")
def api_ligne_detail(micro_id: str):
    """le DÉTAIL d'une ligne du Bureau : brief, précisions, tickets et TOUS ses passages
    (récap, rapport rendu en HTML). Chargé quand la tâche est DÉPLIÉE, jamais dans la liste."""
    _, erreur = _micro_or_404(micro_id)
    if erreur:
        return erreur
    ligne = bureau_lignes.ligne_complete(micro_id)
    if ligne is None:
        return _fail(f"ligne {micro_id} introuvable", 404, "ligne_introuvable")
    return jsonify({"ligne": ligne})


# --------------------------------------------------------------------- §10.1 les macros


@micros_bp.post("/api/macros")
def api_macro_create():
    """{titre, corps?, projets[]?} — crée un chantier multi-dépôts ; 400 sans titre"""
    body = json_body(request)
    titre = (body.get("titre") or "").strip()
    if not titre:
        return _fail("Un chantier a besoin d'un titre.", code="titre_requis")
    macro = service.create_macro(titre=titre,
                                 corps=(body.get("corps") or "").strip(),
                                 projets=body.get("projets") or [])
    return jsonify({"macro": macro}), 201


@micros_bp.get("/api/macros")
def api_macros_list():
    """les macro-tâches (filtre ?etat=active|en_pause|terminee|abandonnee)"""
    return jsonify({"macros": service.list_macros(etat=(request.args.get("etat") or "").strip())})


@micros_bp.post("/api/macros/reorder")
def api_macros_reorder():
    """fixe l'ordre d'affichage des chantiers (le glisser-déposer du Bureau)

    UN post pour toute la liste, et pas un PATCH par chantier : l'ordre est une propriété de
    LA LISTE. L'envoyer d'un bloc évite l'état intermédiaire incohérent (deux chantiers en
    position 3, un chantier sans position) qu'une rafale de PATCH laisserait derrière elle si
    le réseau coupait au milieu.
    """
    body = json_body(request)
    ordre = body.get("ordre")
    if ordre is None:
        ordre = body.get("order")
    if not isinstance(ordre, list):
        return _fail("ordre attendu : la liste des identifiants de chantiers, du haut vers le bas",
                     code="ordre_invalide")
    try:
        macros = service.reorder_macros([str(macro_id) for macro_id in ordre])
    except service.BriefInsuffisant as souci:
        return _fail(str(souci), code="ordre_invalide")
    return jsonify({"macros": macros, "chantiers": macros})


@micros_bp.get("/api/macros/<macro_id>")
def api_macro_detail(macro_id: str):
    """une macro-tâche, ses dépôts et ses micro-tâches ; 404 si inconnue"""
    macro, erreur = _macro_or_404(macro_id)
    if erreur:
        return erreur
    macro = dict(macro)
    macro["micros"] = service.list_micros(macro_id=macro_id)
    return jsonify({"macro": macro})


@micros_bp.patch("/api/macros/<macro_id>")
def api_macro_patch(macro_id: str):
    """{titre?, corps?, etat?} — renomme sans casser les rattachements ; 400 état inconnu"""
    _, erreur = _macro_or_404(macro_id)
    if erreur:
        return erreur
    body = json_body(request)
    champs = {clef: body[clef] for clef in ("titre", "corps", "etat") if clef in body}
    if "etat" in champs and champs["etat"] not in service.ETATS_MACRO:
        return _fail(f"état inconnu : {champs['etat']!r} (attendu {', '.join(service.ETATS_MACRO)})",
                     code="etat_inconnu")
    if not champs:
        return _fail("rien à modifier", code="rien_a_modifier")
    try:
        return jsonify({"macro": service.update_macro(macro_id, **champs)})
    except service.BriefInsuffisant:
        return _fail("Un chantier a besoin d'un titre.", code="titre_vide")


@micros_bp.delete("/api/macros/<macro_id>")
def api_macro_delete(macro_id: str):
    """supprime un chantier et DÉTACHE ses tickets — supprimer un rangement ne détruit pas son contenu"""
    _, erreur = _macro_or_404(macro_id)
    if erreur:
        return erreur
    return jsonify(service.delete_macro(macro_id) or {})


@micros_bp.post("/api/macros/<macro_id>/projets")
def api_macro_add_projet(macro_id: str):
    """{slug} — ajoute un dépôt au chantier en cours de route"""
    _, erreur = _macro_or_404(macro_id)
    if erreur:
        return erreur
    slug = (json_body(request).get("slug") or "").strip()
    if not slug:
        return _fail("slug est obligatoire", code="depot_requis")
    return jsonify({"macro": service.add_projet(macro_id, slug)})


@micros_bp.delete("/api/macros/<macro_id>/projets/<slug>")
def api_macro_remove_projet(macro_id: str, slug: str):
    """retire un dépôt d'un chantier (les tâches gardent leur dépôt propre)"""
    _, erreur = _macro_or_404(macro_id)
    if erreur:
        return erreur
    return jsonify({"macro": service.remove_projet(macro_id, slug)})


# ------------------------------------------------------ §10.2 les micros et le brouillon
