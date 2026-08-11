# [desc] English/French wording printed by the terminal UI itself (startup repairs, tool display). [/desc]
"""Messages printed by `ui/cli.py` and `ui/tool_display.py`, as (english, french).

ANSI codes and glyphs (⚠ ✓ ✗ →) stay at the CALL SITE, never in the table: a test
can then read a message without stripping escape sequences, and re-colouring a line
does not touch the translation.
"""
from __future__ import annotations

TERMINAL_MESSAGES: dict[str, tuple[str, str]] = {
    # --- ripgrep auto-install (cli.py) ---------------------------------------
    "ripgrep.missing": (
        "ripgrep (rg) not found — downloading from GitHub...",
        "ripgrep (rg) non trouvé — téléchargement depuis GitHub...",
    ),
    "ripgrep.downloading": (
        "  Downloading ripgrep {version}...",
        "  Téléchargement de ripgrep {version}...",
    ),
    "ripgrep.installed": (
        "ripgrep installed successfully.",
        "ripgrep installé avec succès.",
    ),
    "ripgrep.install_failed": (
        "Automatic ripgrep install failed: {error}",
        "Échec de l'installation automatique de ripgrep: {error}",
    ),
    "ripgrep.download_manually": (
        "  → Download manually: {url}",
        "  → Télécharger manuellement: {url}",
    ),
    # --- user PATH repair (cli.py) -------------------------------------------
    "path.too_long_for_setx": (
        "   User PATH too long for setx (>1024 chars) — "
        "add the directory by hand (Environment Variables).",
        "   PATH utilisateur trop long pour setx (>1024 car.) — "
        "ajoute le dossier manuellement (Variables d'environnement).",
    ),
    "path.persisted": (
        "   → added to the user PATH permanently (setx).",
        "   → ajouté au PATH utilisateur de façon permanente (setx).",
    ),
    "powershell.not_found": (
        "PowerShell not found (neither on PATH nor at the standard location). "
        "Shell commands will fail — install or restore PowerShell.",
        "PowerShell introuvable (ni dans le PATH ni à l'emplacement standard). "
        "Les commandes shell échoueront — installe/restaure PowerShell.",
    ),
    "powershell.added_to_path": (
        "PowerShell missing from PATH — added for this session ({directory}).",
        "PowerShell absent du PATH — ajouté pour cette session ({directory}).",
    ),
    # --- tool display (tool_display.py) --------------------------------------
    "tool.plan_heading": ("  Plan:", "  Plan :"),
}
