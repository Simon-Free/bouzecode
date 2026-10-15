# [desc] Garde du Bash : pytest lancé par le shell (pytest, py.test, python -m pytest, uv run …) est refusé avec l'appel RunPythonTest équivalent ; `# allow-raw-pytest: <raison>` laisse passer. [/desc]
"""pytest passe par RunPythonTest, pas par le Bash.

Mesuré le 2026-10-13 (tutoriel DEMOAPP) : 307 pytest lancés par le Bash contre 13 par
RunPythonTest. Les briefs prescrivaient `$env:PYTHONPATH=…; python -m pytest …`, les
sous-agents recopiaient ; la suite finale, filtrée par `| Select-Object -Last 40`, a laissé
l'agent aveugle 50 minutes, sans regroupement des 144 erreurs d'environnement identiques ni
comparaison avec develop. RunPythonTest fait déjà tout cela, PYTHONPATH du worktree compris.

Seule la position de COMMANDE compte : `grep pytest`, `pip show pytest-xdist` ou un message
de commit qui parle de pytest passent.
"""
from __future__ import annotations

import re

_ECHAPPATOIRE_RE = re.compile(r"#\s*allow-raw-pytest:\s*\S")
_PYTHON_RE = re.compile(r"^(?:python[\d.]*|pythonw|py)$")
_LANCEURS = {"uv", "poetry", "pipenv", "hatch", "pdm"}
_OPTIONS_LANCEUR_A_VALEUR = {"--directory", "--with", "--project", "--python", "-p", "--extra",
                             "--group", "--env-file", "--package"}
_OPTIONS_PYTEST_A_VALEUR = {"-k", "-m", "-n", "-p", "-o", "-c", "-W", "--rootdir", "--basetemp",
                            "--maxfail", "--tb", "--deselect", "--ignore", "--junitxml",
                            "--timeout", "--reruns", "--numprocesses", "--confcutdir",
                            "--log-level", "--cov", "--durations"}


def _segments(command: str) -> list[str]:
    """Commandes élémentaires, coupées sur `;`, `&&`, `||`, `|` et fin de ligne hors guillemets."""
    morceaux, courant, guillemet, i = [], [], "", 0
    while i < len(command):
        c = command[i]
        if guillemet:
            guillemet = "" if c == guillemet else guillemet
        elif c in "\"'":
            guillemet = c
        elif c == "#" and (i == 0 or command[i - 1].isspace()):
            fin = command.find("\n", i)
            i = len(command) if fin < 0 else fin
            continue
        elif c in ";|\n" or command.startswith("&&", i):
            morceaux.append("".join(courant))
            courant = []
            i += 2 if command.startswith(("&&", "||"), i) else 1
            continue
        courant.append(c)
        i += 1
    morceaux.append("".join(courant))
    return [m.strip() for m in morceaux if m.strip()]


def _jetons(segment: str) -> list[str]:
    jetons = re.findall(r'"[^"]*"|\'[^\']*\'|\S+', segment)
    return [j[1:-1] if len(j) > 1 and j[0] == j[-1] and j[0] in "\"'" else j for j in jetons]


def _sans_prefixe(jetons: list[str]) -> list[str]:
    """Retire `&`, les affectations `X=…`, `env` et `uv run [options]` devant la commande."""
    while jetons:
        tete = jetons[0]
        if tete in ("&", "env") or re.match(r"^[A-Za-z_]\w*=", tete):
            jetons = jetons[1:]
        elif tete.lower() in _LANCEURS and len(jetons) > 1 and jetons[1] == "run":
            jetons = jetons[2:]
            while jetons and jetons[0].startswith("-"):
                jetons = jetons[2:] if jetons[0] in _OPTIONS_LANCEUR_A_VALEUR else jetons[1:]
        else:
            return jetons
    return jetons


def arguments_pytest(segment: str) -> list[str] | None:
    """Arguments passés à pytest si ce segment LANCE pytest, sinon None."""
    jetons = _sans_prefixe(_jetons(segment))
    if not jetons:
        return None
    nom = re.split(r"[\\/]", jetons[0])[-1].lower().removesuffix(".exe")
    if nom in ("pytest", "py.test"):
        return jetons[1:]
    if _PYTHON_RE.match(nom) or jetons[0].startswith("$"):
        for i, jeton in enumerate(jetons[1:-1], start=1):
            if jeton == "-m":
                return jetons[i + 2:] if jetons[i + 1] == "pytest" else None
    return None


#  Redirection du shell (bash comme PowerShell) : `>`, `>>`, `2>`, `*>`, `2>&1`, `<`, collée ou
#  non à son fichier. Session de4d1304 (2026-10-14) : `*> $env:TEMP\x.txt` devenait deux cibles.
_REDIRECTION_RE = re.compile(r"^(?:[\d*]?>>?|<)(?P<suite>.*)$")


def sans_redirections(arguments: list[str]) -> list[str]:
    """Les arguments sans les redirections ni leurs fichiers (`2>&1` n'a pas d'opérande)."""
    gardes, operande_attendu = [], False
    for argument in arguments:
        if operande_attendu:
            operande_attendu = False
            continue
        redirection = _REDIRECTION_RE.match(argument)
        if redirection:
            operande_attendu = not redirection["suite"]
            continue
        gardes.append(argument)
    return gardes


def appel_equivalent(arguments: list[str]) -> str:
    """`RunPythonTest(targets=[…], keyword=…, marker=…)` pour ces arguments pytest."""
    cibles, filtres, attendu = [], {}, ""
    for argument in sans_redirections(arguments):
        if attendu:
            if attendu in ("-k", "-m"):
                filtres["keyword" if attendu == "-k" else "marker"] = argument
            attendu = ""
        elif argument in _OPTIONS_PYTEST_A_VALEUR:
            attendu = argument
        elif not argument.startswith("-"):
            cibles.append(argument)
    parametres = [f"targets={cibles!r}"] if cibles else []
    parametres += [f"{cle}={valeur!r}" for cle, valeur in sorted(filtres.items())]
    return f"RunPythonTest({', '.join(parametres)})"


def refus_pytest_shell(command: str) -> str:
    """Message de refus si la commande lance pytest sans échappatoire, sinon ''."""
    if _ECHAPPATOIRE_RE.search(command):
        return ""
    for segment in _segments(command):
        arguments = arguments_pytest(segment)
        if arguments is not None:
            appel = appel_equivalent(arguments)
            sans_cible = (" Sans `targets`, il lance les tests impactés par les changements "
                          "de la branche." if appel == "RunPythonTest()" else "")
            return (
                f"Refusé : pytest se lance par RunPythonTest, pas par le shell. Équivalent : "
                f"{appel}.{sans_cible} Il met déjà le `src` du worktree en tête de PYTHONPATH, "
                f"plafonne à -n 4, sauve la sortie complète, regroupe les erreurs répétées et, "
                f"sur les tests impactés, sépare les échecs NOUVEAUX de ceux déjà présents sur develop. "
                f"Besoin réel du shell (ex. options qu'il ne porte pas) : ajoute "
                f"`# allow-raw-pytest: <raison>` à la commande."
            )
    return ""
