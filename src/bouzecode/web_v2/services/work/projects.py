# [desc] Registre des projets ouverts + agents par projet + compteurs d'actions requises. [/desc]
from __future__ import annotations
from bouzecode.paths import data_dir as bouzecode_data_dir

import json
import os
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ...runtime.runner import agent_fiche, agent_registre
from ..sessions import store
from . import repos
from ....backend.core.garde_vrai_home import refuser_le_vrai_home

PROJECTS_PATH = bouzecode_data_dir() / "web_v2" / "projects.json"

# Les compteurs de `overview()` coûtent ~2,5 s sur un gros parc (parse des verdicts + statut
# de ~1000 agents) et le sélecteur de dépôts les redemande souvent : cache TTL court +
# single-flight, un seul recalcul partagé entre requêtes concurrentes.
_overview_cache: dict = {}
_overview_lock = threading.Lock()
_overview_compute_lock = threading.Lock()
_OVERVIEW_TTL = 5.0  # secondes ; des compteurs vieux de 5 s sur un dashboard sont sans enjeu


def _cached_overview(key: str, compute):
    now = time.monotonic()
    with _overview_lock:
        entry = _overview_cache.get(key)
        if entry and now < entry[1]:
            return entry[0]
    with _overview_compute_lock:  # single-flight : un seul thread recalcule
        with _overview_lock:
            entry = _overview_cache.get(key)
            if entry and time.monotonic() < entry[1]:
                return entry[0]
        result = compute()
        with _overview_lock:
            _overview_cache[key] = (result, time.monotonic() + _OVERVIEW_TTL)
        return result


def slugify(name: str) -> str:
    """« Dépôt Été » → « depot-ete » : les accents sont TRANSLITTÉRÉS (NFKD), pas supprimés
    (avant : « d-p-t »). Seule la création d'un projet l'appelle : un slug déjà enregistré
    n'est jamais recalculé, donc aucun projet existant ne change d'identifiant."""
    ascii_ = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9-]+", "-", ascii_.lower()).strip("-") or "projet"


def list_projects() -> list[dict]:
    if not PROJECTS_PATH.is_file():
        return []
    projects = json.loads(PROJECTS_PATH.read_text(encoding="utf-8"))
    return projects if isinstance(projects, list) else []


