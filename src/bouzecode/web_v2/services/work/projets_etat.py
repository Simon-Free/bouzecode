# [desc] Etat git des projets enregistres et tri de leurs fichiers NON SUIVIS a transmettre a un agent (local ou rundeck). [/desc]
"""Ce que l'assistant doit savoir d'un projet pour y lancer une tache, sans lire de code.

* `lister()` : les projets enregistres (slug, chemin, description, branche, dernier commit,
  presence d'un `.venv`).
* `fichiers(slug, indices)` : l'etat git (branche, HEAD, commits non pousses, modifications
  non commitees) et les fichiers NON SUIVIS avec leur taille. Un agent lance ailleurs
  (worktree, rundeck) part de l'etat COMMITE : un fichier non suivi dont il a besoin doit
  lui etre transmis explicitement. On marque donc ceux qui semblent pertinents (indices de
  la tache retrouves dans le chemin), on exclut les binaires, les gros fichiers et les
  `temp_*`, et on signale les secrets (`.env*`, cles) sans JAMAIS les proposer.

Lecture seule : uniquement `git status`, `git log`, `git ls-files`, `git rev-parse`.
"""
from __future__ import annotations

import subprocess
import unicodedata
from pathlib import Path

from . import projects

TAILLE_MAX = 1_000_000
NON_SUIVIS_MAX = 300
EXTENSIONS_BINAIRES = {".exe", ".dll", ".pyd", ".so", ".zip", ".gz", ".7z", ".tar", ".whl",
                       ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".pptx", ".docx", ".xlsx",
                       ".parquet", ".pkl", ".db", ".sqlite", ".abf", ".pbix", ".bin", ".pyc"}
MOTIFS_SECRETS = (".env", "id_rsa", "id_ed25519", "credentials", "secret")
EXTENSIONS_SECRETS = {".pem", ".key", ".pfx", ".p12"}


def _git(chemin: str, *args: str) -> tuple[int, str]:
    resultat = subprocess.run(["git", "-C", chemin, *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=30)
    return resultat.returncode, resultat.stdout.rstrip()


def _sans_accents(texte: str) -> str:
    decompose = unicodedata.normalize("NFKD", str(texte or ""))
    return "".join(c for c in decompose if not unicodedata.combining(c)).casefold()


def _dernier_commit(chemin: str) -> dict:
    code, sortie = _git(chemin, "log", "-1", "--format=%h%x1f%s%x1f%cI")
    if code != 0 or not sortie:
        return {}
    sha, titre, date = (sortie.split("\x1f") + ["", "", ""])[:3]
    return {"sha": sha, "titre": titre, "date": date}


def _resume_projet(projet: dict) -> dict:
    chemin = str(projet.get("path") or "")
    vue = {"slug": projet.get("slug", ""), "chemin": chemin,
           "description": projet.get("description", ""),
           "existe": bool(chemin) and Path(chemin).is_dir()}
    if not vue["existe"]:
        return vue
    code, branche = _git(chemin, "rev-parse", "--abbrev-ref", "HEAD")
    vue.update({"git": code == 0, "branche": branche if code == 0 else "",
                "dernier_commit": _dernier_commit(chemin) if code == 0 else {},
                "venv": (Path(chemin) / ".venv").is_dir()})
    return vue


def lister() -> list[dict]:
    return [_resume_projet(projet) for projet in projects.list_projects()]


def _commits_non_pousses(chemin: str) -> dict:
    code, amont = _git(chemin, "rev-parse", "--abbrev-ref", "@{u}")
    if code != 0:
        return {"amont": "", "commits": [], "note": "pas de branche amont : rien n'est pousse"}
    _, journal = _git(chemin, "log", "@{u}..HEAD", "--format=%h %s", "-30")
    return {"amont": amont, "commits": [l for l in journal.splitlines() if l.strip()]}


def _est_secret(relatif: str) -> bool:
    nom = Path(relatif).name.casefold()
    return Path(nom).suffix in EXTENSIONS_SECRETS or any(nom.startswith(m) or m in nom
                                                         for m in MOTIFS_SECRETS)


def _est_binaire(fichier: Path) -> bool:
    if fichier.suffix.casefold() in EXTENSIONS_BINAIRES:
        return True
    with fichier.open("rb") as flux:
        return b"\x00" in flux.read(2048)


def _exclusion(relatif: str, fichier: Path, taille: int) -> str:
    """Pourquoi ce fichier ne doit PAS partir par defaut ("" = transmissible)."""
    if _est_secret(relatif):
        return "secret"
    if Path(relatif).name.casefold().startswith("temp_"):
        return "temporaire"
    if taille > TAILLE_MAX:
        return "trop_gros"
    if _est_binaire(fichier):
        return "binaire"
    return ""


def _fiche(racine: Path, relatif: str, termes: list[str]) -> dict:
    fichier = racine / relatif
    taille = fichier.stat().st_size if fichier.is_file() else 0
    exclu = _exclusion(relatif, fichier, taille) if fichier.is_file() else "illisible"
    chemin_normalise = _sans_accents(relatif)
    touche = [t for t in termes if t in chemin_normalise]
    fiche = {"chemin": relatif, "taille": taille,
             "pertinent": not exclu and (bool(touche) if termes else True)}
    if exclu:
        fiche["exclu"] = exclu
    if touche:
        fiche["indices"] = touche
    return fiche


def _termes(indices) -> list[str]:
    brut = indices if isinstance(indices, (list, tuple)) else str(indices or "").split()
    return [_sans_accents(t).strip() for t in brut if str(t).strip()]


def fichiers(slug: str, indices=None) -> dict:
    """Etat git + fichiers non suivis tries d'un projet enregistre."""
    projet = projects.find(str(slug or "").strip())
    if projet is None:
        return {"ok": False, "erreur": "projet_inconnu", "slug": slug,
                "connus": [p.get("slug") for p in projects.list_projects()]}
    chemin = str(projet.get("path") or "")
    code, head = _git(chemin, "rev-parse", "--short", "HEAD") if Path(chemin).is_dir() else (1, "")
    if code != 0:
        return {"ok": False, "erreur": "pas_un_depot_git", "slug": slug, "chemin": chemin}
    _, branche = _git(chemin, "rev-parse", "--abbrev-ref", "HEAD")
    _, modifies = _git(chemin, "status", "--porcelain", "--untracked-files=no")
    _, non_suivis = _git(chemin, "ls-files", "--others", "--exclude-standard")
    termes = _termes(indices)
    liste = [l for l in non_suivis.splitlines() if l.strip()]
    fiches = [_fiche(Path(chemin), relatif, termes) for relatif in liste[:NON_SUIVIS_MAX]]
    return {"ok": True, "slug": projet.get("slug"), "chemin": chemin,
            "git": {"branche": branche, "head": head, **_commits_non_pousses(chemin),
                    "modifications_non_commitees": [l for l in modifies.splitlines() if l]},
            "non_suivis": fiches, "non_suivis_total": len(liste),
            "tronque": len(liste) > NON_SUIVIS_MAX,
            "proposes": [f["chemin"] for f in fiches if f["pertinent"]],
            "secrets_signales": [f["chemin"] for f in fiches if f.get("exclu") == "secret"]}
