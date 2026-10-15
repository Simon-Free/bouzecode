"""Vue TO-DO : les macro-tâches et leurs puces, lues des clôtures DÉCLARÉES.

Budget de lecture tenu volontairement pauvre : aucun appel git, aucun appel LLM,
aucun parcours de l'arbre d'agents. On se sert des tickets déjà en cache et du
json de session déjà écrit sur disque, comme le fait la sonnette du Bureau.

Le rattachement à une macro-tâche vient de l'AGENT (`taches_restantes[].macro`,
déclaré à la clôture). Quand il manque — clôtures antérieures au champ — on
regroupe par mission d'origine et on le DIT (`deduit: True`).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from bouzecode.web_v2.services.horodatage import en_iso, lire_instant, maintenant

from .todo_source import _agent_id, _closed, _created

#  Fenêtres proposées par la page. « 2j » et « 7j » sont les deux demandées.
FENETRES: dict[str, int | None] = {"2j": 2, "7j": 7, "30j": 30, "tout": None}

#  Ce qu'on affiche quand l'agent n'a rien déclaré : on ne prétend pas qu'il ne
#  reste rien, et on ne devine rien de son texte non plus.
TEXTE_NON_DECLARE = (
    "Clôture sans déclaration de tâches restantes (antérieure au champ "
    "obligatoire) — reste à statuer."
)


def _txt(valeur: object) -> str:
    """Le texte ENTIER, jamais tronqué : on ne fait que retirer les blancs."""
    return str(valeur if valeur is not None else "").strip()


def borne_de(fenetre: str, now: datetime) -> datetime | None:
    """Date plancher de la fenêtre demandée (UTC consciente) ; `None` = pas de plancher."""
    jours = FENETRES.get(str(fenetre or "7j"), 7)
    if jours is None:
        return None
    return (lire_instant(now) or maintenant()) - timedelta(days=jours)


def _faites(source, agent: str) -> int:
    """Combien de tâches l'agent a DÉCLARÉ avoir achevées (`taches_terminees`)."""
    lire = getattr(source, "taches", None)
    brut = lire(agent) if (agent and callable(lire)) else None
    if not isinstance(brut, dict):
        return 0
    faites = brut.get("taches_terminees")
    if not isinstance(faites, list):
        return 0
    return len([item for item in faites if _txt(item if isinstance(item, str) else
                                                (item or {}).get("texte"))])


#  Une tâche sans macro déclarée ne fabrique pas une section par ticket : tout ce qui
#  n'est pas rattaché tombe ICI, et la section dit elle-même que le regroupement est déduit.
MACRO_NON_RATTACHEE = "Non rattachées"


def _declaration(source, agent: str) -> tuple[list, bool]:
    """Rend `(items, declare)`. `declare` vaut True dès que l'agent a répondu,
    même par une liste vide : c'est toute la différence entre « rien ne reste »
    et « je n'ai pas répondu »."""
    lire = getattr(source, "taches", None)
    brut = lire(agent) if (agent and callable(lire)) else None
    if not isinstance(brut, dict):
        return [], False
    restantes = brut.get("taches_restantes")
    declare = bool(brut.get("taches_declarees")) or isinstance(restantes, list)
    return (restantes if isinstance(restantes, list) else []), declare


def _points_ouverts(source, agent: str) -> list:
    """Migration en LECTURE de `recap.points_ouverts` (lot L2) vers les tâches
    restantes : un point ouvert EST une tâche restante qui attend un arbitrage."""
    lire = getattr(source, "recap", None)
    recap = lire(agent) if (agent and callable(lire)) else None
    if not isinstance(recap, dict):
        return []
    points = recap.get("points_ouverts")
    if not isinstance(points, list):
        return []
    migres = []
    for point in points:
        texte = _txt(point.get("texte")) if isinstance(point, dict) else _txt(point)
        if not texte:
            continue
        options = point.get("options") if isinstance(point, dict) else None
        migres.append({
            "titre": texte, "corps": "", "macro_id": "", "macro_titre": "",
            "decision": True,
            "options": options if isinstance(options, list) else [],
        })
    return migres


def _cree_iso(ticket: dict) -> str:
    """La date de création du ticket, ISO UTC explicite (`horodatage.en_iso`).

    Chaque puce la porte pour que le front puisse filtrer la fenêtre EN MÉMOIRE :
    sans elle, changer de fenêtre obligeait à repartir au serveur, alors que la
    fenêtre ne change rien au travail que le serveur fait."""
    return en_iso(_created(ticket))


