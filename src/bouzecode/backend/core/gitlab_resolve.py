# [desc] Résout une entrée (URL GitLab du navigateur OU chemin d'un dossier git local) en coordonnées online d'un repo plugin : scheme/host/project_path + nom pip + source git. [/desc]
"""Resolve a plugin-repo *input* to its ONLINE coordinates.

The input is either a GitLab web URL (what you copy from the browser bar) or the
path of a local folder backed by git. For a local path we never use its contents:
we read its git remote to deduce the online URL. We always target the online repo.

One GitLab repo == one pip plugin package: the repo name IS the pip distribution
name, so we can derive both the package-index name and a git+https fallback source
for the plugin installer.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


class SourceError(Exception):
    """User-facing error (bad input, no remote, clone failed, …)."""


def _git(*args: str) -> tuple[int, str, str]:
    """Run git with the interactive credentials prompt disabled.

    TLS verification stays ON. A GitLab behind a private CA must be handled the
    right way — install the CA, or point `http.sslCAInfo` at its bundle. As an
    explicit last resort, BOUZECODE_GIT_SSL_NO_VERIFY=1 disables the check; it is
    opt-in on purpose so no clone is ever silently unauthenticated.
    """
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    if os.environ.get("BOUZECODE_GIT_SSL_NO_VERIFY") == "1":
        env["GIT_SSL_NO_VERIFY"] = "1"
    proc = subprocess.run(["git", *args], capture_output=True, text=True, env=env)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _token() -> str:
    return os.environ.get("GITLAB_PRIVATE_TOKEN", "") or os.environ.get("GITLAB_TOKEN", "")


def _sanitize(text: str) -> str:
    """Strip the token from any text we surface (error messages, logs)."""
    tok = _token()
    return text.replace(tok, "***") if tok else text


def _normalize_remote_to_https(remote: str) -> str:
    """git@host:grp/repo.git and ssh://git@host/grp/repo.git → https://host/grp/repo.git."""
    remote = remote.strip()
    scp = re.match(r"^[\w.+-]+@([^:/]+):(.+)$", remote)
    if scp:
        return f"https://{scp.group(1)}/{scp.group(2)}"
    if remote.startswith("ssh://"):
        rest = remote[len("ssh://"):].split("@", 1)[-1]  # drop user@
        return "https://" + rest
    return remote


def _parse_gitlab_url(url: str) -> tuple[str, str, str, str | None, str | None]:
    """(scheme, host, project_path, ref, subpath) from a web or clone URL.

    GitLab always puts '/-/' before its in-repo routes, so it cleanly separates
    the project path (with any nested subgroups) from /-/tree/<ref>/<subpath>.
    """
    url = _normalize_remote_to_https(url)
    match = re.match(r"^(https?)://([^/]+)/(.+)$", url)
    if not match:
        raise SourceError(f"URL GitLab invalide : {url}")
    scheme, host, rest = match.group(1), match.group(2), match.group(3).strip("/")
    ref = subpath = None
    if "/-/" in rest:
        project_part, route = rest.split("/-/", 1)
        parts = route.split("/")
        if len(parts) >= 2 and parts[0] in ("tree", "blob"):
            ref = parts[1] or None
            subpath = "/".join(parts[2:]).strip("/") or None
    else:
        project_part = rest
    project_path = project_part.removesuffix(".git").strip("/")
    if not project_path:
        raise SourceError(f"chemin de projet introuvable dans l'URL : {url}")
    return scheme, host, project_path, ref, subpath


def _pick_remote(path: Path) -> str:
    """Remote URL of a local repo: origin, else the first remote."""
    code, url, _ = _git("-C", str(path), "remote", "get-url", "origin")
    if code == 0 and url:
        return url
    code, names, _ = _git("-C", str(path), "remote")
    if code == 0 and names:
        first = names.splitlines()[0].strip()
        code, url, _ = _git("-C", str(path), "remote", "get-url", first)
        if code == 0 and url:
            return url
    return ""


def _resolve_local_path(path: Path) -> tuple[str, str | None, str | None]:
    """(remote_https, ref, subpath) from a local git working dir."""
    code, toplevel, _ = _git("-C", str(path), "rev-parse", "--show-toplevel")
    if code != 0:
        raise SourceError(f"pas un dépôt git : {path}")
    remote = _pick_remote(path)
    if not remote:
        raise SourceError(f"dépôt local sans remote — il doit être en ligne : {path}")
    code, branch, _ = _git("-C", str(path), "symbolic-ref", "--quiet", "--short", "HEAD")
    ref = branch if code == 0 and branch else None
    rel = os.path.relpath(str(path.resolve()), str(Path(toplevel).resolve()))
    subpath = None if rel in (".", "") else rel.replace(os.sep, "/")
    return _normalize_remote_to_https(remote), ref, subpath


def _from_url(url: str) -> dict:
    scheme, host, project_path, ref, subpath = _parse_gitlab_url(url)
    return {"scheme": scheme, "host": host, "project_path": project_path,
            "ref": ref, "subpath": subpath, "web_url": f"{scheme}://{host}/{project_path}"}


def resolve_input(raw: str) -> dict:
    """Resolve a URL or a local git folder path to online coordinates (dict)."""
    raw = (raw or "").strip()
    if not raw:
        raise SourceError("entrée vide")
    is_url = bool(re.match(r"^(https?|ssh|git)://", raw) or re.match(r"^[\w.+-]+@[^:/]+:", raw))
    if is_url:
        return _from_url(raw)
    path = Path(raw).expanduser()
    if not path.is_dir():
        raise SourceError(f"ni une URL GitLab, ni un dossier git local existant : {raw}")
    remote, ref, subpath = _resolve_local_path(path)
    info = _from_url(remote)
    info["ref"], info["subpath"] = ref, subpath  # local path wins for ref/subpath
    return info


def plugin_install_target(info: dict) -> tuple[str, str]:
    """(pip package name, git+https fallback source) for a resolved plugin repo.

    Convention: the repo's last path segment is the pip distribution name
    (e.g. .../plugins/demo-sql-plugin → 'demo-sql-plugin')."""
    package = info["project_path"].rsplit("/", 1)[-1]
    git_source = f"git+{info['scheme']}://{info['host']}/{info['project_path']}.git"
    return package, git_source
