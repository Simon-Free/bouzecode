# [desc] Environment the Bash tool runs commands in: user-level env vars merged case-insensitively, and the absolute path to powershell.exe. [/desc]
"""Where and with what a shell command runs.

Split out of shell_search.py (file-size rule); both helpers stay importable from
shell_search, which is how the rest of the codebase addresses them."""
import functools
import os

from . import venv_du_projet, venv_meme_projet


def _merge_user_env(env: dict[str, str], reg_items: list[tuple[str, str]]) -> dict[str, str]:
    """Merge registry user vars into a copy of `env`, CASE-INSENSITIVELY.

    Windows env var names are case-insensitive, but a plain dict is not: blindly
    adding the registry `Path` next to the process `PATH` yields two keys that
    differ only by case. Under CreateProcess the stale registry value then
    SHADOWS the in-process one — which silently defeats the PowerShell-on-PATH
    repair (and setx), breaking every Bash command with `'powershell' n'est pas
    reconnu`. So:
      - a registry var matching an existing key (ignoring case) is never added
        as a second key;
      - PATH is merged: registry entries absent from the process PATH are
        appended under the existing key, so a freshly-set user PATH is still
        picked up without ever shadowing the repair.
    Pure (no winreg) so the merge stays testable."""
    out = dict(env)
    lower_to_key = {k.lower(): k for k in out}
    for name, value in reg_items:
        low = name.lower()
        if low == "path":
            cur = lower_to_key.get("path")
            if cur is None:
                out[name] = value
                lower_to_key["path"] = name
                continue
            seen = {p.strip().lower() for p in out[cur].split(os.pathsep) if p.strip()}
            extra = [p for p in value.split(os.pathsep)
                     if p.strip() and p.strip().lower() not in seen]
            if extra:
                out[cur] = out[cur] + os.pathsep + os.pathsep.join(extra)
        elif low not in lower_to_key:
            out[name] = value
            lower_to_key[low] = name
    return out


def strip_inherited_python_home(env: dict[str, str]) -> dict[str, str]:
    """Drop an inherited PYTHONHOME from the env handed to child processes.

    PYTHONHOME pins the standard library of ONE interpreter. bouzecode is often
    started by uv/an IDE, which leaks its own PYTHONHOME (e.g. uv's
    cpython-3.12) into the process env; every shell command then runs the
    `python.exe` found on PATH (3.13 here) against a 3.12 stdlib, and the very
    first `import re` dies with `AssertionError: SRE module mismatch` because
    the C `_sre` and the Python `re` come from different versions.

    No legitimate use is lost: an interpreter/venv is selected by its binary
    and its pyvenv.cfg, never by PYTHONHOME. PYTHONPATH is left alone - it only
    ADDS search paths and does not override the stdlib.

    The comparison is case-insensitive because Windows env var names are.
    """
    return {k: v for k, v in env.items() if k.lower() != "pythonhome"}


@functools.lru_cache(maxsize=1)
def _user_registry_items() -> tuple[tuple[str, str], ...]:
    """User-level env vars from HKCU\\Environment (Windows), read once per process."""
    import sys as _sys
    if _sys.platform != "win32":
        return ()
    try:
        import winreg
        reg_items: list[tuple[str, str]] = []
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, i)
                    reg_items.append((name, value))
                    i += 1
                except OSError:
                    break
        return tuple(reg_items)
    except Exception:
        return ()


def _get_env_with_user_vars() -> dict[str, str]:
    """On Windows, merge user-level env vars from registry into process env.

    Ensures vars set at user level (HKCU\\Environment) are available even if the
    parent process started before they were defined. The merge is
    case-insensitive (see _merge_user_env) so the registry never shadows an
    in-process PATH repair.

    Only the REGISTRY read is cached. The process env is re-read on every call:
    `Environment(action='worktree'|'venv')` mutates os.environ for "your next
    Bash calls", and a snapshot taken at the first Bash made that promise false.
    """
    from ...core.dossier_agent import courant, environ  # + variables du sous-agent (venv, worktree)
    env = _merge_user_env(environ(), list(_user_registry_items()))
    return worktree_child_env(strip_inherited_python_home(env), dossier=courant())


