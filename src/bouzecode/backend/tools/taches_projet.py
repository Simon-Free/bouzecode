"""Outil `TachesProjet` : la TODO des chantiers du projet, pour TOUT agent (pas seulement le Bureau).

Beaucoup de taches de la TODO sont resolues plus tard, au fil d'un autre ticket : l'agent qui
vient de resoudre un point doit pouvoir le VOIR et le CLASSER, sinon la liste pourrit.

Perimetre : les projets du ticket porteur (`BOUZECODE_TICKET_SLUG`, virgules acceptees) — une tache y
entre si son depot (`projet_slug`) en fait partie, ou si son chantier est rattache a l'un d'eux.
Lecture : `lister`, `rechercher`. Ecriture limitee au CLASSEMENT (`marquer_faite`,
`marquer_doublon`, `marquer_caduque`), commentaire obligatoire, signe de l'agent et de son ticket
(auteur « agent »). Creer, lancer, relancer, clore, preciser, deplacer, repondre, decider restent
au profil bureau (outil `Taches`). Meme route que le Bureau : refus si un agent travaille dessus.
"""
from __future__ import annotations

import difflib
import os
import re
import unicodedata

from . import bureau_tools as _b

ACTIONS = ["lister", "rechercher", "marquer_faite", "marquer_doublon", "marquer_caduque",
           "explorer", "ranger_ma_tache"]
_RESERVEES = {"creer", "modifier", "preciser", "deplacer", "lancer", "relancer", "clore",
              "rouvrir", "repondre", "vue_ensemble", "decider"}
_MOTIFS = {"marquer_faite": "faite", "marquer_doublon": "doublon", "marquer_caduque": "caduque"}
_BRIEF_MAX = 400


def projets_de_l_agent() -> list[str]:
    """Les slugs de projet du ticket porteur, lus a l'appel (l'agent ne les choisit pas)."""
    brut = os.environ.get("BOUZECODE_TICKET_SLUG") or ""
    return [s.strip() for s in brut.split(",") if s.strip()]


def signature() -> str:
    """« [agent <id> · ticket <id>] » : qui a pose la marque, visible sur la carte."""
    agent = _b._moi().get("parent") or os.environ.get("BOUZECODE_AGENT_ID") or ""
    ticket = os.environ.get("BOUZECODE_TICKET_ID") or ""
    morceaux = [f"agent {agent}" if agent else "agent"]
    if ticket:
        morceaux.append(f"ticket {ticket}")
    return "[" + " · ".join(morceaux) + "]"


def _slug(projet) -> str:
    if isinstance(projet, dict):
        return _b._s(projet.get("slug") or projet.get("projet_slug"))
    return _b._s(projet)


def _lignes_du_perimetre(projets: list[str]) -> list[dict]:
    from bouzecode.web_v2.services.work import bureau_lignes
    voulus = set(projets)
    vue = bureau_lignes.collect_lignes()
    lignes = []
    for chantier in vue.get("chantiers") or []:
        rattache = bool(voulus & {_slug(p) for p in chantier.get("projets") or []})
        lignes += [l for l in chantier.get("lignes") or []
                   if rattache or _b._s(l.get("projet_slug")) in voulus]
    lignes += [l for l in vue.get("non_rattachees") or []
               if _b._s(l.get("projet_slug")) in voulus]
    return lignes


def _vue(ligne: dict) -> dict:
    vue = _b._resume(ligne)
    brief = _b._s(ligne.get("corps") or ligne.get("intent")).strip()
    if brief:
        vue["brief"] = brief if len(brief) <= _BRIEF_MAX else brief[:_BRIEF_MAX] + "…"
    return vue


def _filtrer(lignes: list[dict], p: dict) -> list[dict]:
    if not p.get("include_closed"):
        lignes = [l for l in lignes if _b._s(l.get("statut_ui") or l.get("etat"))
                  not in ("faite", "abandonnee")]
    if p.get("statut"):
        lignes = [l for l in lignes if _b._s(l.get("statut_ui") or l.get("etat")) == p["statut"]]
    return lignes


def _correspond(ligne: dict, mots: list[str]) -> bool:
    foin = " ".join([_b._s(ligne.get("titre")), _b._s(ligne.get("corps")),
                     _b._s((ligne.get("macro") or {}).get("titre"))]).casefold()
    return all(m in foin for m in mots)


