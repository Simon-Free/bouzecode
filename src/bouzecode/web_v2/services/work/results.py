# [desc] Résultats d'un ticket: liens MR/PR trouvés dans la session, branche et commits git récents. [/desc]
"""Best-effort sans config : les URLs de MR sortent du texte de la session (sortie
`git push` GitLab/GitHub), l'état git vient d'un `git` exécuté dans le projet."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ...runtime.runner import agent_fiche
from ..sessions import store

_MR_URL_RE = re.compile(
    r"https?://[^\s'\"<>)\]]+/(?:-/)?(?:merge_requests|pull|pullrequest)/\d+", re.IGNORECASE)
_GIT_TIMEOUT_S = 5


def _session_text(agent: agent_fiche.Agent) -> str:
    data = store.load_session_json(Path(agent.session_path)) or {}
    chunks = []
    for message in data.get("messages", []):
        content = message.get("content")
        if isinstance(content, str):
            chunks.append(content)
    return "\n".join(chunks)


def _mr_links(ticket: dict) -> list[str]:
    links: list[str] = []
    for run in ticket["runs"]:
        if run["kind"] != "work":
            continue
        agent = agent_fiche.load_agent(run["agent_id"])
        if agent is None:
            continue
        for url in _MR_URL_RE.findall(_session_text(agent)):
            if url not in links:
                links.append(url)
    return links


def _git(project_path: str, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", project_path, *args],
        capture_output=True, text=True, timeout=_GIT_TIMEOUT_S, encoding="utf-8", errors="replace",
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _files_summary(ticket: dict) -> dict:
    work_run = next((r for r in ticket["runs"] if r["kind"] == "work"), None)
    if work_run is None:
        return {"count": 0, "session_key": ""}
    agent = agent_fiche.load_agent(work_run["agent_id"])
    if agent is None:
        return {"count": 0, "session_key": ""}
    data = store.load_session_json(Path(agent.session_path)) or {}
    return {
        "count": len(data.get("file_snapshots") or {}),
        "session_key": f"agent/{work_run['agent_id']}",
    }


class GitTropLent(RuntimeError):
    """Une commande git a dépassé `_GIT_TIMEOUT_S` : la route répond 504, pas 500."""


def _git_borne(project_path: str, *args: str) -> str:
    try:
        return _git(project_path, *args)
    except subprocess.TimeoutExpired as exc:
        raise GitTropLent(f"git {' '.join(args[:2])} a dépassé {_GIT_TIMEOUT_S} s") from exc


def _branche_et_commits(project: dict, ticket: dict) -> tuple[str, str, list[str]]:
    """(branche, base, commits) du TICKET (constat C13) : sa branche de travail comparée à sa
    base quand il est isolé ; sinon la branche courante du dépôt depuis la création du ticket."""
    meta = ticket.get("worktree") if isinstance(ticket.get("worktree"), dict) else {}
    branch, base = meta.get("branch") or "", meta.get("base") or ""
    if branch:
        plage = f"{base}..{branch}" if base else branch
        brut = _git_borne(project["path"], "log", "--oneline", "-n", "8", plage)
        return branch, base, brut.splitlines() if brut else []
    branch = _git_borne(project["path"], "rev-parse", "--abbrev-ref", "HEAD")
    brut = _git_borne(project["path"], "log", "--oneline", "-n", "8",
                      f"--since={ticket['created_at']}")
    return branch, "", brut.splitlines() if brut else []


def ticket_results(project: dict, ticket: dict) -> dict:
    """Tout ce qu'il faut pour relire un ticket : MR, branche, commits, fichiers.
    Lève `GitTropLent` si git ne répond pas à temps."""
    branch, base, commits = _branche_et_commits(project, ticket)
    return {
        "mr_links": _mr_links(ticket),
        "branch": branch,
        "base": base,
        "commits": commits,
        "files": _files_summary(ticket),
    }
