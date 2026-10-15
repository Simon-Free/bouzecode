"""Migration de boot : envelopper les tickets existants dans des tâches.

Idempotente par la table `task_tickets` : un ticket DÉJÀ lié à une tâche ne recrée rien. La
migration est en LECTURE SEULE côté tickets — elle ne pose aucun drapeau, ne réécrit aucun
ticket, et peut donc rejouer à chaque boot sans risque.

Règle de regroupement (§4.1 de l'annexe technique) : un ticket sans parent devient une tâche ;
les tickets enfants d'un même manager rejoignent la tâche de leur racine. Aucune tâche n'est
créée pour un ticket archivé.
"""
from __future__ import annotations

from . import decisions
from . import tasks as tasks_service
from ._persistence import all_tickets
from ._status import derive_status, remaining_of

# Une chaîne de managers plus profonde que ça n'existe pas ; la borne protège surtout d'un
# cycle qu'un store abîmé pourrait porter (A parent de B, B parent de A).
MAX_DEPTH = 20

Key = tuple[str, str]


def _live_tickets() -> dict[Key, dict]:
    """Les tickets vivants, indexés par (slug, ticket_id). Les archivés sont écartés."""
    live: dict[Key, dict] = {}
    for slug, ticket in all_tickets():
        if ticket.get("archived"):
            continue
        ticket_id = str(ticket.get("id") or "")
        if ticket_id:
            live[(slug, ticket_id)] = ticket
    return live


def _agent_index(tickets: dict[Key, dict]) -> dict[str, Key]:
    """`agent_id` -> ticket qui le porte.

    Le champ `parent` d'un ticket contient l'`agent_id` de son manager, pas un ticket_id : sans
    cet index, impossible de savoir à quelle tâche rattacher un enfant.
    """
    index: dict[str, Key] = {}
    for key, ticket in tickets.items():
        for run in ticket.get("runs") or []:
            agent_id = str(run.get("agent_id") or "")
            if agent_id:
                index[agent_id] = key
    return index


def _parents(tickets: dict[Key, dict], index: dict[str, Key]) -> dict[Key, Key]:
    """Lien enfant -> parent, restreint aux parents vivants et connus.

    Une conversation avec l'assistant du Bureau n'est pas une racine de travail
    (`TYPOLOGIES_SANS_TACHE`) : les tâches qu'il lance lui sont rattachées pour qu'il soit
    réveillé, mais chacune reste SA propre racine — sinon elles disparaîtraient avec la
    conversation, qui ne devient jamais une tâche."""
    parents: dict[Key, Key] = {}
    for key, ticket in tickets.items():
        parent = index.get(str(ticket.get("parent") or ""))
        if parent and str(tickets.get(parent, {}).get("typology") or "") in TYPOLOGIES_SANS_TACHE:
            continue
        if parent and parent != key and parent in tickets:
            parents[key] = parent
    return parents


def _root(key: Key, parents: dict[Key, Key]) -> Key:
    """Remonte la chaîne des managers jusqu'au ticket racine (anti-cycle, profondeur bornée)."""
    seen = {key}
    current = key
    for _ in range(MAX_DEPTH):
        parent = parents.get(current)
        if parent is None or parent in seen:
            return current
        seen.add(parent)
        current = parent
    return current


#  Une conversation avec l'assistant du Bureau n'est PAS un ticket qui porte du travail :
#  son `title` est le PROMPT que l'humain a tapé. L'envelopper dans une tâche v1 remplissait
#  la liste de lignes comme « Tu peux regarder mes mails/teams de ces 30 derniers jours… »,
#  une par conversation (6 vivantes mesurées le 2026-09-09, plus les rejeux de tour). Depuis
#  qu'il déclare ses tâches EXPLICITEMENT par l'outil `Taches`, l'enveloppement automatique
#  n'a plus rien à doubler. Le filtre est ici, dans la boucle, et non dans `_live_tickets()` :
#  rendre ces tickets invisibles ferait clôturer leurs tâches existantes par `_orphan_tasks`
#  avec `outcome="ticket disparu"`. Il ne réutilise pas non plus `constats.NON_CODING_TYPOLOGIES`,
#  qui pilote le parking des managers et `wake._finalize_noncoding_parent`.
TYPOLOGIES_SANS_TACHE = frozenset({"bureau-assistant"})


