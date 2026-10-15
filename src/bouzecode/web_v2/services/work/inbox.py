# [desc] « À traiter » (SPEC §4.2) : UNE liste de cartes de tout ce qui attend l'utilisateur, tous agents confondus. [/desc]
"""La boîte de réception du Bureau.

Une carte par point qui attend un geste humain, avec ce qu'il faut pour AGIR sur place
(question et options, récap, raison d'échec, actions possibles). Sources, sans rien recalculer :

* les tâches du Bureau (`bureau_lignes.collect_lignes`, déjà enrichies par `taches_vue`) —
  a_repondre, a_relire, en_echec, a_decider ;
* les agents qui attendent une réponse HORS tâche (`awaiting.agents_awaiting_answer`) ;
* les conversations libres arrêtées sans finir (arbre de flotte, < 7 jours) ;
* les lancements échoués hors tâche (store des tickets, < 7 jours).

Une tâche ne produit qu'UNE carte ; un agent déjà couvert par une tâche n'en produit pas d'autre.
"""
from __future__ import annotations

from bouzecode.web_v2.services.horodatage import age_s

from . import lexique
from .etat_ticket import vue_rattachee
from .fsm import etats

FENETRE_JOURS = 7
URGENCE = {"question": 0, "plan": 0, "en_echec": 1, "agent_arrete": 1, "lancement_echoue": 1,
           "a_relire": 2, "decision": 3}
#  Un signalement porte sa PROPRE urgence (selon sa gravité, `signalements.URGENCE`).
#  Motif d'un point SANS tâche (celui d'une tâche vient de sa ligne, cf. `lexique.motif_attente`).
MOTIF_HORS_TACHE = {"question": "question", "plan": "plan", "agent_arrete": "plante",
                    "lancement_echoue": "lancement"}


def _recent(iso: str, jours: int = FENETRE_JOURS) -> bool:
    age = age_s(iso)
    return age is not None and age <= jours * 86400


PLAN_MAX = 20000


def _dernier_plan(messages: list[dict]) -> str:
    for message in reversed(messages or []):
        for appel in reversed(message.get("tool_calls") or []):
            if appel.get("name") == "WritePlan":
                return str((appel.get("input") or {}).get("content") or "")[:PLAN_MAX]
    return ""


def texte_du_plan(agent_id: str) -> str:
    """Le dernier plan écrit par l'agent (`WritePlan`), lu dans sa session : c'est ce qu'on
    lui demande de valider, et la carte doit le montrer pour qu'on puisse répondre sur place."""
    from pathlib import Path

    from bouzecode.web_v2.runtime.runner import agent_fiche

    from ..sessions import store
    agent = agent_fiche.load_agent(agent_id) if agent_id else None
    if agent is None or not agent.session_path:
        return ""
    return _dernier_plan((store.load_session_json(Path(agent.session_path)) or {}).get("messages"))


def _question(genre: str, agent_id: str, source: dict, cle_texte: str) -> dict:
    question = {"texte": source.get(cle_texte, ""), "options": source.get("options") or [],
                "allow_freetext": source.get("allow_freetext", True)}
    if genre == "plan":
        question["plan"] = texte_du_plan(agent_id)
    return question


def _tache(ligne: dict, titres_chantiers: dict[str, str]) -> dict:
    return {"micro_id": ligne.get("id", ""), "titre": ligne.get("titre", ""),
            "chantier": titres_chantiers.get(str(ligne.get("macro_id") or ""), ""),
            "macro_id": ligne.get("macro_id", "")}


# -------------------------------------------------------------- cartes des tâches


def _carte_reponse(ligne: dict, base: dict, dernier: dict) -> dict:
    attente = next(p for p in ligne["passages"] if p["etat"] in lexique.ETATS_ATTENTE)
    genre = "plan" if attente["etat"] == "awaiting_plan_validation" else "question"
    return {**base, "type": genre, "id": f"{genre}:{attente['agent_id']}",
            "agent_id": attente["agent_id"], "key": attente["key"],
            "depuis": attente.get("started_at", ""),
            "question": _question(genre, attente["agent_id"], attente.get("question") or {},
                                  "texte"),
            "agent_vivant": (vivant := _agent_vivant(attente["agent_id"])),
            "actions": _actions_question(vivant)}


