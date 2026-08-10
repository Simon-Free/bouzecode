# [desc] Registre des projets ouverts + agents par projet + compteurs d'actions requises. [/desc]
from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ...runtime import runner
from ..sessions import store

PROJECTS_PATH = Path.home() / ".bouzecode" / "web_v2" / "projects.json"

# Les compteurs home (overview/logical_overview) coûtent ~2,5 s (parse verdicts + statut de
# ~1000 agents). Le front les poll toutes les ~1-2 s et sur 2 endpoints → sans cache, chaque
# poll relançait le calcul complet ET les requêtes concurrentes se sérialisaient (24 s à 6).
# Cache TTL court + single-flight : un seul recalcul partagé, résultat quasi instantané.
_overview_cache: dict = {}
_overview_lock = threading.Lock()
# RLock (réentrant) : logical_overview() appelle overview() en tenant DÉJÀ ce lock (même
# thread) → un Lock simple deadlockerait sur lui-même et empoisonnerait le lock pour toutes les
# requêtes suivantes. RLock autorise la ré-entrée du même thread tout en sérialisant les autres.
_overview_compute_lock = threading.RLock()
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
    return re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-") or "projet"


def list_projects() -> list[dict]:
    if not PROJECTS_PATH.is_file():
        return []
    projects = json.loads(PROJECTS_PATH.read_text(encoding="utf-8"))
    return projects if isinstance(projects, list) else []


def _save(projects: list[dict]) -> None:
    PROJECTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = PROJECTS_PATH.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(projects, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(PROJECTS_PATH)


def add_project(name: str, path: str, description: str = "") -> dict | str:
    """Retourne le projet créé, ou un message d'erreur."""
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
    from . import reaper  # import local : évite tout cycle au chargement du module
    # Retirer un projet abandonne son travail actif → on réclame le worktree de chacun de ses
    # tickets (branche gardée, commits récupérables). Sans ça, les worktrees restaient orphelins.
    reaper.reap_project(slug)
    _save(remaining)
    return True


def find(slug: str) -> dict | None:
    return next((p for p in list_projects() if p["slug"] == slug), None)


def _belongs_to(agent_cwd: str, project_path: str) -> bool:
    if not agent_cwd:
        return False
    cwd = Path(agent_cwd)
    target = Path(project_path)
    return cwd == target or target in cwd.parents


def project_for_cwd(agent_cwd: str, projects: list[dict] | None = None) -> dict | None:
    """Projet ouvert auquel appartient un cwd d'agent (ou None si hors projet)."""
    for project in (projects if projects is not None else list_projects()):
        if _belongs_to(agent_cwd, project["path"]):
            return project
    return None


def slug_of_agent(agent_id: str) -> str:
    """Slug du projet d'un agent DÉJÀ lancé. Sert l'HÉRITAGE de projet : un enfant dispatché
    par un manager travaille sur LE projet de son manager.

    Deux sources, dans cet ordre :
    1. `agent.ticket_slug` — le slug de PROJET enregistré au spawn (cf. `dispatch._launch`,
       qui passe `ticket_slug=<slug projet>`). Source FIABLE : elle reste juste même quand
       l'agent travaille dans un worktree, lequel vit sous `~/.bouzecode/worktrees/…`, donc
       HORS du dossier du projet — cas où `project_for_cwd` ne trouverait rien.
    2. `project_for_cwd(agent.cwd)` — repli pour un agent lancé SANS ticket : en isolation
       'shared' son cwd EST le dossier du projet.

    Renvoie "" pour un lancement manuel ('dispatcher:*'), un agent inconnu, ou un slug dont
    le projet n'est plus ouvert — l'appelant retombe alors sur `needs_project`."""
    if not agent_id or agent_id.startswith("dispatcher:"):
        return ""
    agent = runner.load_agent(agent_id)
    if agent is None:
        return ""
    slug = getattr(agent, "ticket_slug", "") or ""
    if slug and find(slug):
        return slug
    project = project_for_cwd(getattr(agent, "cwd", "") or "")
    return project["slug"] if project else ""


def agents_of(project: dict, agents: list | None = None) -> list[dict]:
    """Agents web dont le cwd est dans le projet, avec statut live (du plus récent au plus ancien).

    If *agents* is provided (list of Agent objects), uses that instead of calling list_agents().
    This avoids redundant disk reads when the caller already has the full list.
    """
    all_agents = agents if agents is not None else runner.list_agents()
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
    all_agents = runner.list_agents()  # single call for all projects
    # Index agent_id -> Agent : réutilisé par refresh_verdicts/_attach_run_state pour
    # un lookup mémoire au lieu de re-load_agent(id) disque par run (~500 lectures à froid).
    agents_index = {a.agent_id: a for a in all_agents}

    def _compute_one(project: dict) -> dict:
        agents = agents_of(project, agents=all_agents)
        project_tickets = tickets_service.list_tickets(
            project["slug"], refresh=True, persist=False, agents_index=agents_index)
        # Même vérité que le board (cf. routes/work/tickets.py) : un manager SANS enfant
        # n'est pas « en attente des enfants » mais « à relire » — il doit donc peser dans
        # le compteur d'actions de la home, pas disparaître dans un limbo.
        parents = tickets_service.parent_agent_ids(project["slug"])
        statuses = [tickets_service.derive_status(t, parents_with_children=parents)
                    for t in project_tickets]
        return {
            **project,
            "agents_running": sum(1 for a in agents if a["status"]["state"] == "running"),
            "agents_awaiting": sum(1 for a in agents if a["status"]["state"] == "awaiting_input"),
            "tickets_to_review": statuses.count("à relire"),
            "validations_ko": sum(
                1 for t in project_tickets for r in t["runs"]
                if r["kind"].startswith("validate") and r.get("verdict") == "KO"
            ),
            "tickets_total": len(project_tickets),
        }

    projects = list_projects()
    if not projects:
        return []
    # I/O-bound (scan disque/git par projet) : paralléliser au lieu de sommer les
    # latences en série. executor.map préserve l'ordre du tableau projects.
    with ThreadPoolExecutor(max_workers=min(8, len(projects))) as executor:
        return list(executor.map(_compute_one, projects))


def logical_overview() -> list[dict]:
    """Projets logiques + compteurs agrégés (caché ~4 s, single-flight)."""
    return _cached_overview("logical_overview", _logical_overview_uncached)


def _logical_overview_uncached() -> list[dict]:
    """Projets regroupés par dépôt git (worktrees pliés sous un même projet).

    Deux dépôts distincts peuvent avoir le même nom de dossier (ex. le vrai
    demo_ingestion et sa copie sous temp/migration_en_cours) → on désambiguïse
    le nom par le dossier parent et on garantit des slugs uniques."""
    from collections import Counter

    from . import repos
    groups = repos.group_overview(overview())
    name_counts = Counter(group["name"] for group in groups)
    used_slugs: set[str] = set()
    for group in groups:
        if name_counts[group["name"]] > 1:
            group["name"] = f"{group['name']} ({repos.parent_hint(group['key'])})"
        group["slug"] = _unique_slug(slugify(group["name"]), used_slugs)
        for worktree in group["worktrees"]:
            worktree["branch"] = repos.branch_of(worktree["path"])
    return groups


def _unique_slug(base: str, used: set[str]) -> str:
    slug, i = base, 2
    while slug in used:
        slug, i = f"{base}-{i}", i + 1
    used.add(slug)
    return slug
