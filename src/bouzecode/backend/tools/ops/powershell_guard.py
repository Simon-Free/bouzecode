# [desc] Garde-fous du Bash sous Windows (PowerShell) : heredoc bash, message de commit interpolé, argument vide, préambule UTF-8/sans progression, décodage OEM. [/desc]
"""Ce que PowerShell fait en silence aux commandes écrites « comme en bash ».

Relevés sur 70 sessions réelles du poste Windows (PowerShell 5.1) :
  - un heredoc bash (`git commit -F - <<'MSG'`) : erreur d'analyse, RIEN n'est exécuté ;
  - `git commit -m "... $batch ..."` : `$batch` devient une chaîne vide, et le Markdown
    `` `teams` `` devient TABULATION + « eams » — le message committé est faux, sans erreur ;
  - `-m ""` vers un programme externe : PS 5.1 supprime l'argument vide, l'option avale
    l'argument suivant ;
  - « Au caract�re » : la sortie est dans la page de code OEM (cp850), décodée en UTF-8 ;
  - les barres de progression (`Invoke-WebRequest`) ralentissent et polluent la sortie ;
  - `Get-Content` lit un fichier UTF-8 sans BOM comme de l'ANSI : accents cassés.

Les deux premiers sont REFUSÉS avant exécution (le premier échouerait de toute façon, le second
corromprait l'historique) ; l'argument vide est SIGNALÉ ; le reste est corrigé d'office par un
préambule et un décodage de repli.
"""
from __future__ import annotations

import re
import sys

# `try` : sans console attachée, affecter [Console]::OutputEncoding peut lever (« handle non
# valide ») — la commande de l'agent doit tourner quand même. UTF8Encoding($false) : sans BOM,
# sinon .NET en écrit un en tête de la sortie redirigée.
PREAMBULE_POWERSHELL = (
    "$ProgressPreference='SilentlyContinue'; "
    "try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false } catch {}; "
    "$OutputEncoding = New-Object System.Text.UTF8Encoding $false; "
    "$PSDefaultParameterValues['Get-Content:Encoding']='UTF8'; "
    "$PSDefaultParameterValues['Select-String:Encoding']='UTF8'\n"
)

# `using`, `param(` et `#requires` doivent ouvrir le script : rien ne peut les précéder.
_TETE_OBLIGATOIRE_RE = re.compile(r"\s*(?:using\s|param\s*\(|#requires)", re.IGNORECASE)


def avec_preambule(command: str) -> str:
    """La commande précédée du préambule, sauf si elle doit ouvrir le script elle-même."""
    if _TETE_OBLIGATOIRE_RE.match(command):
        return command
    return PREAMBULE_POWERSHELL + command


_HEREDOC_RE = re.compile(r"(?m)(?<![<@\w])<<-?\s*(['\"]?)([A-Za-z_]\w*)\1\s*$")
_COMMIT_RE = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?(?:commit|tag)\b")
_MESSAGE_RE = re.compile(r"(?:-m|--message)(?:\s+|=)\"((?:[^\"`]|`.|\"\")*)\"", re.DOTALL)
_VAR_RE = re.compile(r"\$(?!\()([A-Za-z_]\w*(?::\w+)?)")
_ECHAPPEMENT_RE = re.compile(r"`[0abefnrtuv]")
_ARG_VIDE_RE = re.compile(r"(?<!\S)(-{1,2}[A-Za-z][\w-]*)\s+(\"\"|'')(?=\s|$|;|\|)")
_CMDLET_RE = re.compile(r"^[A-Za-z]+-[A-Za-z]+$")

_RECETTE_MESSAGE = (
    "Écris le message avec Write(temp=True) (UTF-8 sans BOM) puis `git commit -F <chemin>`, "
    "ou utilise des guillemets SIMPLES (littéraux), ou un here-string `@'` … `'@` "
    "(délimiteurs seuls sur leur ligne) passé à `git commit -F -`."
)


def _refus_heredoc(command: str) -> str:
    m = _HEREDOC_RE.search(command)
    if not m:
        return ""
    return (f"Refusé avant exécution : `{m.group(0).strip()}` est un heredoc BASH. Le Bash "
            f"exécute PowerShell ici, qui ne le connaît pas (« L'opérateur < est réservé ») et "
            f"n'exécute alors RIEN du script. Pour un message de commit : {_RECETTE_MESSAGE} "
            f"Pour un script : Write(temp=True) puis lance le fichier.")


def _refus_message_interpole(command: str) -> str:
    if not _COMMIT_RE.search(command):
        return ""
    assignees = set(re.findall(r"\$([A-Za-z_]\w*)\s*=", command))
    problemes: list[str] = []
    for m in _MESSAGE_RE.finditer(command):
        texte = m.group(1)
        for var in _VAR_RE.findall(texte):
            if var.split(":")[0] not in assignees and f"${var}" not in problemes:
                problemes.append(f"${var}")
        for esc in _ECHAPPEMENT_RE.findall(texte):
            if esc not in problemes:
                problemes.append(esc)
    if not problemes:
        return ""
    liste = ", ".join(f"`{p}`" for p in problemes)
    return (f"Refusé avant exécution : dans ce message de commit entre guillemets DOUBLES, "
            f"PowerShell remplacerait {liste} (variable → chaîne vide, accent grave + lettre → "
            f"caractère de contrôle, ex. `` `t `` = tabulation) et le commit porterait un message "
            f"faux, sans aucune erreur. {_RECETTE_MESSAGE}")


def _note_argument_vide(command: str) -> str:
    notes: list[str] = []
    for segment in re.split(r"[;\n|]", command):
        mots = segment.split()
        if not mots or _CMDLET_RE.match(mots[0]):
            continue
        for m in _ARG_VIDE_RE.finditer(segment):
            notes.append(f"{m.group(1)} {m.group(2)}")
    if not notes:
        return ""
    return (f"⚠️ {', '.join(notes)} : PowerShell 5.1 SUPPRIME un argument vide passé à un "
            f"programme externe — l'option avale l'argument suivant. Retire l'option, ou passe "
            f"une valeur non vide.\n")


def diagnostic_powershell(command: str) -> tuple[str, str]:
    """(refus, note) pour une commande destinée à PowerShell ; ("", "") si rien à redire."""
    refus = _refus_heredoc(command) or _refus_message_interpole(command)
    if refus:
        return refus, ""
    return "", _note_argument_vide(command)


def decoder_sortie(data: bytes, windows: bool = True) -> str:
    """UTF-8 d'abord ; sous Windows, repli sur la page de code OEM (cp850 en français).

    Le préambule force UTF-8, mais une erreur d'ANALYSE survient avant qu'il ne s'exécute :
    ces messages-là arrivent en OEM (« Au caract�re Ligne:7 » une fois décodés en UTF-8)."""
    if not data:
        return ""
    try:
        return data.decode("utf-8").removeprefix("\ufeff")
    except UnicodeDecodeError:
        if windows:
            # `oem` n'existe que sous Windows (ailleurs le module lève à l'import).
            for enc in (("oem",) if sys.platform == "win32" else ()) + ("cp850",):
                try:
                    return data.decode(enc)
                except Exception:  # noqa: BLE001 — codec absent ou octets invalides
                    continue
        return data.decode("utf-8", "replace")