def _agent_vivant(agent_id: str) -> bool:
    """Le process de l'agent tourne-t-il encore ? Fiche illisible : on le dit vivant (aucun
    geste d'archivage proposé à tort sur une question qui attend peut-être encore)."""
    try:
        from bouzecode.web_v2.runtime.runner import agent_fiche, agent_vivacite
        agent = agent_fiche.load_agent(agent_id)
        return True if agent is None else bool(agent_vivacite.is_running(agent))
    except Exception:  # noqa: BLE001 — un parc illisible ne fait pas tomber l'accueil
        return True


def _carte_a_relire(ligne: dict, base: dict, dernier: dict) -> dict:
    integrable = bool(dernier.get("integrable"))
    return {**base, "type": "a_relire", "id": f"a_relire:{ligne['id']}",
            "recap": dernier.get("recap") or {},
            "fichiers_modifies": dernier.get("fichiers_modifies"),
            "branche": dernier.get("branche", ""), "integrable": integrable,
            "slug": dernier.get("slug", ""), "ticket_id": dernier.get("ticket_id", ""),
            "joignable": dernier.get("joignable", False),
            "actions": ["relire", "marquer_faite", "relancer"] + (["integrer"] if integrable else [])}


def _carte_echec(ligne: dict, base: dict, dernier: dict) -> dict:
    joignable = dernier.get("joignable", False)
    return {**base, "type": "en_echec", "id": f"en_echec:{ligne['id']}",
            "raison": ligne.get("raison_echec", ""), "joignable": joignable,
            "actions": ["continuer", "relancer", "ouvrir"] if joignable else ["relancer"]}


def _carte_decision(ligne: dict, base: dict, dernier: dict) -> dict:
    return {**base, "type": "decision", "id": f"decision:{ligne['id']}",
            "brief": ligne.get("corps", ""), "depuis": ligne.get("updated_at", ""),
            "actions": ["trancher"]}


_CARTE_PAR_STATUT = {"a_repondre": _carte_reponse, "a_relire": _carte_a_relire,
                     "en_echec": _carte_echec, "a_decider": _carte_decision}


def _carte_tache(ligne: dict, titres: dict[str, str]) -> dict | None:
    fabrique = _CARTE_PAR_STATUT.get(ligne.get("statut_ui"))
    if fabrique is None:
        return None
    passages = ligne.get("passages") or []
    dernier = passages[0] if passages else {}
    base = {"titre": ligne.get("titre", ""), "tache": _tache(ligne, titres),
            "motif": ligne.get("motif", ""),
            "projet_slug": dernier.get("slug") or ligne.get("projet_defaut", ""),
            "agent_id": dernier.get("agent_id", ""), "key": dernier.get("key", ""),
            "depuis": dernier.get("finished_at") or dernier.get("started_at")
            or ligne.get("updated_at", ""), **_etat_rattache(dernier)}
    return fabrique(ligne, base, dernier)


def _etat_rattache(source: dict) -> dict:
    """L'état du ticket porté par un passage ou un nœud (`ticket_state`, `libelle_ticket`…)."""
    return {k: v for k, v in source.items() if k.startswith("ticket_") or k == "libelle_ticket"}


# --------------------------------------------------------------------- la boîte


def construire() -> dict:
    """Toutes les cartes, triées par urgence puis ancienneté (mémorisé ≤ 3 s)."""
    from . import taches_vue
    return taches_vue.memorise_a_part("inbox", _construire)


def _lignes_du_bureau() -> tuple[list[dict], dict[str, str]]:
    from . import bureau_lignes
    vue = bureau_lignes.collect_lignes()
    titres = {c["macro_id"]: c["titre"] for c in vue.get("chantiers") or []}
    lignes = [l for c in vue.get("chantiers") or [] for l in c.get("lignes") or []]
    return lignes + list(vue.get("non_rattachees") or []), titres


