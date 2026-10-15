# [desc] En-tête Markdown « quel bouzecode a tourné » des exports : version, commits, branche, provenance (arbre modifié / commit absent d'origin / paquet), modèle, session, bascules. [/desc]
"""En-tête de version des exports de conversation.

La provenance est constatée À L'EXPORT, sans réseau : `git status` (fichiers suivis modifiés)
et `git branch -r --contains` contre les refs origin déjà présentes localement — un commit de
fusion locale (cas d7b16027 du 2026-10-06) n'y figure pas. Hors dépôt git, bouzecode a été
installé depuis un paquet (Artifactory)."""
from __future__ import annotations

import subprocess
from datetime import datetime

from .code_version import BOOT, REPO_ROOT, read_head_sha


def _git(args: list[str], repo_root: str) -> str | None:
    """Sortie de `git <args>`, None si git est absent ou échoue (sha inconnu…)."""
    try:
        fini = subprocess.run(["git", *args], cwd=repo_root, capture_output=True,
                              text=True, timeout=15)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return fini.stdout if fini.returncode == 0 else None


def provenance_du_code(repo_root: str, boot_sha: str) -> str:
    if not repo_root:
        return "installé depuis un paquet (pas de dépôt git : Artifactory)"
    constats = []
    statut = _git(["status", "--porcelain", "--untracked-files=no"], repo_root)
    if statut is None:
        constats.append("état du dépôt illisible (git indisponible)")
    elif statut.strip():
        constats.append("arbre local modifié (fichiers suivis, constaté à l'export)")
    if boot_sha:
        distantes = _git(["branch", "-r", "--contains", boot_sha], repo_root)
        if distantes is not None and not distantes.strip():
            constats.append(f"commit {boot_sha[:8]} absent des branches origin connues "
                            f"localement (commit ou fusion locale)")
        if read_head_sha(repo_root) not in ("", boot_sha):
            constats.append("HEAD a bougé depuis le démarrage du process")
    return " ; ".join(constats) or "commit présent sur origin, arbre propre"


def _ligne_version(entree: dict) -> str:
    tour = entree.get("tour")
    debut = f"à partir du tour {tour}" if tour else "tour inconnu (session antérieure)"
    boot = entree.get("boot_commit") or ""
    morceaux = [f"{debut} : **{entree.get('version') or '?'}**",
                f"commit `{entree.get('commit') or '?'}`"]
    if boot:
        morceaux.append(f"démarrage `{boot[:8]}` (`{boot}`)")
    if entree.get("branche"):
        morceaux.append(f"branche `{entree['branche']}`")
    return "- " + " · ".join(morceaux)


def entete_markdown(state, config: dict, maintenant: datetime | None = None) -> str:
    """Bloc Markdown à placer en tête d'un export de la conversation `state`."""
    historique = list(getattr(state, "versions_successives", []) or [])
    if not historique:
        historique = [{"tour": None, "version": getattr(state, "bouzecode_version", ""),
                       "commit": getattr(state, "bouzecode_commit", ""),
                       "boot_commit": getattr(state, "bouzecode_boot_commit", "")}]
    boot = historique[-1].get("boot_commit") or BOOT.boot_sha
    quand = (maintenant or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    lignes = [
        "# Export de conversation bouzecode", "",
        f"- **bouzecode** {historique[-1].get('version') or '?'} · commit de démarrage "
        f"`{boot[:8] or '?'}` (`{boot or '?'}`)",
        f"- Provenance : {provenance_du_code(REPO_ROOT, boot)}",
        f"- Modèle : `{config.get('model') or '?'}` · session : "
        f"`{config.get('_session_id') or '?'}` · exporté le {quand}",
        f"- Code exécuté ({len(historique)} version(s) successive(s)) :",
        *("  " + _ligne_version(e) for e in historique),
        "", "---", "",
    ]
    return "\n".join(lignes)


def ligne_exporteur() -> str:
    """Une ligne : quel bouzecode a produit ce rapport (pour les exports sans session)."""
    from .version_session import lire_branche, lire_version_bouzecode
    branche = lire_branche()
    return (f"_exporté par bouzecode {lire_version_bouzecode()} · commit de démarrage "
            f"`{BOOT.boot_sha[:8] or '?'}`" + (f" · branche `{branche}`" if branche else "")
            + "_")