def _save(projects: list[dict]) -> None:
    refuser_le_vrai_home(PROJECTS_PATH)  # 2026-10-06 : un test avait écrasé le vrai registre
    PROJECTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = PROJECTS_PATH.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(projects, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(PROJECTS_PATH)
    # Le registre vient de changer : la vue d'ensemble mémorisée (5 s) est fausse. Sans cette
    # ligne, un dépôt tout juste ajouté restait absent du sélecteur, et un dépôt retiré y restait.
    with _overview_lock:
        _overview_cache.clear()


def add_project(name: str, path: str, description: str = "") -> dict | str:
    """Retourne le projet créé, ou un message d'erreur.

    Un projet l'est parce que l'utilisateur l'a désigné : la seule chose vérifiée
    ici est que le dossier existe. Aucun marqueur (`.git`, `.bouzecode/`) n'est
    exigé — deviner ce qui est un projet est précisément ce qui a peuplé ce
    registre d'entrées fantômes.
    """
    from . import dismissed_paths  # import local : évite tout cycle au chargement

    resolved = Path(path).expanduser()
    if not resolved.is_dir():
        return f"dossier introuvable: {path}"
    slug = slugify(name)
    projects = list_projects()
    if any(p["slug"] == slug for p in projects):
        return f"projet déjà ouvert: {slug}"
    project = {
        "name": name.strip(),
        "slug": slug,
        "path": str(resolved.resolve()),
        "description": description.strip()[:200],
    }
    projects.append(project)
    _save(projects)
    # Se raviser doit marcher : le désigner projet lève l'éventuel « ce n'en est pas un ».
    dismissed_paths.undismiss(resolved)
    return project


def update_project(slug: str, description: str) -> dict | None:
    """Met à jour la description d'un projet. Retourne le projet modifié, ou None si inconnu."""
    projects = list_projects()
    project = next((p for p in projects if p["slug"] == slug), None)
    if project is None:
        return None
    project["description"] = description.strip()[:200]
    _save(projects)
    return project


def remove_project(slug: str) -> bool:
    projects = list_projects()
    remaining = [p for p in projects if p["slug"] != slug]
    if len(remaining) == len(projects):
        return False
    from . import nettoyage  # import local : évite tout cycle au chargement du module
    # Retirer un projet abandonne son travail → on nettoie le worktree de chacun de ses tickets
    # qui passe les gardes (aucun run vivant, travail récolté proprement ; branche gardée).
    # Sans ça, les worktrees restaient orphelins ; un ticket refusé garde le sien (B9).
    nettoyage.nettoyer_le_projet(slug)
    _save(remaining)
    return True


def find(slug: str) -> dict | None:
    return next((p for p in list_projects() if p["slug"] == slug), None)


def _chemin_compare(chemin: str) -> str:
    """Forme comparable d'un chemin (casse et séparateurs de l'OS, sans séparateur final)."""
    return os.path.normcase(os.path.normpath(chemin)).rstrip("\\/")


def _belongs_to(agent_cwd: str, project_path: str) -> bool:
    """`agent_cwd` est le dossier du projet ou l'un de ses descendants.

    Comparaison de CHAÎNES normalisées : l'ancienne (`target in Path(cwd).parents`) créait et
    comparait un `Path` par ancêtre — 0,7 s par arbre d'agents (500 agents × 13 projets)."""
    if not agent_cwd or not project_path:
        return False
    cwd, target = _chemin_compare(agent_cwd), _chemin_compare(project_path)
    return cwd == target or cwd.startswith(target + os.sep)


def project_for_cwd(agent_cwd: str, projects: list[dict] | None = None) -> dict | None:
    """Projet ouvert auquel appartient un cwd d'agent (ou None si hors projet)."""
    for project in (projects if projects is not None else list_projects()):
        if _belongs_to(agent_cwd, project["path"]):
            return project
    return None


def slug_of_agent(agent_id: str) -> str:
    """Slug du projet d'un agent DÉJÀ lancé, servi par sa fiche (GET /api/agents/<id>) : l'outil
    `Agent` d'un manager y lit le projet de ses enfants (un enfant travaille sur LE projet de
    son manager).

    Deux sources, dans cet ordre :
    1. `agent.ticket_slug` — le slug de PROJET enregistré au spawn (cf. `dispatch._launch`,
       qui passe `ticket_slug=<slug projet>`). Source FIABLE : elle reste juste même quand
       l'agent travaille dans un worktree, lequel vit sous `~/.bouzecode/worktrees/…`, donc
       HORS du dossier du projet — cas où `project_for_cwd` ne trouverait rien.
    2. `project_for_cwd(agent.cwd)` — repli pour un agent lancé SANS ticket : en isolation
       'shared' son cwd EST le dossier du projet ; s'il s'est isolé depuis (`Environment`),
       son cwd est un worktree hors du projet, et c'est le dépôt de ce worktree qui compte.

    Renvoie "" pour un lancement manuel ('dispatcher:*'), un agent inconnu, ou un slug dont
    le projet n'est plus ouvert — l'outil refuse alors en `projet_requis`."""
    if not agent_id or agent_id.startswith("dispatcher:"):
        return ""
    agent = agent_fiche.load_agent(agent_id)
    if agent is None:
        return ""
    slug = getattr(agent, "ticket_slug", "") or ""
    if slug and find(slug):
        return slug
    project = _projet_du_cwd(getattr(agent, "cwd", "") or "")
    return project["slug"] if project else ""


def _projet_du_cwd(cwd: str) -> dict | None:
    """Le projet du dossier, ou celui du DÉPÔT quand le dossier est un worktree hors projet."""
    return project_for_cwd(cwd) or project_for_cwd(repos.repo_root(cwd) or "")


def agents_of(project: dict, agents: list | None = None) -> list[dict]:
    """Agents web dont le cwd est dans le projet, avec statut live (du plus récent au plus ancien).

    If *agents* is provided (list of Agent objects), uses that instead of calling list_agents().
    This avoids redundant disk reads when the caller already has the full list.
    """
    all_agents = agents if agents is not None else agent_registre.list_agents()
    rows = []
    for agent in all_agents:
        if not _belongs_to(agent.cwd, project["path"]):
            continue
        rows.append({
            "key": f"agent/{agent.agent_id}",
            "agent_id": agent.agent_id,
            "title": (agent.prompt or "").strip().split("\n")[0][:90],
            "model": agent.model,
            "started_at": agent.started_at,
            "status": store.agent_status(agent),
        })
    rows.sort(key=lambda row: row["started_at"], reverse=True)
    return rows


def overview() -> list[dict]:
    """Projets + compteurs pour la home (caché ~4 s, single-flight)."""
    return _cached_overview("overview", _overview_uncached)


def _overview_uncached() -> list[dict]:
    """Projets + compteurs pour la home: où dois-je agir ?"""
    from . import tickets as tickets_service
    all_agents = agent_registre.list_agents()  # single call for all projects

    def _compute_one(project: dict) -> dict:
        agents = agents_of(project, agents=all_agents)
        project_tickets = tickets_service.list_tickets(project["slug"])
        # Même vérité que le board : le statut est la projection de `ticket.state`.
        statuses = [tickets_service.derive_status(t) for t in project_tickets]
        return {
            **project,
            "agents_running": sum(1 for a in agents if a["status"]["state"] == "running"),
            "agents_awaiting": sum(1 for a in agents if a["status"]["state"] == "awaiting_input"),
            "tickets_to_review": statuses.count("à relire"),
            "tickets_total": len(project_tickets),
        }

    projects = list_projects()
    if not projects:
        return []
    # I/O-bound (scan disque/git par projet) : paralléliser au lieu de sommer les
    # latences en série. executor.map préserve l'ordre du tableau projects.
    with ThreadPoolExecutor(max_workers=min(8, len(projects))) as executor:
        return list(executor.map(_compute_one, projects))