#  Compat : les tests (et d'anciens appelants) vidaient ce cache ; c'est désormais celui du
#  registre, seule partie encore mémorisée.
_get_env_with_user_vars.cache_clear = _user_registry_items.cache_clear  # type: ignore[attr-defined]


def _src_du_worktree_en_tete(env: dict[str, str], wt: str) -> dict[str, str]:
    """PYTHONPATH avec `<worktree>/src` EN TÊTE (le code testé est celui du worktree), sans doublon."""
    out = dict(env)
    src = os.path.join(wt, "src")
    if os.path.isfile(os.path.join(wt, "pyproject.toml")) and os.path.isdir(src):
        parts = [p for p in out.get("PYTHONPATH", "").split(os.pathsep) if p]
        if not parts or os.path.normcase(parts[0]) != os.path.normcase(src):
            parts = [src] + [p for p in parts if os.path.normcase(p) != os.path.normcase(src)]
        out["PYTHONPATH"] = os.pathsep.join(parts)
    return out


def _venv_propre_designe(env: dict[str, str], wt: str) -> str:
    """Le venv DU worktree que VIRTUAL_ENV désigne déjà (Environment(action='venv')), sinon ""."""
    from ....web_v2.runtime import venv_env
    courant = env.get("VIRTUAL_ENV", "")
    dedans = courant and venv_meme_projet._sous(courant, wt)
    return courant if dedans and venv_env.is_usable(courant) else ""


def worktree_child_env(env: dict[str, str], base_venv: str | None = None,
                       dossier: str = "") -> dict[str, str]:
    """Env des commandes d'un agent : le venv du PROJET où il travaille, et lui seul.

    Règle (2026-10-12, `venv_du_projet`) : le venv désigné est celui du projet Python qui
    contient le dossier courant de l'agent (`dossier`, sinon son worktree, sinon le cwd) —
    qu'il y soit arrivé par un spawn en worktree, LoadProjectConfig(cd=true) ou un simple cwd.
    Tout autre venv hérité (celui de bouzecode hors du projet bouzecode, celui d'un agent parent) est
    retiré de VIRTUAL_ENV / UV_PROJECT_ENVIRONMENT / PATH : uv le viserait, et le détruirait
    (le venv de bouzecode l'a été deux fois le 2026-10-12). Hors de tout projet : aucun venv.

    En plus, DANS un worktree d'agent (`BOUZECODE_WORKTREE_ROOT`, dossier courant dedans) :
      - PYTHONPATH : `<worktree>/src` EN TÊTE — constat sur 70 sessions : `python -m pytest`
        importait sinon le code du SERVEUR ;
      - le venv est celui du même projet dans le checkout principal, sauf venv DÉDIÉ du
        worktree (Environment(action='venv')) ;
      - UV_NO_SYNC=1 tant que le venv n'est pas celui du worktree : `uv run` l'utilise tel quel
        au lieu d'en synchroniser ou d'en créer un vide (« Failed to spawn: pytest »).

    UV_PROJECT_ENVIRONMENT n'est posé que sous la garde `venv_env.is_compatible`. Pur (env
    injecté) ; `base_venv` remplace la résolution, pour les tests."""
    wt = env.get("BOUZECODE_WORKTREE_ROOT", "")
    dans_wt = bool(wt) and os.path.isdir(wt) and (
        not dossier or venv_meme_projet._sous(dossier, wt))
    out = _src_du_worktree_en_tete(env, wt) if dans_wt else dict(env)
    ici = dossier or (wt if dans_wt else os.getcwd())
    venv = (_venv_propre_designe(out, wt) if dans_wt else "") or (
        venv_du_projet.venv_du_projet(ici) if base_venv is None else base_venv)
    out = venv_du_projet.designer(out, venv)
    if dans_wt and not (venv and venv_meme_projet._sous(venv, wt)):
        out["UV_NO_SYNC"] = "1"
    return out


@functools.lru_cache(maxsize=1)
def _powershell_exe() -> str:
    """Absolute path to powershell.exe, or bare 'powershell' as last resort.

    Invoking PowerShell by absolute path makes the Bash tool immune to a PATH
    that is missing the WindowsPowerShell directory — the failure mode that
    breaks every command with `'powershell' n'est pas reconnu`."""
    import shutil
    found = shutil.which("powershell") or shutil.which("pwsh")
    if found:
        return found
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    cand = os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    return cand if os.path.isfile(cand) else "powershell"