def _puce(item: object, ticket: dict, agent: str, rang: int, declare: bool) -> dict | None:
    """Normalise un item déclaré en puce affichable. Texte vide = pas de puce."""
    corps, macro_id = "", ""
    if isinstance(item, dict):
        #  Format courant : `titre` + `corps` + `macro_id`/`macro_titre`. Les clôtures
        #  DÉJÀ en base portent `texte`/`macro` : on les lit encore, sinon des puces
        #  existantes disparaîtraient de l'écran du jour au lendemain.
        texte = _txt(item.get("titre")) or _txt(item.get("texte"))
        corps = _txt(item.get("corps"))
        macro_id = _txt(item.get("macro_id"))
        macro = _txt(item.get("macro_titre")) or _txt(item.get("macro"))
        decision = bool(item.get("decision"))
        options = item.get("options") if isinstance(item.get("options"), list) else []
    else:
        #  Tolérance : une clôture peut avoir écrit des chaînes nues.
        texte, macro, decision, options = _txt(item), "", False, []
    if not texte:
        return None
    return {
        "id": f"{agent or ticket.get('id') or 'x'}:{rang}",
        "texte": texte,
        "corps": corps,
        "macro": macro,
        "macro_id": macro_id,
        "decision": decision,
        "options": options,
        "declare": declare,
        "agent": agent,
        "ticket": str(ticket.get("id") or ""),
        "slug": str(ticket.get("slug") or ""),
        "title": str(ticket.get("title") or ""),
        "date": str(ticket.get("created_at") or ""),
        "cree": _cree_iso(ticket),
    }


def _ranger(puce: dict, a_decider: list[dict], macros: dict[str, dict]) -> None:
    """Une décision va dans `a_decider` ; sinon dans sa macro. Une puce sans macro déclarée ne
    fabrique PAS une macro par ticket : elle tombe dans une section unique, qui se dit
    elle-même « déduite » dès qu'un seul item y est non rattaché."""
    if puce["decision"]:
        a_decider.append(puce)
        return
    nom = puce["macro"] or MACRO_NON_RATTACHEE
    groupe = macros.setdefault(nom, {"macro": nom, "deduit": not puce["macro"], "puces": []})
    groupe["deduit"] = groupe["deduit"] or not puce["macro"]
    groupe["puces"].append(puce)


def _eligible(source, ticket: dict, plancher) -> bool:
    if not _closed(ticket):
        return False
    cree = _created(ticket)
    return cree is not None and (plancher is None or cree >= plancher)


def _est_test(source, agent: str) -> bool:
    """Une conversation de TEST (PING/PONG, « Ticket normal »…) n'a aucune tâche à porter."""
    est_test = getattr(source, "is_test", None)
    return bool(agent and callable(est_test) and est_test(agent))


def _items_du_ticket(source, agent: str) -> tuple[list, bool]:
    items, declare = _declaration(source, agent)
    if not declare:
        items = _points_ouverts(source, agent) or [{"texte": TEXTE_NON_DECLARE}]
    return items, declare


def collect(source, now: datetime | None = None, fenetre: str = "7j") -> dict:
    """Rend `{a_decider, macros, stats}` pour les tickets terminés de la fenêtre."""
    plancher = borne_de(fenetre, now or maintenant())
    a_decider: list[dict] = []
    macros: dict[str, dict] = {}
    stats = {"tickets": 0, "non_declare": 0, "tests_ecartes": 0, "faites_declarees": 0,
             "puces": 0}
    for ticket in source.tickets():
        if not _eligible(source, ticket, plancher):
            continue
        agent = _agent_id(ticket)
        if _est_test(source, agent):
            stats["tests_ecartes"] += 1
            continue
        stats["tickets"] += 1
        stats["faites_declarees"] += _faites(source, agent)
        items, declare = _items_du_ticket(source, agent)
        stats["non_declare"] += 0 if declare else 1
        puces = [_puce(item, ticket, agent, rang, declare) for rang, item in enumerate(items)]
        for puce in (p for p in puces if p is not None):
            stats["puces"] += 1
            _ranger(puce, a_decider, macros)
    ordonnees = sorted(macros.values(), key=lambda g: (g["deduit"], g["macro"].lower()))
    return {
        "a_decider": a_decider,
        "macros": ordonnees,
        "stats": {"macros": len(ordonnees), "a_decider": len(a_decider),
                  "fenetre": str(fenetre or "7j"), **stats},
    }


