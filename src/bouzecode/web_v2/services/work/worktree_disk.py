# [desc] Le vrai poste disque : les `.venv` des bacs à sable. Inventaire, et récupération de ce qui se refait par `uv sync`. [/desc]
r"""Ce que pèsent les worktrees d'agents, et comment en récupérer l'espace SANS RIEN PERDRE.

MESURÉ SUR UN POSTE RÉEL. `~/.bouzecode` pesait 104 Go. Sa répartition :
    worktrees/    91 253 Mo   ← dont 82 830 Mo de `.venv`
    sessions/      7 650 Mo
    web_agents/    1 835 Mo
Soit 166 bacs à sable, et ~1 Go de dépendances installées dans chacun (un `uv sync
--all-extras` d'une application Python de taille moyenne). Aucun n'est partagé avec un autre.

POURQUOI VISER LES `.venv` ET RIEN D'AUTRE. Un venv est un ARTEFACT REPRODUCTIBLE : `uv sync`
le refait à l'identique depuis `uv.lock`. Le supprimer ne détruit aucun travail — c'est le seul
endroit de tout ce parc où l'on peut récupérer des dizaines de gigaoctets sans risquer une
ligne de code. Le reste du worktree, lui, peut porter du travail NON COMMITÉ : on n'y touche
pas ici (cf. `delivery.harvest_before_reclaiming`, `reaper`).

QUATRE EXCLUSIONS, dans cet ordre :
  0. tout chemin qui est un LIEN (jonction / symlink) — voir l'avertissement ci-dessous ;
  1. un worktree dont un agent est VIVANT — il s'en sert, à l'instant ;
  2. un worktree dont le ticket est encore OUVERT — son agent va reprendre, et lui refaire
     payer un `uv sync` de plusieurs minutes serait une fausse économie ;
  3. tout ce qui n'est pas exactement un dossier `.venv`.
Ce qui reste : les bacs à sable de tickets terminés ou dont le ticket n'existe même plus.

⚠️ LA JONCTION QUI A DÉTRUIT LE VENV DU DÉPÔT PRINCIPAL (2026-07-30). Cet arbre ne contient
PAS que des bacs à sable : `worktree_sources.link_editable_sources` y crée des JONCTIONS vers
les vrais dépôts, pour que les dépendances editables (`../bouzecode`) se résolvent depuis un
worktree isolé. Elles ressemblent en tout point à un dossier :

    ~/.bouzecode/worktrees/demo_app/bouzecode  ->  C:\…\dev\demo_monorepo\bouzecode

La première version de ce module les a prises pour des bacs à sable — leur nom n'étant pas un
id de ticket, elles ont été classées `inconnu`, donc récupérables — et `shutil.rmtree` a suivi
le lien : le `.venv` du VRAI dépôt bouzecode a été effacé (celui qui lance le serveur et les
tests), et celui du monorepo voisin avec. D'où la règle 0, appliquée AVANT toute autre : sur
un chemin qui traverse un lien, on ne supprime rien, jamais. `os.walk` et `rglob` ne
protègent de rien ici — c'est `is_symlink()` / l'attribut de point d'analyse qui le dit, et il
faut l'interroger sur CHAQUE segment, pas seulement sur le `.venv` final.
"""
from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

from ...runtime import runner
from ..sessions import store
from . import projects, reaper, tickets, worktrees

# Vivacités qui prouvent qu'un agent se sert de son bac à sable EN CE MOMENT.
_ETATS_VIVANTS = ("running", "starting", "awaiting_input", "awaiting_plan_validation", "idle")


