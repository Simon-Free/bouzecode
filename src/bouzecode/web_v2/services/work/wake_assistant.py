# [desc] Réveil de l'assistant du Bureau : à CHAQUE fin et à CHAQUE question d'une tâche qu'il a lancée. [/desc]
"""Extrait de `wake.py` (seuil ~200 lignes) : le manager orchestre UN lot et attend que tous
ses enfants aient fini ; l'assistant du Bureau, lui, pilote des tâches indépendantes et est
réveillé pour chacune dès qu'elle a fini ou qu'elle demande quelque chose."""
from __future__ import annotations

import logging
import zlib

from ...runtime.runner import agent_reprise
from . import signalements, wake, wake_digest

_log = logging.getLogger(__name__)

#  Profil de l'assistant du Bureau (même valeur que `bureau_contexte.PROFIL_ASSISTANT`).
PROFIL_ASSISTANT = "bureau-assistant"


def est_assistant(parent_agent) -> bool:
    return str(getattr(parent_agent, "profile", "") or "") == PROFIL_ASSISTANT


def _entree_question(ticket: dict) -> str:
    """Une question se signale par son TEXTE : une deuxième question posée dans le même tour
    (compteur de tours inchangé) est un nouvel événement."""
    question = wake_digest.pending_question(ticket)
    empreinte = zlib.crc32(str(question.get("question") or "").encode("utf-8"))
    return f"{ticket['id']}:question:{empreinte:08x}"


def evenements_assistant(kids: list[dict]) -> dict[str, dict]:
    """{entrée: ticket} des tâches qui ont quelque chose à dire à l'assistant : une ISSUE
    (finie, plantée, lancement échoué) ou une QUESTION. Contrairement au manager, qui orchestre
    UN lot et attend que TOUS ses enfants aient fini, l'assistant pilote des tâches
    indépendantes : chacune lui revient dès qu'elle a fini ou qu'elle demande quelque chose.
    L'entrée d'une issue reprend celle de `children_signature` (issue + tours clos) : une
    tâche relancée qui re-livre est un nouvel événement."""
    evenements: dict[str, dict] = {}
    for ticket in kids:
        if not wake.child_counts_for_wake(ticket):
            continue
        if wake.child_blocked_on_question(ticket):
            evenements[_entree_question(ticket)] = ticket
        elif wake.ticket_terminal(ticket):
            entree = f"{ticket['id']}:{wake.ticket_outcome(ticket)}#t{wake_digest.run_turns(ticket)}"
            evenements[entree] = ticket
    return evenements


def _taches_du_bureau() -> dict[str, dict]:
    """{ticket_id: {micro_id, titre}} — la tâche du Bureau d'où vient chaque ticket. Confort de
    lecture : une base illisible ne doit pas empêcher le réveil."""
    from . import micros
    try:
        return micros.micro_par_ticket()
    except Exception:  # noqa: BLE001 — le digest se dégrade, le réveil a lieu
        _log.exception("wake: tâches du Bureau illisibles pour le digest de l'assistant")
        return {}


def _nom_de_tache(ticket: dict, taches: dict[str, dict]) -> str:
    tache = taches.get(ticket["id"]) or {}
    titre = tache.get("titre") or ticket.get("title") or ""
    agent = (wake_digest.newest_run(ticket) or {}).get("agent_id") or "?"
    ou = f"tâche {tache['micro_id']}, " if tache.get("micro_id") else ""
    return f"« {titre} » ({ou}ticket {ticket['id']}, agent {agent})"


def build_assistant_digest(nouveaux: list[dict], kids: list[dict]) -> str:
    """Le message qui réveille l'assistant : QUELLE tâche (titre, id de tâche, ticket, agent),
    son ÉTAT, sa question en attente ou son rapport, et quoi faire. Les tâches encore en cours
    sont rappelées en une ligne : l'assistant sait ce qui reviendra plus tard."""
    taches = _taches_du_bureau()
    lignes = ["[Réveil du Bureau] Du nouveau sur des tâches que tu as lancées :", ""]
    questions = []
    for ticket in sorted(nouveaux, key=lambda t: t["id"]):
        bloc = wake_digest.child_block(ticket, delivered=wake.work_delivered(ticket))
        lignes.append(f"- Tâche {_nom_de_tache(ticket, taches)} : {wake.ticket_outcome(ticket)}")
        lignes += bloc[1:]
        if wake.child_blocked_on_question(ticket):
            questions.append(ticket)
    encore = [t for t in kids if t not in nouveaux and not wake.ticket_terminal(t)
              and not wake.child_blocked_on_question(t) and wake.child_counts_for_wake(t)]
    if encore:
        lignes += ["", "Toujours en cours (tu seras réveillé à leur tour) : "
                   + " ; ".join(_nom_de_tache(t, taches) for t in encore)]
    lignes.append("")
    if questions:
        lignes.append("QUESTION : si ce que l'humain t'a dit suffit à trancher, réponds avec "
                      'Taches(action="repondre", agent_id="<agent>", texte="<ta réponse>") ; '
                      "sinon pose-lui la question TELLE QUELLE, en citant la tâche, et relaie "
                      "sa réponse de la même façon. Ne laisse aucune tâche bloquée sans le dire.")
    if len(questions) < len(nouveaux):
        lignes.append("TÂCHE FINIE : dis à l'humain, en une ou deux lignes et en citant la tâche, "
                      "ce qui a été livré, ce qui reste, ou pourquoi elle a échoué — d'après le "
                      'rapport, sans rien inventer. Échec : propose Taches(action="relancer").')
    return "\n".join(lignes)


def traiter(parent_agent, kids: list[dict], state: dict, tour_clos: bool) -> bool:
    """Réveille l'assistant pour ses tâches qui ont DU NOUVEAU (fin ou question) depuis son
    dernier réveil. Pendant qu'il parle avec l'humain, rien : le tick qui suit la fin de son
    tour le réveillera.

    Les événements ne sont notés vus QU'AU RÉVEIL effectif : ni un tour en cours ni un arrêt
    demandé ne les consomment. Contrairement au manager (dont le parent lit les comptes rendus
    sur son ticket), l'assistant est le seul relais vers l'humain : une fin ou une question
    arrivée pendant l'arrêt lui est rendue au premier tour clos après la levée de l'arrêt
    (nouveau message de l'humain), au lieu d'être perdue."""
    if not tour_clos:
        return False
    evenements = evenements_assistant(kids)
    deja = set(state.get(parent_agent.agent_id) or [])
    nouveaux = [t for entree, t in evenements.items() if entree not in deja]
    if not nouveaux:
        return False
    motif = wake._reveil_sans_objet(parent_agent)
    if motif:
        #  Réévalué à chaque tick tant que l'arrêt tient : debug, pas info.
        _log.debug("wake: assistant %s non relancé (%s)", parent_agent.agent_id, motif)
        return False
    state[parent_agent.agent_id] = sorted(evenements)
    agent_reprise.continue_agent(parent_agent, build_assistant_digest(nouveaux, kids)
                          + signalements.digest_pour(parent_agent.agent_id))
    return True
