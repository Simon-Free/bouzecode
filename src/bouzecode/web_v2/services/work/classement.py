# [desc] Classer une tâche sans la lancer : faite ailleurs, doublon d'une autre, caduque — avec un commentaire, l'auteur (toi ou l'assistant) et la date, visibles sur la carte ; « Rouvrir » date la réouverture sans rien effacer. [/desc]
"""Pourquoi une tâche a quitté le Bureau sans qu'un agent la fasse.

Cas réel (chantier « Portail des énigmes », 2026-09-25) : « Corriger les 10 points » avait été
fait par la tâche principale lors de son tour de retours, « Relire la livraison » doublait la
carte « À vérifier », « Étendre le scraping » existait en trois exemplaires. Les classer
« Faite » ou « Abandonnée » d'un clic perdait la seule information utile : OÙ c'était fait, DE
QUOI c'était le doublon, et qui l'avait dit.

Trois motifs, deux états existants (aucun état nouveau dans le cycle de vie) :

* `faite`   → état `faite`       — fait ailleurs (`lien_id` : la tâche qui l'a fait, optionnel) ;
* `doublon` → état `abandonnee`  — `lien_id` OBLIGATOIRE : la tâche qui porte le travail ;
* `caduque` → état `abandonnee`  — plus d'objet.

Le changement d'état passe par `taches_actions.changer_etat` (archivage des agents, Rouvrir) ;
ce module n'ajoute que la trace. Jamais sur une tâche dont un agent est actif.
"""
from __future__ import annotations

from bouzecode.web_v2.services.horodatage import heure_locale, maintenant_iso

from . import micros

ETAT_DU_MOTIF = {"faite": "faite", "doublon": "abandonnee", "caduque": "abandonnee"}
LIBELLES = {"faite": "Faite", "doublon": "Doublon", "caduque": "Caduque"}
#  « agent » : un agent non-bureau (outil `TachesProjet`), signe dans son commentaire.
AUTEURS = ("humain", "assistant", "agent")
_CLASSES = ("faite", "abandonnee")


def _maintenant() -> str:
    return maintenant_iso()


def _auteur(auteur: str) -> str:
    return auteur if auteur in AUTEURS else "humain"


def _motif_ou_refus(motif: str) -> str:
    from .taches_actions import Refus
    motif = str(motif or "").strip().lower()
    if motif not in ETAT_DU_MOTIF:
        raise Refus("motif_inconnu", f"motif inconnu : {motif!r} (faite, doublon ou caduque)",
                    attendu=list(ETAT_DU_MOTIF))
    return motif


def _lien_ou_refus(micro: dict, motif: str, lien_id: str) -> str:
    """La tâche désignée (« fait par » / « doublon de ») : existante et différente."""
    from .taches_actions import Refus
    lien_id = str(lien_id or "").strip()
    if not lien_id:
        if motif == "doublon":
            raise Refus("lien_requis", "Doublon de quelle tâche ? Donne son id (`de`).")
        return ""
    if lien_id == micro["id"]:
        raise Refus("lien_invalide", "Une tâche ne peut pas être le doublon d'elle-même.")
    if micros.get_micro(lien_id) is None:
        raise Refus("lien_inconnu", f"tâche {lien_id} inconnue : vérifie son id.", 404)
    return lien_id


def _refus_si_agent_actif(micro: dict) -> None:
    from . import lexique
    from .taches_actions import Refus, agent_actif
    actif = agent_actif(micro) if micro.get("tickets") else None
    if actif is None:
        return
    raise Refus(
        "agent_actif",
        f"Un agent travaille encore sur « {micro.get('titre') or micro['id']} » (agent "
        f"{actif.get('agent_id') or '?'}, {lexique.libelle_etat(actif['etat']) or actif['etat']}) :"
        " elle n'est pas marquée. Attends sa livraison puis classe-la, ou arrête d'abord l'agent"
        " (bouton « Arrêter » de la tâche).", 409, agent_id=actif.get("agent_id", ""))


def _refus_si_deja_classee(micro: dict) -> None:
    from .taches_actions import Refus
    if micro.get("etat") not in _CLASSES:
        return
    actuel = actifs().get(micro["id"])
    raison = f" ({texte(actuel)})" if actuel else ""
    raise Refus("deja_classee",
                f"« {micro.get('titre') or micro['id']} » est déjà classée"
                f"{raison or ' ' + micro['etat']} : rouvre-la d'abord pour la reclasser.", 409)


