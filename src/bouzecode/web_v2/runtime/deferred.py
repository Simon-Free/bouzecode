# [desc] Persiste/charge/supprime `<session>.deferred.json` ({answer, checks}) pour drainer les checks différés. [/desc]
"""Persist/load/delete `.deferred.json` next to a web-agent session file.

Written when `DeferredChecks` is raised at FinalAnswer; read by the web runner
to drain the queued commands after the model is unloaded. On a failing check the
agent is respawned via `--resume-deferred`. Lives as `<session_path>.deferred.json`
and holds `{"answer": str, "checks": list[dict]}`.
"""
from __future__ import annotations

import json
from pathlib import Path


def deferred_path(session_path: str | Path) -> Path:
    return Path(str(session_path) + ".deferred.json")


def save(session_path: str | Path, exc) -> None:
    """Serialize a DeferredChecks to disk next to the session."""
    payload = {
        "answer": exc.answer,
        "checks": exc.checks,
    }
    deferred_path(session_path).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8",
    )


def load(session_path: str | Path) -> dict | None:
    path = deferred_path(session_path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def delete(session_path: str | Path) -> None:
    path = deferred_path(session_path)
    if path.exists():
        path.unlink()


def exists(session_path: str | Path) -> bool:
    return deferred_path(session_path).exists()


# --- Exécution et verdict (partagés par le drain du runner web et le TUI) -----------

def lancer_une(command: str, cwd: str, timeout: int):
    """Run a queued deferred command through the SAME shell wrapper as the Bash tool
    (`_build_popen_command` → PowerShell `-EncodedCommand` on Windows), NEVER cmd.exe.

    Deferred commands are authored as PowerShell (`$env:X = ...; ...`); running them via
    `shell=True` sent them to cmd.exe, which fails instantly on that syntax and never
    executed the check (e.g. the Azure deploy). `_strip_clixml` drops PowerShell's
    module-load progress envelope from stderr; the spilled temp .ps1 (large bodies) is
    removed in `finally`.

    Même environnement que l'outil Bash : sans `env=`, l'enfant héritait du PYTHONHOME
    que uv laisse fuir (stdlib 3.12) et un venv 3.13 mourait sur `SRE module mismatch`."""
    import contextlib
    import os
    import subprocess
    from ...backend.tools.ops.bash_bg import marquer_env
    from ...backend.tools.ops.shell_env import _get_env_with_user_vars
    from ...backend.tools.ops.shell_search import _build_popen_command, _strip_clixml
    popen_cmd, shell, temp_path = _build_popen_command(command)
    try:
        result = subprocess.run(
            popen_cmd, shell=shell, cwd=cwd or None, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
            env=marquer_env(_get_env_with_user_vars()),
        )
        result.stderr = _strip_clixml(result.stderr or "")
        return result
    finally:
        if temp_path:
            with contextlib.suppress(OSError):
                os.remove(temp_path)


_LIGNES_D_EXTRAIT = 6


def _extrait(sortie: str) -> str:
    """La FIN de la sortie : c'est là qu'une suite de tests donne son verdict."""
    lignes = [ligne for ligne in (sortie or "").strip().splitlines() if ligne.strip()]
    return "\n".join(lignes[-_LIGNES_D_EXTRAIT:])


def executer(checks: list[dict], cwd: str, lancer=None, journal=None) -> dict:
    """Lance les vérifications dans l'ordre, s'arrête à la première rouge, rend le verdict.

    `{"statut": "vert"|"rouge"|"delai", "checks": [{command, code, extrait}], "echec":
    {command, stdout, stderr, code | timeout}}` — `echec` absent quand tout est vert.
    `journal(texte)` reçoit la sortie brute au fil de l'eau (stdout de l'agent côté web)."""
    import subprocess
    lancer = lancer or lancer_une
    ecrire = journal or (lambda _texte: None)
    faits: list[dict] = []
    for check in checks:
        command = check["command"]
        timeout = check.get("timeout") or 600
        ecrire(f"$ {command}\n")
        try:
            result = lancer(command, cwd, timeout)
        except subprocess.TimeoutExpired:
            ecrire("deferred check TIMED OUT\n")
            faits.append({"command": command, "code": None,
                          "extrait": f"délai de {timeout}s dépassé"})
            return {"statut": "delai", "checks": faits,
                    "echec": {"command": command, "timeout": timeout}}
        ecrire(result.stdout or "")
        ecrire(result.stderr or "")
        sortie = f"{result.stdout or ''}\n{result.stderr or ''}"
        faits.append({"command": command, "code": result.returncode,
                      "extrait": _extrait(sortie)})
        if result.returncode != 0:
            return {"statut": "rouge", "checks": faits,
                    "echec": {"command": command, "code": result.returncode,
                              "stdout": result.stdout or "", "stderr": result.stderr or ""}}
    return {"statut": "vert", "checks": faits}


def texte_du_verdict(verdict: dict, apres_echec: str = "") -> str:
    """Le paragraphe qui remplace « vérification non faite » dans la réponse livrée."""
    if verdict.get("statut") == "vert":
        tete = "✅ Vérification différée FAITE après la clôture : verte."
    else:
        tete = ("❌ Vérification différée faite après la clôture : ÉCHEC — ce que la réponse "
                "ci-dessus affirme n'est PAS confirmé." + (f" {apres_echec}" if apres_echec else ""))
    lignes = [tete]
    for fait in verdict.get("checks") or []:
        code = fait.get("code")
        issue = "délai dépassé" if code is None else f"code {code}"
        lignes.append(f"- `{fait.get('command', '')}` → {issue}")
        if fait.get("extrait"):
            lignes.extend("    " + ligne for ligne in fait["extrait"].splitlines())
    return "\n".join(lignes)


def consigner(session_path: str | Path, verdict: dict, apres_echec: str = "") -> None:
    """Porte le verdict dans la session : champ `deferred_result`, et à la place de l'avis
    « non faite » dans `final_answer` ET dans le résultat FinalAnswer de la conversation —
    tout ce qui lit le rapport (Bureau, ticket, vue de session) voit donc le verdict."""
    import os
    from ...backend.tools.interaction import remplacer_annonce
    path = Path(str(session_path))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    texte = texte_du_verdict(verdict, apres_echec)
    data["deferred_result"] = verdict
    if isinstance(data.get("final_answer"), str) and data["final_answer"]:
        data["final_answer"] = remplacer_annonce(data["final_answer"], texte)
    for message in reversed(data.get("messages") or []):
        if message.get("role") == "tool" and message.get("name") == "FinalAnswer":
            if isinstance(message.get("content"), str):
                message["content"] = remplacer_annonce(message["content"], texte)
            break
    tmp = path.with_name(path.name + ".verdict.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