def _tache_liee(lien: dict | None, titres: dict[str, str]) -> dict | None:
    if not lien:
        return None
    return {"micro_id": lien["micro_id"], "titre": lien["titre"],
            "chantier": titres.get(lien.get("macro_id") or "", ""),
            "macro_id": lien.get("macro_id", "")}


def _est_sous_agent(parent) -> bool:
    return bool(parent) and not str(parent).startswith("dispatcher:")


def _carte_question_libre(row: dict, lien: dict | None, titres: dict[str, str]) -> dict:
    genre = "plan" if row.get("state") == "awaiting_plan_validation" else "question"
    return {"type": genre, "id": f"{genre}:{row['agent_id']}", "titre": row.get("title", ""),
            "agent_id": row["agent_id"], "key": row["key"], "depuis": row.get("asked_at", ""),
            "projet_slug": row.get("ticket_slug") or row.get("project_slug") or "",
            "tache": _tache_liee(lien, titres),
            "question": _question(genre, row["agent_id"], row, "question"),
            "sous_agent": _est_sous_agent(row.get("parent")),
            "agent_vivant": bool(row.get("warm")),
            "actions": _actions_question(row.get("warm"))}


def _actions_question(vivant) -> list[str]:
    """Agent vivant : on répond. Agent ARRÊTÉ : l'humain choisit — répondre (relance), reprendre
    l'agent (« Continuer… »), ou classer la question sans réponse. Jamais d'archivage d'office."""
    if vivant:
        return ["repondre", "ouvrir"]
    return ["repondre", "continuer", "archiver", "ouvrir"]


def _questions_hors_tache(couverts: set[str], par_ticket: dict, titres: dict) -> list[dict]:
    """Questions d'agents hors tâche (conversations libres, sous-agents d'un manager…)."""
    from . import awaiting
    try:
        attentes = awaiting.agents_awaiting_answer()
    except Exception:  # noqa: BLE001 — un parc illisible ne fait pas tomber l'accueil
        return []
    from . import _persistence
    par_id = {str(t.get("id")): t for _slug, t in _persistence.all_tickets()} if attentes else {}
    cartes = []
    for row in attentes:
        if row["agent_id"] not in couverts:
            cartes.append({**_carte_question_libre(row, par_ticket.get(row.get("ticket_id") or ""),
                                                   titres),
                           **vue_rattachee(par_id.get(str(row.get("ticket_id") or "")))})
            couverts.add(row["agent_id"])
    return cartes


def _construire() -> dict:
    from . import micros as micros_service
    lignes, titres = _lignes_du_bureau()
    couverts = {p["agent_id"] for l in lignes for p in l.get("passages") or []
                if p.get("agent_id")}
    cartes = [c for c in (_carte_tache(l, titres) for l in lignes) if c is not None]
    par_ticket = micros_service.micro_par_ticket()
    cartes += _questions_hors_tache(couverts, par_ticket, titres)
    cartes += _conversations_arretees(couverts)
    cartes += _lancements_echoues(par_ticket)
    from . import inbox_signalements
    cartes += inbox_signalements.cartes(par_ticket)
    for carte in cartes:
        carte.setdefault("urgence", URGENCE.get(carte["type"], 9))
        carte.setdefault("motif", MOTIF_HORS_TACHE.get(carte["type"], ""))
        carte["categorie"] = lexique.categorie(carte["motif"])
        carte.setdefault("tache", None)
    cartes.sort(key=lambda c: (c["urgence"], str(c.get("depuis") or "")))
    return {"items": cartes, "compte": len(cartes)}


def _arret_a_signaler(n: dict, deja: set[str], par_id: dict[str, dict]) -> bool:
    """Un agent (hors test) mort sans clôture depuis < 7 jours. Un sous-agent arrêté est
    l'affaire de son parent TANT QUE ce parent peut s'en occuper ; orphelin (parent introuvable,
    lui-même arrêté, ou assistant de terminal), il revient à l'humain."""
    from .inbox_signalements import parent_peut_s_en_occuper
    if not n.get("interrupted") or n.get("agent_id") in deja:
        return False
    if n.get("category") == "test" or (n.get("kind") or "work") != "work":
        return False
    if _est_sous_agent(n.get("parent")) and parent_peut_s_en_occuper(n.get("parent"), par_id):
        return False
    return _recent(n.get("saved_at") or n.get("started_at") or "")


