"""Le pont de clôture : ce qu'un agent DÉCLARE en partant devient une ligne de travail.

Avant ce module, `taches_restantes` n'était QU'AFFICHÉ (page TO-DO, `todo_board.collect`) et
il fallait un geste humain (`POST /api/todo/capture`) pour en faire une micro-tâche. Mesuré
le 2026-09-08 : le champ est rempli à presque chaque clôture (57 des 60 sessions récentes),
et pourtant zéro micro-tâche en base n'en provenait — l'humain recopiait le texte à la main.

Règle arbitrée par l'utilisateur : « si le ticket provient d'une tâche macro, on y rattache
par défaut les nouveaux tickets ». La macro n'est donc ni inventée par l'agent ni validée par
un humain : elle est HÉRITÉE du ticket parent, et ce défaut l'emporte sur le `macro_titre`
que l'agent aurait proposé.

Rien ne part tout seul : une micro naît en `brouillon`, et un dispatch exige `prete`.
"""
from __future__ import annotations

import unicodedata

from . import decisions_sans_objet, meme_point, micros, suites_cloture

#  Un point déjà ouvert ailleurs ne se rouvre pas ; une ligne `faite`/`abandonnee`, si.
ETATS_NON_TERMINAUX = ("brouillon", "prete", "lancee")


def _txt(valeur: object) -> str:
    return str(valeur or "").strip()


def _cle(titre: str) -> str:
    """Titre comparable : deux agents n'écrivent pas la même casse ni les mêmes espaces."""
    return " ".join(str(titre or "").split()).casefold()


#  Les EN-TÊTES que `micros.prompt_de` injecte dans le brief de l'agent. Un agent les recopie
#  parfois dans `taches_restantes` en croyant lister un point ouvert : mesuré le 2026-09-21,
#  3 lignes en base dont titre == corps == « Macro-tâche de rattachement : Finir l'assistant »
#  (dont une créée 15 min avant le signalement — le geste est courant, pas un vestige).
#  Ce sont les seules lignes de contexte que le brief contient, donc la liste est FERMÉE :
#  aucune heuristique sur « est-ce que ça ressemble à une tâche ».
ENTETES_CONTEXTE = (
    "macro-tache de rattachement",
    "chantier :",
    "informations communes au chantier",
    "precisions",
)
#  Le 4e en-tête, lui, ANNONCE une vraie action (`Tâche : {titre}`) : on ne jette pas la ligne,
#  on retire l'étiquette.
PREFIXE_TACHE = "tache :"


def _aplati(texte: str) -> str:
    """Forme comparable : accents retirés, minuscules, espaces compressés.

    Sans accents parce qu'un titre recopié en perd souvent (« Macro-tache »), et une égalité
    littérale raterait alors la moitié des cas."""
    decompose = unicodedata.normalize("NFD", str(texte or ""))
    sans_accents = "".join(c for c in decompose if unicodedata.category(c) != "Mn")
    return " ".join(sans_accents.split()).casefold()


def _sans_entete(titre: str) -> str:
    """Titre débarrassé de l'en-tête de brief recopié — `""` si c'est PUREMENT du contexte.

    `""` remonte à `_normalise`, qui rend alors `None` : la ligne n'est pas créée du tout.
    """
    plat = _aplati(titre)
    if any(plat.startswith(entete) for entete in ENTETES_CONTEXTE):
        return ""
    if plat.startswith(PREFIXE_TACHE) and ":" in titre:
        #  Découpe sur le VRAI texte (pas sur la forme aplatie) pour rendre les accents intacts.
        return titre.split(":", 1)[1].strip()
    return str(titre or "").strip()


def _normalise(item: object) -> dict | None:
    """Même tolérance que `todo_board._puce` : le format courant, l'ancien, et la chaîne nue.

    Titre vide ⇒ `None` : une déclaration biscornue ne doit pas fabriquer de ligne fantôme.
    """
    if isinstance(item, dict):
        libelle = _txt(item.get("titre")) or _txt(item.get("texte"))
        titre = _sans_entete(libelle)
        if not titre:
            return None
        return {
            "libelle": libelle,
            "titre": titre,
            "corps": _txt(item.get("corps")),
            "macro_id": _txt(item.get("macro_id")),
            "macro_titre": _txt(item.get("macro_titre")) or _txt(item.get("macro")),
            "decision": bool(item.get("decision")),
        }
    titre = _sans_entete(_txt(item))
    if not titre:
        return None
    return {"libelle": _txt(item), "titre": titre, "corps": "", "macro_id": "", "macro_titre": "",
            "decision": False}


def _chantier_du_point(item: dict, heritee: str) -> str:
    """Le chantier hérité du ticket prime ; créer un chantier depuis le titre déclaré n'est
    qu'un dernier recours (un agent ne peut pas éparpiller les suites d'un ticket rattaché)."""
    if heritee or item["macro_id"]:
        return heritee or item["macro_id"]
    if not item["macro_titre"]:
        return ""
    macro = micros.ensure_macro(item["macro_titre"])
    return str(macro.get("id") or "") if isinstance(macro, dict) else ""