def _aucun_chantier() -> dict:
    return {"ok": True, "taches": [], "projets": [],
            "message": "aucun chantier rattaché : ce ticket n'a pas de projet (BOUZECODE_TICKET_SLUG vide)."}


def taches_projet(action: str = "lister", task_id: str = "", texte: str = "",
                  include_closed: bool = False, statut: str = "", commentaire: str = "",
                  de: str = "", chantier: str = "", creer_chantier: bool = False,
                  chantier_titre: str = "", chantier_brief: str = "",
                  chantier_projets: list | None = None, **_ignores) -> dict:
    action = _b._txt(action) or "lister"
    if action in _RESERVEES:
        return {"ok": False, "erreur": "action_reservee_au_bureau",
                "message": (f"'{action}' est reserve au Bureau (outil Taches). TachesProjet ne "
                            "fait que lister, rechercher, classer (faite/doublon/caduque), "
                            "explorer et ranger TA tache sous un chantier.")}
    if action not in ACTIONS:
        return {"ok": False, "erreur": "action_inconnue", "message": f"Actions : {ACTIONS}."}
    if action == "explorer":
        return _explorer()
    if action == "ranger_ma_tache":
        return _ranger_ma_tache(task_id, chantier, creer_chantier, chantier_titre,
                                chantier_brief, chantier_projets)
    projets = projets_de_l_agent()
    if not projets:
        return _aucun_chantier()
    lignes = _lignes_du_perimetre(projets)
    p = {"include_closed": include_closed, "statut": _b._txt(statut)}
    if action == "lister":
        return {"ok": True, "projets": projets, "taches": [_vue(l) for l in _filtrer(lignes, p)]}
    if action == "rechercher":
        mots = _b._txt(texte).casefold().split()
        if not mots:
            return {"ok": False, "erreur": "texte_requis",
                    "message": "Donne les mots cherches dans `texte`."}
        trouvees = [l for l in _filtrer(lignes, p) if _correspond(l, mots)]
        return {"ok": True, "projets": projets, "taches": [_vue(l) for l in trouvees]}
    return _classer(action, lignes, task_id, commentaire, de)


def _classer(action: str, lignes: list[dict], task_id: str, commentaire: str, de: str) -> dict:
    micro = _b._trouver(task_id)
    if micro is None:
        return {"ok": False, "erreur": "tache_introuvable",
                "message": f"Aucune tache « {task_id} »."}
    ident = _b._s(micro.get("id"))
    if ident not in {_b._s(l.get("id")) for l in lignes}:
        return {"ok": False, "erreur": "hors_perimetre",
                "message": "Cette tache n'appartient pas aux chantiers de ton projet."}
    if not _b._txt(commentaire):
        return {"ok": False, "erreur": "commentaire_requis",
                "message": ("Dis d'ou vient la resolution dans `commentaire` (ticket, agent, "
                            "commit) : l'utilisateur le lira sur la carte.")}
    lien = ""
    if _b._txt(de):
        cible = _b._trouver(de)
        lien = _b._s(cible.get("id")) if cible else _b._txt(de)
    reponse = _b._appel("POST", f"/api/micros/{ident}/classer",
                        {"motif": _MOTIFS[action],
                         "commentaire": f"{signature()} {_b._txt(commentaire)}",
                         "de": lien, "auteur": "agent"})
    return _b._echec(reponse) or {"ok": True, "classement": reponse.get("classement"),
                                  "tache": _b._resume(reponse.get("micro") or {"id": ident})}


#  --- Explorer l'organisation, ranger SA tache ---------------------------------------------

def _vue_chantier(macro: dict) -> dict:
    corps = _b._s(macro.get("corps"))
    return {"id": _b._s(macro.get("id")), "titre": _b._s(macro.get("titre")),
            "brief": corps[:_BRIEF_MAX], "projets": list(macro.get("projets") or []),
            "etat": _b._s(macro.get("etat"))}


def _explorer() -> dict:
    """Les projets (depots) puis les chantiers actifs, ceux du depot de l'agent en premier."""
    from bouzecode.web_v2.services.work import micros, projects
    mes_projets = projets_de_l_agent()
    depots = [{"slug": _b._s(p.get("slug")), "nom": _b._s(p.get("name") or p.get("slug")),
               "le_mien": _b._s(p.get("slug")) in mes_projets}
              for p in projects.list_projects() if isinstance(p, dict)]
    depots.sort(key=lambda d: not d["le_mien"])
    chantiers = [_vue_chantier(m) for m in micros.list_macros(etat="active")]
    for c in chantiers:
        c["rattache_a_mon_depot"] = bool(set(c["projets"]) & set(mes_projets))
    chantiers.sort(key=lambda c: not c["rattache_a_mon_depot"])  # tri stable : ordre du Bureau
    return {"ok": True, "mes_projets": mes_projets, "projets": depots, "chantiers": chantiers}


