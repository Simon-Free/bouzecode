# [desc] Version de bouzecode d'une session : lecture de la version, branche, et historique des bascules de code (versions_successives) au fil des reprises. [/desc]
"""Quel code a fait tourner une session — et quand il a changé.

Le 2026-10-06, un export « malgré un pull » portait `bouzecode_version=3.5.102` et
`bouzecode_commit=d7b16027` (fusion locale absente d'origin) : la session JSON ne gardait que
la version du DERNIER run. Une conversation reprise après une mise à jour a pourtant tourné
sur plusieurs versions. `versions_successives` (champ additif de la session) les garde toutes,
avec le premier tour joué sous chacune."""
from __future__ import annotations

from pathlib import Path

from .code_version import REPO_ROOT, _git_dirs, _read

_PACKAGE_DIR = Path(__file__).resolve().parent


def _version_du_pyproject(dossier_paquet: Path) -> str | None:
    """[project].version du premier pyproject.toml au-dessus du paquet s'il est celui de
    bouzecode (mode dépôt / editable). Un pyproject illisible est journalisé, pas fatal."""
    import tomllib
    from .version_paquet import journal
    for dossier in (dossier_paquet, *dossier_paquet.parents):
        candidat = dossier / "pyproject.toml"
        if not candidat.is_file():
            continue
        try:
            with open(candidat, "rb") as f:
                projet = tomllib.load(f).get("project", {})
        except (OSError, tomllib.TOMLDecodeError) as erreur:
            journal.warning("pyproject %s illisible (%s) : repli sur le paquet installé",
                            candidat, erreur)
            return None
        if projet.get("name") == "bouzecode" and projet.get("version"):
            return projet["version"]
        return None
    return None


def lire_version_bouzecode(dossier_paquet: Path = _PACKAGE_DIR,
                      chemins: list[str] | None = None) -> str:
    """[project].version du pyproject.toml de bouzecode (dépôt), sinon métadonnées du
    paquet installé (Artifactory), sinon nom du dossier dist-info, sinon "unknown" —
    jamais d'exception : appelée au démarrage de chaque run (incident Focus du 2026-10-12,
    METADATA illisible juste après pip sur CIFS). Le pyproject d'un AUTRE projet qui
    contiendrait le venv n'est pas pris pour celui de bouzecode. `chemins` : sys.path par défaut."""
    from .version_paquet import journal, version_paquet
    version = _version_du_pyproject(dossier_paquet) or version_paquet("bouzecode", chemins=chemins)
    if version:
        return version
    journal.warning("version de bouzecode introuvable (ni pyproject, ni métadonnées, ni "
                    "dossier dist-info) : le run continue avec \"unknown\"")
    return "unknown"


def lire_branche(repo_root: str = REPO_ROOT) -> str:
    """Branche courante lue dans `.git/HEAD` (sans lancer git), "" si HEAD détaché ou
    pas de dépôt."""
    if not repo_root:
        return ""
    gitdir, _ = _git_dirs(repo_root)
    if gitdir is None:
        return ""
    head = _read(gitdir / "HEAD")
    prefixe = "ref: refs/heads/"
    return head[len(prefixe):] if head.startswith(prefixe) else ""


def _meme_code(a: dict, b: dict) -> bool:
    return all(a.get(cle) == b.get(cle) for cle in ("version", "commit", "boot_commit"))


def noter_version(state, *, version: str, commit: str, boot_commit: str) -> None:
    """Ajoute une entrée à `state.versions_successives` quand le code diffère de la
    précédente (premier run, ou reprise après une mise à jour). `tour` = premier tour joué
    sous ce code."""
    entree = {"tour": state.turn_count + 1, "version": version, "commit": commit,
              "boot_commit": boot_commit, "branche": lire_branche()}
    historique = state.versions_successives
    if historique and _meme_code(historique[-1], entree):
        return
    historique.append(entree)


def historique_de_session(data: dict) -> list:
    """Historique relu d'une session JSON. Une session antérieure au champ n'a que la
    version de son dernier run : elle devient une entrée de tour inconnu (None)."""
    if data.get("versions_successives"):
        return [dict(e) for e in data["versions_successives"]]
    version = data.get("bouzecode_version") or ""
    commit = data.get("bouzecode_commit") or ""
    if not (version or commit):
        return []
    return [{"tour": None, "version": version, "commit": commit,
             "boot_commit": data.get("bouzecode_boot_commit") or "", "branche": ""}]