def _points_deja_ouverts() -> dict[tuple[str, str], str]:
    """Anti-doublon : plusieurs agents signalent le même point ouvert d'un même chantier.
    Rend la tâche qui le porte déjà : c'est elle que le récap du passage désignera."""
    return {(_cle(micro.get("titre")), str(micro.get("macro_id") or "")): micro["id"]
            for micro in micros.list_micros()
            if str(micro.get("etat") or "") in ETATS_NON_TERMINAUX}


def _deja_ouvert(item: dict, macro_id: str, deja: dict[tuple[str, str], str]) -> str:
    """La tâche qui porte déjà ce point : même titre, ou — pour une décision — même OBJET
    (le worktree / la branche d'agent qu'elle tranche, quel que soit le libellé choisi)."""
    par_titre = deja.get((_cle(item["titre"]), macro_id), "")
    if par_titre or not item["decision"]:
        return par_titre
    objet = decisions_sans_objet.objet_de(item["titre"], item["corps"])
    return decisions_sans_objet.decision_ouverte_sur(objet, macro_id)


def _ouvertes_par_chantier() -> dict[str, list[dict]]:
    """Les tâches ouvertes, par chantier, avec TOUS les libellés qui les désignent : leur titre
    et chaque point de clôture déjà rattaché (`micro_suites`). Les alias comptent : « Étendre le
    scraping… » ne ressemble pas à « Brancher d'autres sites… », mais à « Étendre le scraping…
    (après le Kangourou) » que la clôture précédente y a rattaché (cas réel du 2026-09-25)."""
    alias: dict[str, list[str]] = {}
    for points in suites_cloture.index().values():
        for cle_point, suite in points.items():
            alias.setdefault(suite["micro_id"], []).append(cle_point)
    groupes: dict[str, list[dict]] = {}
    for micro in micros.list_micros():
        if str(micro.get("etat") or "") in ETATS_NON_TERMINAUX:
            groupes.setdefault(str(micro.get("macro_id") or ""), []).append({
                "id": micro["id"], "etat": micro["etat"], "decision": bool(micro.get("decision")),
                "libelles": [str(micro.get("titre") or ""), *alias.get(micro["id"], [])]})
    return groupes


def _quasi_doublon(item: dict, candidates: list[dict]) -> dict | None:
    """La tâche ouverte du chantier qui dit déjà la même chose (`meme_point`), même nature."""
    return next((c for c in candidates if c["decision"] == item["decision"]
                 and any(meme_point.meme_point(item["titre"], l) for l in c["libelles"])), None)


def _rattacher(item: dict, tache: dict, ticket_id: str) -> None:
    """Le point rejoint la tâche : lien du récap, et son libellé (avec le brief déclaré) en
    précision si la tâche n'est pas encore lancée — un agent lancé ne reçoit rien en douce."""
    suites_cloture.lier(ticket_id, item["libelle"], tache["id"], "existante")
    if tache["etat"] != "lancee" and all(_cle(l) != _cle(item["titre"]) for l in tache["libelles"]):
        texte = f"Même point signalé par une autre fin d'agent : « {item['titre']} »"
        micros.add_precision(tache["id"], f"{texte}\n\n{item['corps']}" if item["corps"] else texte,
                             auteur="bureau")
    tache["libelles"].append(item["titre"])


def ouvrir_micros_de_cloture(taches_restantes: object, ticket_id: str = "",
                             slug: str = "", session_id: str = "") -> list[dict]:
    """Ouvre une micro-tâche en brouillon par point resté ouvert. Rend celles créées.

    `session_id` est la session de l'agent qui clôture : il estampille les lignes créées
    (`micro_provenance`) pour qu'une vague entière reste auditable et purgeable.

    Volontairement PAS de `lier_ticket(nouvelle, ticket_parent)` : `micro_tickets` veut dire
    « tickets LANCÉS par cette micro » ; lier le parent inverserait la filiation. Le lien
    point déclaré → tâche (créée, ou déjà ouverte) va dans `micro_suites` : c'est lui que le
    récap du passage affiche."""
    if not isinstance(taches_restantes, list):
        return []
    items = [n for n in (_normalise(item) for item in taches_restantes) if n is not None]
    if not items:
        return []
    heritee = micros.macro_du_ticket(ticket_id)
    deja = _points_deja_ouverts()
    ouvertes = _ouvertes_par_chantier()
    creees: list[dict] = []
    for item in items:
        macro_id = _chantier_du_point(item, heritee)
        cle = (_cle(item["titre"]), macro_id)
        existante = _deja_ouvert(item, macro_id, deja)
        if existante:
            suites_cloture.lier(ticket_id, item["libelle"], existante, "existante")
            continue
        voisine = _quasi_doublon(item, ouvertes.get(macro_id, []))
        if voisine is not None:
            _rattacher(item, voisine, ticket_id)
            continue
        creee = micros.create_micro(
            titre=item["titre"], corps=item["corps"], macro_id=macro_id,
            projet_slug=slug, origine="cloture_agent", decision=item["decision"],
            session_id=session_id, source="final_answer")
        deja[cle] = creee["id"]
        ouvertes.setdefault(macro_id, []).append({"id": creee["id"], "etat": "brouillon",
                                                  "decision": item["decision"],
                                                  "libelles": [item["titre"]]})
        suites_cloture.lier(ticket_id, item["libelle"], creee["id"], "creee")
        creees.append(creee)
    return creees