def _title_of(ticket: dict, key: Key) -> str:
    return (str(ticket.get("title") or "").strip() or f"ticket {key[1]}")[:200]


_INTENT_MAX = 240


def _intent_of(ticket: dict) -> str:
    """Amorce du prompt du ticket (1re ligne non vide, tronquée) : l'intent lisible du board.

    Le prompt du ticket EST la spec que l'agent reçoit : en reprendre l'amorce rend la tâche
    compréhensible seule au lieu d'un titre brut parachuté par la migration. Un ticket sans
    prompt garde une intent vide — le backfill de la réconciliation réessaiera plus tard.
    """
    text = (ticket.get("prompt") or "").strip()
    if not text:
        return ""
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if len(first) > _INTENT_MAX:
        first = first[:_INTENT_MAX - 1].rstrip() + "…"
    return first


def _backfill_intents(live: dict) -> int:
    """Complète l'intent des tâches migrées avant l'enrichissement. Rend le nombre remplies.

    Idempotent : une tâche qui a déjà une intent n'est jamais réécrite. La tâche est relue
    depuis `live` via son PREMIER lien ticket — suffisant, tous les tickets d'une tâche
    partagent la racine qui a porté la création."""
    first_link: dict[str, tuple] = {}
    for link in tasks_service.all_links():
        first_link.setdefault(link["task_id"], (link["slug"], link["ticket_id"]))
    filled = 0
    for task in tasks_service.list_tasks():
        if task.get("intent"):
            continue
        ticket = live.get(first_link.get(task["id"], ("", "")))
        intent = _intent_of(ticket) if ticket else ""
        if not intent:
            continue
        tasks_service.update_task(task["id"], intent=intent)
        tasks_service.add_event(
            task["id"], actor="moteur", kind="note",
            label="intent précisée depuis le prompt du ticket", why="backfill",
        )
        filled += 1
    return filled


def migrate_tickets_into_tasks() -> int:
    """Crée les tâches manquantes autour des tickets vivants. Rend le nombre de tâches créées."""
    tickets = _live_tickets()
    if not tickets:
        return 0
    parents = _parents(tickets, _agent_index(tickets))
    # Amorcé depuis la base : c'est CE dictionnaire qui rend la migration idempotente.
    task_of: dict[Key, str] = {
        (link["slug"], link["ticket_id"]): link["task_id"] for link in tasks_service.all_links()
    }
    created = 0
    for key in sorted(tickets):
        root = _root(key, parents)
        if root not in task_of:
            # Un ticket dont le travail est DÉJÀ terminé n'a plus rien à porter : l'enrôler
            # remplirait le board d'un « fait » qui n'attend personne. Skip idempotent : au
            # passage suivant il n'a toujours aucun lien, donc il est toujours écarté — et le
            # `continue` est obligatoire, sinon le lien enfant ci-dessous lèverait un KeyError.
            if _is_finished(tickets[root]):
                continue
            #  Même geste de skip idempotent que ci-dessus, pour une conversation qui ne
            #  porte pas de travail (cf. TYPOLOGIES_SANS_TACHE) : sans `continue`, le lien
            #  enfant plus bas lèverait un KeyError.
            if str(tickets[root].get("typology") or "") in TYPOLOGIES_SANS_TACHE:
                continue
            task = tasks_service.create_task(
                title=_title_of(tickets[root], root),
                intent=_intent_of(tickets[root]),
                project_slug=root[0],
                owner="agent",
                policy="observer",
            )
            tasks_service.link_ticket(task["id"], root[0], root[1], role="work")
            tasks_service.add_event(
                task["id"], actor="moteur", kind="note",
                label="tâche créée autour d'un ticket existant", why="migration de boot",
            )
            task_of[root] = task["id"]
            created += 1
        if key not in task_of:
            tasks_service.link_ticket(task_of[root], key[0], key[1], role="work")
            task_of[key] = task_of[root]
    return created


def _is_finished(ticket: dict, open_points: int = 0) -> bool:
    """Le travail de ce ticket est-il terminé ? Clos avec succès (`closed`), ou LIVRÉ sans
    plus aucun acte restant : ni commit non intégré (compte mémorisé par le tick, aucun git
    ici) ni point ouvert déclaré (`open_points`, décisions encore ouvertes de la tâche). Un
    ticket planté, bloqué ou en échec n'est jamais terminé : son état le dit."""
    if derive_status(ticket) == "terminé":
        return True
    reste = remaining_of(ticket, open_points=open_points)
    return (derive_status(ticket) == "à relire"
            and reste["unmerged_commits"] == 0 and reste["open_points"] == 0)


