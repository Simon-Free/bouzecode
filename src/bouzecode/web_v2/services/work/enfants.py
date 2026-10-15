# [desc] Les enfants d'un agent (tickets dont il est le parent), lus FRAIS dans le store : état, branche, worktree. [/desc]
"""Ce qu'un agent parent doit savoir de ses enfants, et seulement ça.

POURQUOI UN SERVICE À PART, et pas l'arbre (`fleet.agent_tree`). Essai 3 du 2026-09-24 : la
racine 6bafe9cd a lancé son enfant « ui-tinder » (ticket fee42a91) puis, quelques tours plus
tard, `ListAgentTasks` lui a répondu « No sub-agent tasks » en 27 ms. L'outil lisait l'arbre
servi par `/api/agents/tree`, et l'arbre est un cache « servir d'abord, recalculer ensuite »
(`fleet_cache`) : un lecteur reçoit la version CONNUE, même périmée, le recalcul part en fond.
Un enfant né après le dernier calcul y est donc invisible — et un enfant en mode `defer`
n'est, pendant son provisionnement, qu'un ticket sans agent. La racine a cru l'enfant
disparu et a réécrit elle-même son travail.

Une vue d'observation peut avoir une seconde de retard ; une décision de l'agent (« mon
enfant existe-t-il ? », « puis-je supprimer ce worktree ? », « puis-je clore ? ») ne le peut
pas. Ici : les tickets dont `parent` est l'agent, relus dans SQLite à chaque appel (une
requête filtrée, aucun cache), et leur état est `ticket.state` — le même que lit le serveur.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ...runtime.runner import agent_registre
from . import _ligne_ticket, _persistence, etat_ticket, liveness, wake
from .fsm import etats
from .titres import titre_lisible

# États d'un enfant, du point de vue de son parent.
LANCEMENT = "lancement"          # ticket créé, agent pas encore démarré (provisionnement)
EN_COURS = "en_cours"            # il travaille (ou vient d'être ré-instruit)
ATTEND_REPONSE = "attend_reponse"  # il a posé une question et attend
LIVRE = "livre"                  # a rendu la main, rien d'intégré
INTEGRE = "integre"              # sa branche est intégrée
ARRETE = "arrete"                # mort sans clôture (planté, ou arrêté par Fleet kill)
ECHEC_LANCEMENT = "echec_lancement"

#  Un enfant ACTIF est un enfant dont le travail peut encore changer : on ne détruit pas son
#  worktree, on ne clôt pas par-dessus lui.
ACTIFS = frozenset({LANCEMENT, EN_COURS, ATTEND_REPONSE})

LIBELLES = {
    LANCEMENT: "en lancement", EN_COURS: "en cours", ATTEND_REPONSE: "attend une réponse",
    LIVRE: "fini, livré (non intégré)", INTEGRE: "fini, intégré", ARRETE: "arrêté/planté",
    ECHEC_LANCEMENT: "lancement échoué",
}


def tickets_enfants(agent_id: str) -> list[tuple[str, dict]]:
    """(slug, ticket) des tickets dont `agent_id` est le parent, archivés compris, récent en
    tête. UNE requête filtrée sur la colonne JSON : aucun décodage des autres tickets."""
    if not agent_id:
        return []
    with _persistence._connect() as conn:
        rows = conn.execute(
            "SELECT slug, data, version FROM tickets WHERE json_extract(data, '$.parent') IN"
            " (?, ?) ORDER BY seq DESC", (agent_id, f"agent/{agent_id}"),
        ).fetchall()
        return [(slug, _ligne_ticket.hydrater(conn, slug, json.loads(data), version))
                for slug, data, version in rows]


_ETAT_DE_L_ENFANT = {
    etats.CREATED: LANCEMENT, etats.PROVISIONING: LANCEMENT, etats.RUNNING: EN_COURS,
    etats.INTEGRATING: EN_COURS, etats.AWAITING_INPUT: ATTEND_REPONSE,
    etats.LAUNCH_FAILED: ECHEC_LANCEMENT, etats.STOPPED: ARRETE, etats.IDLE_NO_DELIVERY: ARRETE,
}


def etat(ticket: dict) -> str:
    """L'état d'un enfant, projection de `ticket.state` : « en cours » veut dire qu'il n'a pas
    rendu la main (un manager garé qui attend SES enfants l'est encore) ; livré, en conflit,
    clos ou abandonné, il a rendu la main."""
    if etat_ticket.integre(ticket):
        return INTEGRE
    return _ETAT_DE_L_ENFANT.get(str(ticket.get("state") or ""), LIVRE)


def _dernier_run(ticket: dict) -> dict:
    """Le run le plus récent : `runs` est tenu récent en tête."""
    return next((r for r in ticket.get("runs") or [] if isinstance(r, dict)), {})


#  La ligne du brief qui dit ce qu'on attend de l'enfant : « OBJECTIF : … », « ## Ta mission… ».
_LIGNE_D_OBJECTIF_RE = re.compile(r"^\W*(objectif|mission|but|livrable)\b", re.I)


def objectif(prompt: str) -> str:
    """L'objectif d'un enfant, lu dans son brief : la ligne qui l'annonce, sinon la première.
    Le titre (80 premiers caractères) disait « Tu travailles sur le projet… » pour deux enfants
    différents — la racine ne pouvait pas les distinguer (essai du 2026-09-25)."""
    lignes = [ligne.strip() for ligne in (prompt or "").splitlines() if ligne.strip()]
    choisie = next((ligne for ligne in lignes if _LIGNE_D_OBJECTIF_RE.match(ligne)),
                   lignes[0] if lignes else "")
    return choisie[:160]


def fiche(slug: str, ticket: dict) -> dict:
    """Ce que le parent lit d'un enfant : qui, dans quel état, où (branche, worktree), et
    quand il l'a lancé (tour, nom donné) pour quel objectif."""
    meta = ticket.get("worktree") if isinstance(ticket.get("worktree"), dict) else {}
    chemin = str(meta.get("worktree") or "")
    code = etat(ticket)
    return {
        "ticket_id": ticket.get("id", ""),
        "slug": slug,
        "agent_id": _dernier_run(ticket).get("agent_id", ""),
        "titre": ticket.get("title") or (ticket.get("prompt") or "")[:80],
        "etat": code,
        "libelle": LIBELLES.get(code, code),
        "state": ticket.get("state", ""), "state_reason": ticket.get("state_reason"),
        "actif": code in ACTIFS,
        "branche": str(meta.get("branch") or ""),
        "worktree": chemin,
        "worktree_existe": bool(chemin) and Path(chemin).is_dir(),
        "issue": _issue(ticket),
        "lancement": ticket.get("lancement") or {},
        "objectif": objectif(ticket.get("prompt") or ""),
    }


def _issue(ticket: dict) -> str:
    """L'issue de l'enfant, et ce qui lui est arrivé APRÈS sa clôture sans le relancer : les
    comptes rendus de ses propres enfants (petits-enfants du lecteur), notés par `wake`."""
    issue = wake.ticket_outcome(ticket)
    notes = ticket.get("comptes_rendus_sans_relance") or []
    if notes:
        issue += (" ; comptes rendus de SES enfants arrivés après sa clôture, notés sans le "
                  "relancer : " + " ; ".join(f"{n.get('ticket')} : {n.get('issue')}"
                                             for n in notes))
    return issue


_ETAT_D_UN_AGENT = {"running": EN_COURS, liveness.AWAITING: ATTEND_REPONSE,
                    liveness.IDLE: LIVRE, "delivered": LIVRE}


def _fiche_agent(agent) -> dict:
    """Un enfant SANS ticket (agent lancé avec `parent` mais hors dispatch) : même fiche."""
    vivacite = liveness.classify_agent(agent)
    code = _ETAT_D_UN_AGENT.get(vivacite, ARRETE)
    cwd = agent.cwd or ""
    return {"ticket_id": agent.agent_id, "slug": "", "agent_id": agent.agent_id,
            "titre": titre_lisible(agent.prompt or ""), "etat": code,
            "libelle": LIBELLES.get(code, code), "actif": code in ACTIFS, "branche": "",
            "worktree": cwd if str(Path(cwd)).startswith(str(_worktrees_dir())) else "",
            "worktree_existe": bool(cwd) and Path(cwd).is_dir(), "issue": vivacite,
            "lancement": {}, "objectif": objectif(agent.prompt or "")}


def _worktrees_dir() -> Path:
    from . import worktrees
    return worktrees.WORKTREES_DIR


def _agents_sans_ticket(agent_id: str, tickets_connus: set[str]) -> list:
    parents = {agent_id, f"agent/{agent_id}"}
    return [a for a in agent_registre.list_agents()
            if (a.parent or "") in parents and (a.ticket_id or "") not in tickets_connus]


def enfants_de(agent_id: str) -> list[dict]:
    """Les enfants de `agent_id`, frais : ses tickets, puis ses agents lancés sans ticket."""
    fiches = []
    for slug, ticket in tickets_enfants(agent_id):
        fiches.append(fiche(slug, ticket))
    connus = {f["ticket_id"] for f in fiches}
    fiches.extend(_fiche_agent(a) for a in _agents_sans_ticket(agent_id, connus))
    return fiches
