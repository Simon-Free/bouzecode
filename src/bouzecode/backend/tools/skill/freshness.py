# [desc] Mesure la dérive d'une skill depuis sa dernière vérification, et rend le bandeau affiché à son ouverture. [/desc]
"""Une skill est une piste datée, pas une vérité.

Rien ne disait à un agent qu'une skill pouvait être fausse : ni le prompt, ni
l'outil. Elle était donc avalée comme parole d'évangile — pire que pas de skill,
puisqu'elle le détourne d'aller lire le vrai code.

La dérive se mesure : `updated:` dit quand un humain (ou un agent) a confirmé le
contenu, `covers:` dit quels chemins la skill décrit. Le nombre de commits qui
ont touché ces chemins depuis cette date est une mesure honnête de ce qu'on
risque en s'y fiant.

On ne crie pas au loup : sans dérive, aucun bandeau n'est affiché. C'est la même
mécanique que le `[stale — …]` des cartes `SYMBOLS.md`, qui a fait ses preuves.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ATTENTION_THRESHOLD = 1
PISTE_THRESHOLD = 10


def _repo_of(path: Path) -> Path | None:
    """Le dépôt qui contient ce chemin, ou None s'il n'y en a pas."""
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def commits_since(repo: Path, since: str, paths: list[str]) -> int:
    """Nombre de commits touchant `paths` depuis `since`. -1 si non mesurable."""
    completed = subprocess.run(
        ["git", "log", "--oneline", f"--since={since}", "--", *paths],
        cwd=str(repo), capture_output=True, text=True, timeout=10,
    )
    if completed.returncode != 0:
        return -1
    return len([line for line in completed.stdout.splitlines() if line.strip()])


def drift(skill) -> int:
    """Commits ayant touché les chemins couverts depuis la dernière vérification.

    -1 quand la question n'a pas de sens ici : pas de date, pas de chemins
    couverts, ou fichier hors dépôt.
    """
    if not skill.updated or not skill.covers:
        return -1
    skill_path = Path(skill.file_path)
    repo = _repo_of(skill_path)
    if repo is None:
        return -1
    existing = [c for c in skill.covers if (repo / c).exists()]
    if not existing:
        return -1
    return commits_since(repo, skill.updated, existing)


def banner(skill) -> str:
    """Le bandeau à préfixer au contenu de la skill. Vide si rien à signaler."""
    count = drift(skill)
    if count < ATTENTION_THRESHOLD:
        return ""
    corrige = (f"Si tu constates un écart, CORRIGE la skill dans ce même tour "
               f"(Edit sur {skill.file_path}, et remets `updated:` à aujourd'hui).")
    if count >= PISTE_THRESHOLD:
        return (f"[FRAÎCHEUR — vérifiée le {skill.updated}. Depuis, {count} commits ont touché "
                f"les chemins qu'elle décrit. Traite son contenu comme une PISTE, pas comme "
                f"une vérité : vérifie par Read avant de t'appuyer dessus. {corrige}]\n\n")
    return (f"[FRAÎCHEUR — vérifiée le {skill.updated}. Depuis, {count} commit(s) ont touché "
            f"les chemins qu'elle décrit : vérifie ce sur quoi tu t'appuies. {corrige}]\n\n")