def _conversations_arretees(deja: set[str]) -> list[dict]:
    from . import fleet
    try:
        noeuds = fleet.agent_tree(avec_git=False).get("nodes") or []
    except Exception:  # noqa: BLE001
        return []
    par_id = {str(n.get("agent_id")): n for n in noeuds}
    return [{"type": "agent_arrete", "id": f"agent_arrete:{n['agent_id']}",
             "titre": n.get("title", ""), "agent_id": n["agent_id"], "key": n["key"],
             "depuis": n.get("saved_at") or n.get("started_at") or "",
             "projet_slug": n.get("project_slug", ""),
             "raison": ("Sous-agent arrêté sans réponse finale, et son parent ne peut plus "
                        "s'en occuper" if _est_sous_agent(n.get("parent")) else
                        "L'agent s'est arrêté sans réponse finale"),
             "sous_agent": _est_sous_agent(n.get("parent")), "parent": n.get("parent") or "",
             "joignable": True, "actions": ["continuer", "ouvrir"], **_etat_rattache(n)}
            for n in noeuds if _arret_a_signaler(n, deja, par_id)]


def _echec_quand(ticket: dict) -> str:
    return str((ticket.get("state_reason") or {}).get("at") or ticket.get("created_at") or "")


def _echec_a_signaler(ticket: dict, par_ticket: dict) -> bool:
    ident = str(ticket.get("id") or "")
    if ticket.get("state") != etats.LAUNCH_FAILED or not ident or ident in par_ticket:
        return False
    if ticket.get("archived"):
        return False
    return _recent(_echec_quand(ticket))


def _lancements_echoues(par_ticket: dict[str, dict]) -> list[dict]:
    """Tickets hors tâche dont le lancement a échoué récemment (les tâches ont leur carte)."""
    from . import _persistence
    return [{"type": "lancement_echoue", "id": f"lancement_echoue:{ticket['id']}",
             "titre": ticket.get("title", ""), "agent_id": "", "key": f"failed/{ticket['id']}",
             "ticket_id": str(ticket["id"]), "projet_slug": slug, "depuis": _echec_quand(ticket),
             "raison": f"Lancement échoué : {(ticket.get('state_reason') or {}).get('message') or '?'}",
             "actions": ["relancer"], **vue_rattachee(ticket)}
            for slug, ticket in _persistence.all_tickets() if _echec_a_signaler(ticket, par_ticket)]


#  Alias : la liste vit avec le registre qui la compte (`fleet_vue.AU_TRAVAIL`).
ETATS_AU_TRAVAIL = frozenset({"running", "thinking", "preparing"})


def compteurs() -> dict:
    """Pastilles de la navigation : points qui m'attendent, agents au travail.

    SOURCE UNIQUE, jamais un second calcul : « à moi » est le compte de LA boîte (même
    emplacement mémorisé que `GET /api/inbox`) et « en cours » ce que l'arbre servi à la page
    Agents montre au travail (`fleet.agents_au_travail`). L'ancienne mémoire propre aux
    pastilles, posée par-dessus, divergeait de la boîte d'une unité et de la page Agents
    pendant des dizaines de secondes (vérificateur d'invariants des E2E).

    Pollé toutes les 15 s par TOUTES les pages : la boîte est servie aussitôt et recalculée en
    fond une fois sa mémoire passée ; sa clé (`taches_vue.cle_courante`) change à chaque
    écriture de tâche ET à chaque changement d'état d'agent, ce qui force le recalcul."""
    from . import fleet, taches_vue
    boite = taches_vue.memorise_a_part("inbox", _construire, en_fond=True)
    return {"a_moi": boite["compte"], "inbox": boite["compte"], "en_cours": fleet.agents_au_travail()}