def _finished_tasks(live: dict[Key, dict], links: list[dict]) -> list[str]:
    """Les tâches d'agent ouvertes dont TOUT le travail encore vivant est terminé.

    Elles sont CLÔTURÉES, jamais supprimées : elles sortent du board par défaut et restent
    consultables (`include_closed=1`). C'est aussi le rattrapage de l'existant — rejouer cette
    passe sur une base déjà à jour ne fait rien, `closed_at` non vide écarte la tâche.

    Une tâche dont plus AUCUN ticket ne vit n'est pas jugée ici : c'est le cas orphelin."""
    linked: dict[str, list[Key]] = {}
    for link in links:
        linked.setdefault(link["task_id"], []).append((link["slug"], link["ticket_id"]))
    # UNE requête pour tout le parc : une tâche qui porte une décision ouverte n'est pas finie,
    # et interroger la base par ticket ferait 220 requêtes par tick.
    ouverts = decisions.count_open_by_task()
    finished: list[str] = []
    for task in tasks_service.list_tasks():
        keys = linked.get(task["id"]) or []
        if task["owner"] != "agent" or task["closed_at"] or not keys:
            continue
        vivants = [key for key in keys if key in live]
        points = ouverts.get(task["id"], 0)
        if vivants and all(_is_finished(live[key], open_points=points) for key in vivants):
            finished.append(task["id"])
    return finished


def _orphan_tasks(live: dict[Key, dict], links: list[dict]) -> list[str]:
    """Les tâches d'agent dont TOUS les tickets liés ont disparu (supprimés ou archivés).

    Trois garde-fous, tous nécessaires : `owner == "agent"` (une tâche `owner='moi'` est SAISIE
    à la main), `closed_at == ""` (ne pas re-clôturer), et AU MOINS un lien — une tâche sans
    aucun ticket n'est pas orpheline, elle est humaine, et la fermer détruirait du travail."""
    linked: dict[str, list[Key]] = {}
    for link in links:
        linked.setdefault(link["task_id"], []).append((link["slug"], link["ticket_id"]))
    orphans: list[str] = []
    for task in tasks_service.list_tasks():
        keys = linked.get(task["id"]) or []
        if task["owner"] != "agent" or task["closed_at"] or not keys:
            continue
        if all(key not in live for key in keys):
            orphans.append(task["id"])
    return orphans


def reconcile_tasks_with_tickets() -> dict[str, int]:
    """Réconcilie les tâches avec les tickets vivants. À rejouer EN CONTINU (watchdog).

    Deux sens, car un board qui ne montre que les apparitions serait aussi faux qu'un board figé :
    - un ticket apparu depuis le dernier passage devient une tâche (`migrate_tickets_into_tasks`,
      idempotente : son `task_of` est amorcé depuis `all_links()`, donc rejouer n'est jamais un
      doublon — c'est exactement l'appel du boot, ni plus ni moins) ;
    - une tâche dont tous les tickets ont disparu est CLÔTURÉE, pas supprimée : elle sort du board
      (`list_tasks(include_closed=False)`) tout en restant consultable avec `include_closed=1`.

    Pur SQLite : aucun appel git, aucun LLM, aucune lecture de fichier agent."""
    created = migrate_tickets_into_tasks()
    live = _live_tickets()
    # Les tâches créées AVANT que la migration ne renseigne une intent (ou autour d'un ticket
    # alors sans prompt) sont complétées ici, silencieusement : même sens « rattrapage » que
    # la création de tâches ci-dessus, mais en écriture ciblée et jamais pour écraser.
    _backfill_intents(live)
    closed = 0
    for task_id in _orphan_tasks(live, tasks_service.all_links()):
        tasks_service.close_task(task_id, outcome="ticket disparu")
        closed += 1
    # Recalculé APRÈS les orphelines : une tâche déjà close a un `closed_at`, donc elle n'est
    # jamais comptée deux fois. Une tâche qui arrive à son terme RESTE, simplement close.
    for task_id in _finished_tasks(live, tasks_service.all_links()):
        tasks_service.close_task(task_id, outcome="fait")
        closed += 1
    return {"created": created, "closed": closed}