def ma_tache() -> dict | None:
    """La tache du ticket porteur (BOUZECODE_TICKET_ID), ou None : la seule qu'un agent peut ranger."""
    from bouzecode.web_v2.services.work import micros
    ticket = os.environ.get("BOUZECODE_TICKET_ID") or ""
    return micros.micro_par_ticket().get(ticket) if ticket else None


def _normaliser(titre: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", titre or "").encode("ascii", "ignore").decode("ascii")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", ascii_.casefold()).split())


def chantiers_proches(titre: str, chantiers: list[dict]) -> list[dict]:
    """Chantiers dont le titre ressemble (inclusion ou ratio >= 0.75) : pas de doublon cree."""
    cible = _normaliser(titre)
    proches = []
    for c in chantiers:
        autre = _normaliser(c.get("titre") or "")
        if not autre or not cible:
            continue
        if (cible in autre or autre in cible
                or difflib.SequenceMatcher(None, cible, autre).ratio() >= 0.75):
            proches.append(c)
    return proches


def _trouver_chantier(ref: str, chantiers: list[dict]) -> dict | None:
    ref = _b._txt(ref)
    return next((c for c in chantiers if _b._s(c.get("id")) == ref), None) or next(
        (c for c in chantiers if _b._s(c.get("titre")).casefold() == ref.casefold()), None)


def _ranger_ma_tache(task_id: str, chantier: str, creer_chantier: bool, chantier_titre: str,
                     chantier_brief: str, chantier_projets) -> dict:
    from bouzecode.web_v2.services.work import micros
    mienne = ma_tache()
    if not mienne:
        return {"ok": False, "erreur": "aucune_tache_en_cours",
                "message": "Ton ticket ne porte aucune tache de la TODO : rien a ranger."}
    mon_id = _b._s(mienne.get("micro_id"))
    if _b._txt(task_id):
        visee = _b._trouver(task_id)
        if _b._s((visee or {}).get("id") or task_id) != mon_id:
            return {"ok": False, "erreur": "pas_ta_tache",
                    "message": ("Tu ne peux ranger QUE la tache de ton ticket "
                                f"({mon_id}) ; les autres se rangent au Bureau.")}
    actifs = micros.list_macros(etat="active")
    cree = None
    if creer_chantier:
        titre = _b._txt(chantier_titre)
        if not titre:
            return {"ok": False, "erreur": "titre_vide",
                    "message": "Un chantier a besoin d'un titre : le RESULTAT vise."}
        proches = chantiers_proches(titre, actifs)
        if proches:
            return {"ok": False, "erreur": "chantier_proche_existe",
                    "chantiers": [_vue_chantier(c) for c in proches],
                    "message": ("Un chantier au titre proche existe deja : range ta tache "
                                "dedans (`chantier` = son id) au lieu d'en creer un.")}
        projets = list(chantier_projets or []) or projets_de_l_agent()
        corps = f"{signature()} {_b._txt(chantier_brief)}".strip()
        cible = cree = micros.create_macro(titre, corps=corps, projets=projets)
    else:
        if not _b._txt(chantier):
            return {"ok": False, "erreur": "chantier_requis",
                    "message": ("Donne `chantier` (id ou titre exact, voir 'explorer') ou "
                                "creer_chantier=true avec chantier_titre.")}
        cible = _trouver_chantier(chantier, actifs)
        if cible is None:
            return {"ok": False, "erreur": "chantier_introuvable",
                    "message": f"Aucun chantier actif « {chantier} » (voir 'explorer')."}
    micros.update_micro(mon_id, macro_id=_b._s(cible.get("id")))
    rendu = {"ok": True, "tache": {"id": mon_id, "titre": _b._s(mienne.get("titre"))},
             "chantier": _vue_chantier(cible)}
    if cree:
        rendu["chantier_cree"] = True
    return rendu


