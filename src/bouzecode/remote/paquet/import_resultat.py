"""Reimporte dans le depot local la branche produite sur la VM (bundle `<slug>.resultat.bundle`).

Le bundle a pour prerequis le SHA de depart, present localement : `git fetch` suffit. La branche
locale cible (`agent/<ticket>`) est creee ; on refuse d'ecraser une branche existante qui ne
serait pas un ancetre du resultat (pas de --force).
"""
import subprocess
from pathlib import Path


def _git(depot: Path, *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *arguments], cwd=depot, capture_output=True, text=True)


def importer_bundle_resultat(depot: Path, bundle: Path, branche_distante: str, branche_locale: str) -> dict:
    verification = _git(depot, "bundle", "verify", str(bundle))
    if verification.returncode != 0:
        return {"ok": False, "code": "bundle_invalide", "message": verification.stderr.strip()[-400:]}
    recuperation = _git(depot, "fetch", str(bundle), f"refs/heads/{branche_distante}:refs/heads/{branche_locale}")
    if recuperation.returncode != 0:
        return {"ok": False, "code": "import_refuse", "message": recuperation.stderr.strip()[-400:]}
    sha = _git(depot, "rev-parse", branche_locale).stdout.strip()
    return {"ok": True, "branche": branche_locale, "sha": sha}