def is_link(path: Path) -> bool:
    """`path` est-il un LIEN (symlink POSIX ou JONCTION Windows) ?

    Les deux, obligatoirement : sous Windows, `os.path.islink` répond FAUX sur une jonction —
    c'est exactement ce qui a laissé passer `worktrees/demo_app/bouzecode` pour un
    dossier ordinaire.

    La jonction est détectée par l'ATTRIBUT de point d'analyse, et non par
    `os.path.isjunction` : cette fonction n'existe qu'à partir de Python 3.12, or le venv du
    projet tourne en 3.11.14 — la première version de cette garde levait donc un
    `AttributeError` sur le poste même qu'elle devait protéger. `st_file_attributes` n'existe
    que sous Windows, d'où le repli à « pas un lien » ailleurs."""
    if os.path.islink(path):
        return True
    try:
        attributs = os.lstat(path).st_file_attributes
    except (OSError, AttributeError):
        return False  # chemin disparu, ou plateforme sans attributs de fichier
    return bool(attributs & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def crosses_link(path: Path, under: Path) -> bool:
    """Le chemin `path` traverse-t-il un lien, à n'importe quel segment sous `under` ?

    On interroge CHAQUE segment : tester le seul dossier final laisserait passer
    `<lien>/.venv`, qui est un vrai dossier… dans le vrai dépôt, à l'autre bout du lien."""
    if is_link(path):
        return True
    current = path.parent
    under = under.resolve()
    while True:
        if is_link(current):
            return True
        if current.resolve() == under or current.parent == current:
            return False
        current = current.parent


def _dir_bytes(root: Path) -> int:
    """Poids d'un dossier, sans JAMAIS traverser un lien (sinon on compterait le vrai dépôt)."""
    if not root.is_dir() or is_link(root):
        return 0
    return sum(f.stat().st_size for f in root.rglob("*")
               if f.is_file() and not is_link(f))


def _tickets_by_id() -> dict[str, dict]:
    """Tous les tickets des projets ouverts, archivés compris, indexés par id."""
    index = {}
    for project in projects.list_projects():
        for ticket in tickets.list_tickets(project["slug"], include_archived=True):
            index[ticket["id"]] = ticket
    return index


def _live_ticket_ids() -> set[str]:
    return {
        getattr(agent, "ticket_id", "") or ""
        for agent in runner.list_agents()
        if store.agent_status(agent).get("state") in _ETATS_VIVANTS
    }


def classify(ticket_id: str, index: dict[str, dict], live: set[str]) -> str:
    """'agent_vivant' | 'ouvert' | 'terminal' | 'inconnu' — les deux premiers sont INTOUCHABLES.

    'inconnu' = aucun ticket de ce nom dans le store (projet fermé, ticket purgé). Son bac à
    sable ne sera plus jamais repris par personne ; ses commits, eux, vivent sur la branche
    `agent/<id>`, que ce module ne touche pas."""
    if ticket_id and ticket_id in live:
        return "agent_vivant"
    ticket = index.get(ticket_id)
    if ticket is None:
        return "inconnu"
    if reaper.terminal_outcome(ticket) or ticket.get("done") or ticket.get("archived"):
        return "terminal"
    return "ouvert"


def _venvs() -> list[dict]:
    """Un enregistrement par bac à sable portant un `.venv`, avec sa classe et son poids."""
    index, live = _tickets_by_id(), _live_ticket_ids()
    rows = []
    if not worktrees.WORKTREES_DIR.is_dir():
        return rows
    for repo_dir in worktrees.WORKTREES_DIR.iterdir():
        if not repo_dir.is_dir() or is_link(repo_dir):
            continue
        for sandbox in repo_dir.iterdir():
            venv = sandbox / ".venv"
            if not (sandbox.is_dir() and venv.is_dir()):
                continue
            # RÈGLE 0 : un lien n'est pas un bac à sable. Le franchir mène au VRAI dépôt —
            # c'est ce qui a effacé le venv du dépôt principal. On ne le liste même pas :
            # ce qui n'entre pas dans l'inventaire ne peut pas être supprimé plus tard.
            if crosses_link(venv, worktrees.WORKTREES_DIR):
                continue
            rows.append({
                "repo": repo_dir.name,
                "ticket_id": sandbox.name,
                "venv": str(venv),
                "classe": classify(sandbox.name, index, live),
                "bytes": _dir_bytes(venv),
            })
    return rows


RECLAIMABLE = ("terminal", "inconnu")


def inventory() -> dict:
    """Poids des `.venv` par classe de bac à sable, SANS RIEN TOUCHER.

    `recuperable` = les venvs des classes `RECLAIMABLE`, du plus gros au plus petit."""
    rows = _venvs()
    par_classe: dict[str, dict] = {}
    for row in rows:
        seau = par_classe.setdefault(row["classe"], {"venvs": 0, "bytes": 0})
        seau["venvs"] += 1
        seau["bytes"] += row["bytes"]
    recuperable = sorted((r for r in rows if r["classe"] in RECLAIMABLE),
                         key=lambda r: r["bytes"], reverse=True)
    return {
        "venvs": len(rows),
        "bytes": sum(row["bytes"] for row in rows),
        "par_classe": par_classe,
        "recuperable": recuperable,
        "recuperable_bytes": sum(row["bytes"] for row in recuperable),
    }


def reclaim_venvs(confirm: bool = False) -> dict:
    """Supprime les `.venv` récupérables. `confirm=False` (défaut) : simulation.

    Ne touche QUE des dossiers nommés `.venv` : le worktree, son code et son travail non
    commité restent intacts, et un `uv sync` reconstruit l'environnement si le bac à sable
    reprend vie. La classe est RECALCULÉE juste avant chaque suppression, pas seulement à
    l'inventaire : entre les deux, un ticket a pu être relancé."""
    etat = inventory()
    if not confirm:
        return {"simulation": True, "venvs": len(etat["recuperable"]),
                "bytes": etat["recuperable_bytes"],
                "detail": [{"ticket_id": r["ticket_id"], "repo": r["repo"],
                            "classe": r["classe"], "bytes": r["bytes"]}
                           for r in etat["recuperable"]]}
    if not runner.destruction_permitted():
        return {"simulation": False, "supprimes": [],
                "refuse": "destruction interdite hors exploitation"}
    index, live = _tickets_by_id(), _live_ticket_ids()
    supprimes, liberes, refuses = [], 0, []
    for row in etat["recuperable"]:
        if classify(row["ticket_id"], index, live) not in RECLAIMABLE:
            refuses.append(row["ticket_id"])  # repris entre-temps
            continue
        venv = Path(row["venv"])
        # Défense en profondeur, re-vérifiée à l'instant de détruire : jamais autre chose
        # qu'un dossier `.venv`, et jamais un chemin qui traverse un lien. L'inventaire
        # filtre déjà les deux ; ce second contrôle existe parce que la conséquence d'un
        # trou ici est la destruction d'un vrai dépôt, et que ça s'est produit.
        if venv.name != ".venv" or crosses_link(venv, worktrees.WORKTREES_DIR):
            refuses.append(row["ticket_id"])
            continue
        shutil.rmtree(venv, ignore_errors=True)
        supprimes.append(row["ticket_id"])
        liberes += row["bytes"]
    return {"simulation": False, "supprimes": supprimes, "bytes": liberes, "refuses": refuses}