SCHEMA = {
    "name": "TachesProjet",
    "description": (
        "La TODO des chantiers de TON projet (celui du ticket), pour tout agent. "
        "'lister' (defaut ; statut, include_closed) et 'rechercher' (texte = mots cherches dans "
        "titre, brief, chantier) rendent id, titre, brief, statut, chantier. "
        "Tu viens de resoudre un point de cette TODO ? Classe-le : 'marquer_faite' (task_id + "
        "commentaire ; de = la tache qui l'a faite), 'marquer_doublon' (task_id + de + "
        "commentaire), 'marquer_caduque' (task_id + commentaire). Le commentaire est OBLIGATOIRE "
        "et cite d'ou vient la resolution (ticket, commit) ; il est signe de ton agent et de ton "
        "ticket sur la carte. Refuse si un agent travaille sur la tache. "
        "'explorer' rend les projets (depots) et les chantiers actifs, ceux de ton depot en "
        "premier. 'ranger_ma_tache' range la tache de TON ticket (jamais celle d'un autre) "
        "sous un chantier : `chantier` = id ou titre exact d'un chantier existant, ou "
        "creer_chantier=true + chantier_titre (le resultat vise) + chantier_brief + "
        "chantier_projets (defaut : ton depot) ; refuse si un chantier au titre proche existe "
        "(explore d'abord). Le chantier cree est signe de ton agent et ticket. Creer/lancer/"
        "relancer/clore/preciser une tache, deplacer celle d'un autre : reserves au Bureau."),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ACTIONS},
            "task_id": {"type": "string", "description": "Id de la tache (ou titre exact)."},
            "texte": {"type": "string", "description": "Pour 'rechercher' : les mots cherches."},
            "statut": {"type": "string", "description": (
                "Filtre : brouillon, a_decider, en_cours, a_repondre, a_relire, en_echec, "
                "faite, abandonnee.")},
            "include_closed": {"type": "boolean", "description": "Inclure faites/abandonnees."},
            "commentaire": {"type": "string", "description": (
                "Obligatoire pour marquer_* : d'ou vient la resolution (ticket, commit).")},
            "de": {"type": "string", "description": (
                "Pour marquer_doublon (requis) / marquer_faite : la tache de reference.")},
            "chantier": {"type": "string", "description": (
                "Pour ranger_ma_tache : id ou titre exact du chantier existant.")},
            "creer_chantier": {"type": "boolean", "description": (
                "Pour ranger_ma_tache : creer le chantier (aucun pertinent dans 'explorer').")},
            "chantier_titre": {"type": "string", "description": "Titre du chantier a creer."},
            "chantier_brief": {"type": "string", "description": "Brief du chantier a creer."},
            "chantier_projets": {"type": "array", "items": {"type": "string"}, "description": (
                "Depots (slugs) du chantier a creer ; defaut : ton depot.")},
        },
        "required": [],
    },
}


def est_sous_agent(config: dict | None = None) -> bool:
    """Un SOUS-AGENT (lance par un autre agent) n'a pas la TODO : il rend compte a son parent,
    et c'est l'agent PRINCIPAL du ticket qui consulte, classe et range.

    Se reconnait a son agent parent (`BOUZECODE_PARENT`, hors dispatcher du serveur) ou a sa
    profondeur de delegation (`BOUZECODE_AGENT_DEPTH` + `config["_depth"]`). Une tache du Bureau
    (`BOUZECODE_BRIEF_HUMAIN=1`) est l'agent principal de son ticket."""
    from ..multi_agent.profondeur import profondeur_courante
    if os.environ.get("BOUZECODE_BRIEF_HUMAIN") != "1":
        parent = os.environ.get("BOUZECODE_PARENT", "").strip()
        if parent and not parent.startswith("dispatcher:"):
            return True
    try:
        return profondeur_courante(config or {}) > 0
    except (TypeError, ValueError):
        return False


def _refus_sous_agent() -> dict:
    return {"ok": False, "erreur": "reserve_a_l_agent_principal",
            "message": ("Un sous-agent ne touche pas a la TODO : mets dans ton rapport ce qui "
                        "est resolu / a ranger, l'agent principal du ticket decidera.")}


def _appel_outil(p: dict, c: dict) -> dict:
    if est_sous_agent(c):
        return _refus_sous_agent()
    return taches_projet(**p)


def register() -> None:
    from ..core.tool_registry import ToolDef, register_tool
    register_tool(ToolDef(name="TachesProjet", schema=SCHEMA,
                          func=_appel_outil,
                          read_only=False, concurrent_safe=False))
