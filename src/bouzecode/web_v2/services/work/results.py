# [desc] Résultats d'un ticket: liens MR/PR trouvés dans la session, branche et commits git récents. [/desc]
"""Best-effort sans config : les URLs de MR sortent du texte de la session (sortie
`git push` GitLab/GitHub), l'état git vient d'un `git` exécuté dans le projet."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ....web import runner
from ..sessions import store

_MR_URL_RE = re.compile(
    r"https?://[^\s'\"<>)\]]+/(?:-/)?(?:merge_requests|pull|pullrequest)/\d+", re.IGNORECASE)
_GIT_TIMEOUT_S = 5


def _session_text(agent: runner.Agent) -> str:
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
        agent = runner.load_agent(run["agent_id"])
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
    agent = runner.load_agent(work_run["agent_id"])
    if agent is None:
        return {"count": 0, "session_key": ""}
    data = store.load_session_json(Path(agent.session_path)) or {}
    return {
        "count": len(data.get("file_snapshots") or {}),
        "session_key": f"agent/{work_run['agent_id']}",
    }


def ticket_results(project: dict, ticket: dict) -> dict:
    """Tout ce qu'il faut pour relire un ticket : MR, branche, commits depuis création, fichiers."""
    branch = _git(project["path"], "rev-parse", "--abbrev-ref", "HEAD")
    commits_raw = _git(
        project["path"], "log", "--oneline", "-n", "8", f"--since={ticket['created_at']}")
    return {
        "mr_links": _mr_links(ticket),
        "branch": branch,
        "commits": commits_raw.splitlines() if commits_raw else [],
        "files": _files_summary(ticket),
    }
