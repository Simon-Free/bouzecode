# [desc] Vue d'enquête d'une session (page /enquete/<agent_id>) et ses routes JSON : frise, tour, élément, export, note, saturation, recherche. [/desc]
"""Comprendre pourquoi un agent déraille ou ce qui sature son contexte (SPEC §5.5)."""
from __future__ import annotations

import json

from flask import Blueprint, jsonify, make_response, render_template, request

from ._errors import erreur

from ..services.sessions import enquete as source
from ..services.sessions.enquete import frise, methodologie, recherche, saturation, tour

enquete_bp = Blueprint("enquete", __name__)


def _charger(agent_id: str):
    enquete = source.charger(agent_id)
    if enquete is None:
        return None, erreur("enquete_introuvable", f"aucune donnée d'enquête pour l'agent "
                            f"{agent_id} (agent inconnu, ou session sans journal de payloads)", 404)
    return enquete, None


@enquete_bp.get("/enquete/<agent_id>")
def enquete_page(agent_id: str):
    return render_template("enquete.html", page="enquete", agent_id=agent_id)


@enquete_bp.get("/api/enquete/<agent_id>/frise")
def api_frise(agent_id: str):
    """enquête : une ligne par tour {tour, horodatage, duree_s, plein_tarif, cache_lu, cache_ecrit,
    sortie, cout, outils[], marqueurs[]
    (entree|relance|enforcement|erreur|question|sous_agent|cloture_acceptee|cloture_refusee|compaction|cache_rate|saut_contexte),
    anormal} + total_cout, nb_anormaux ; 404 si agent inconnu ou sans journal de payloads"""
    enquete, err = _charger(agent_id)
    return err or jsonify(enquete.memoise("frise", lambda: frise.frise(enquete)))


@enquete_bp.get("/api/enquete/<agent_id>/tours/<int:n>")
def api_tour(agent_id: str, n: int):
    """enquête : payload du tour élément par élément {indice, cle, genre, libelle, tokens, cache,
    apercu, tronque, taille}, diff avec le tour précédent {rupture (1er élément qui casse le
    préfixe), ajoutes[], modifies[{indice, nature ajout_en_fin|modifie, position, avant,
    apres}], retires[]}, réponse du modèle {texte, reflexion, appels[], resultats[]}, appels
    annexes"""
    enquete, err = _charger(agent_id)
    if err:
        return err
    detail = enquete.memoise(f"tour:{n}", lambda: tour.detail(enquete, n))
    if detail is None:
        return erreur("tour_introuvable", f"tour {n} introuvable", 404)
    return jsonify(detail)


@enquete_bp.get("/api/enquete/<agent_id>/tours/<int:n>/elements/<int:i>")
def api_element(agent_id: str, n: int, i: int):
    """enquête : texte intégral d'un élément du payload du tour"""
    enquete, err = _charger(agent_id)
    if err:
        return err
    element = tour.element(enquete, n, i)
    if element is None:
        return erreur("element_introuvable", f"élément {i} du tour {n} introuvable", 404)
    return jsonify(element)


@enquete_bp.get("/api/enquete/<agent_id>/tours/<int:n>/export")
def api_export(agent_id: str, n: int):
    """enquête : payload brut du tour (journal des payloads) en pièce jointe JSON"""
    enquete, err = _charger(agent_id)
    if err:
        return err
    dump = enquete.dumps.get(n)
    if dump is None:
        return erreur("tour_introuvable", f"tour {n} introuvable", 404)
    resp = make_response(json.dumps(dump, ensure_ascii=False, indent=2))
    resp.headers["Content-Type"] = "application/json; charset=utf-8"
    resp.headers["Content-Disposition"] = f'attachment; filename="{agent_id}-tour-{n}.json"'
    return resp


@enquete_bp.get("/api/enquete/<agent_id>/methodologie")
def api_methodologie(agent_id: str):
    """enquête : histoire de la note de travail — courbe [{tour, taille}], compactions[], entrees
    [{tour, taille, ajoute, retire, compaction, disparu, appels[]}] ; ?q= filtre"""
    enquete, err = _charger(agent_id)
    if err:
        return err
    q = request.args.get("q", "")
    if q:
        return jsonify(methodologie.historique(enquete, q))
    return jsonify(enquete.memoise("methodologie", lambda: methodologie.historique(enquete)))


@enquete_bp.get("/api/enquete/<agent_id>/saturation")
def api_saturation(agent_id: str):
    """enquête : composition du contexte par tour (systeme, note_prose, note_extraits,
    resultats_outils, messages en tokens estimés) + 20 plus gros morceaux (sections de note
    comprises) du tour ?tour= (défaut : dernier)"""
    enquete, err = _charger(agent_id)
    if err:
        return err
    n = request.args.get("tour", type=int)
    return jsonify(enquete.memoise(f"saturation:{n}", lambda: saturation.saturation(enquete, n)))


@enquete_bp.get("/api/enquete/<agent_id>/recherche")
def api_recherche(agent_id: str):
    """enquête : ?q= (2 car. min.) — occurrences {tour, ou note|payload|reponse|resultat:<outil>,
    indice, extrait} dans la note (ajouts), les payloads (sans doublons) et les réponses ; 200
    max"""
    enquete, err = _charger(agent_id)
    if err:
        return err
    return jsonify(recherche.rechercher(enquete, request.args.get("q", "")))