def marquer(micro_id: str, motif: str, commentaire: str = "", lien_id: str = "",
            auteur: str = "humain") -> dict:
    """Classe la tâche (faite / doublon / caduque) et enregistre pourquoi. Lève `Refus`."""
    from .taches_actions import _micro_ou_refus, changer_etat
    motif = _motif_ou_refus(motif)
    micro = _micro_ou_refus(micro_id)
    lien_id = _lien_ou_refus(micro, motif, lien_id)
    _refus_si_agent_actif(micro)
    _refus_si_deja_classee(micro)
    resultat = changer_etat(micro_id, ETAT_DU_MOTIF[motif])
    with micros._tx() as conn:
        conn.execute(
            "INSERT INTO micro_classements (id, micro_id, motif, commentaire, lien_id, auteur, at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (micros._id(), micro_id, motif, str(commentaire or "").strip(), lien_id,
             _auteur(auteur), _maintenant()))
    return {**resultat, "classement": actifs().get(micro_id)}


def noter_reouverture(micro_id: str, par: str = "humain") -> None:
    """« Rouvrir » : le classement en cours est daté, pas effacé (historique conservé)."""
    with micros._tx() as conn:
        conn.execute("UPDATE micro_classements SET rouvert_at = ?, rouvert_par = ?"
                     " WHERE micro_id = ? AND rouvert_at = ''",
                     (_maintenant(), _auteur(par), micro_id))


# ------------------------------------------------------------------------------ lecture

_SELECT = ("SELECT c.micro_id, c.motif, c.commentaire, c.lien_id, c.auteur, c.at, c.rouvert_at,"
           " c.rouvert_par, COALESCE(l.titre, '') FROM micro_classements c"
           " LEFT JOIN micros l ON l.id = c.lien_id")


def _vue(ligne: tuple) -> dict:
    micro_id, motif, commentaire, lien_id, auteur, at, rouvert_at, rouvert_par, lien_titre = ligne
    return {"micro_id": micro_id, "motif": motif, "libelle": LIBELLES.get(motif, motif),
            "commentaire": commentaire, "auteur": auteur, "at": at,
            "lien": {"id": lien_id, "titre": lien_titre} if lien_id else None,
            "rouvert_at": rouvert_at, "rouvert_par": rouvert_par}


def actifs() -> dict[str, dict]:
    """`{micro_id: classement}` des classements NON rouverts — UNE requête pour tout l'écran."""
    with micros._tx() as conn:
        lignes = conn.execute(_SELECT + " WHERE c.rouvert_at = '' ORDER BY c.at, c.rowid").fetchall()
    return {ligne[0]: _vue(ligne) for ligne in lignes}


def historiques() -> dict[str, list[dict]]:
    """`{micro_id: [classements, du plus ancien au plus récent]}`, rouverts compris."""
    with micros._tx() as conn:
        lignes = conn.execute(_SELECT + " ORDER BY c.at, c.rowid").fetchall()
    par_micro: dict[str, list[dict]] = {}
    for ligne in lignes:
        par_micro.setdefault(ligne[0], []).append(_vue(ligne))
    return par_micro


def _date_courte(iso: str) -> str:
    return heure_locale(iso, "%d/%m %H:%M")


def texte(classement: dict | None) -> str:
    """La phrase de la carte, pour l'assistant : « Faite — … (commentaire de l'assistant, 25/09
    03:12) ». Le Bureau compose la même en JS (`bureau/classement.js`)."""
    if not classement:
        return ""
    lien = classement.get("lien") or {}
    cible = f"« {lien.get('titre') or lien.get('id')} » [{lien.get('id')}]" if lien else ""
    tete = {"faite": f"Faite{' par ' + cible if cible else ''}",
            "doublon": f"Doublon de {cible}"}.get(classement["motif"], classement["libelle"])
    qui = {"assistant": "l'assistant", "agent": "un agent"}.get(classement.get("auteur"),
                                                                 "l'utilisateur")
    de_qui = "d'un agent" if qui == "un agent" else f"de {qui}"
    quoi = f"commentaire {de_qui}" if classement.get("commentaire") else f"marquée par {qui}"
    corps = f" — {classement['commentaire']}" if classement.get("commentaire") else ""
    return f"{tete}{corps} ({quoi}, {_date_courte(classement.get('at') or '')})"
