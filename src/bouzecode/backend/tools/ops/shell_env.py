# [desc] Environment the Bash tool runs commands in: user-level env vars merged case-insensitively, and the absolute path to powershell.exe. [/desc]
"""Where and with what a shell command runs.

Split out of shell_search.py (file-size rule); both helpers stay importable from
shell_search, which is how the rest of the codebase addresses them."""
import functools
import os


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


@functools.lru_cache(maxsize=1)
def _get_env_with_user_vars() -> dict[str, str]:
    """On Windows, merge user-level env vars from registry into process env.

    Ensures vars set at user level (HKCU\\Environment) are available even if the
    parent process started before they were defined. The merge is
    case-insensitive (see _merge_user_env) so the registry never shadows an
    in-process PATH repair.
    """
    env = os.environ.copy()
    try:
        import sys as _sys
        if _sys.platform != "win32":
            return env
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
        env = _merge_user_env(env, reg_items)
    except Exception:
        pass
    return env


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
