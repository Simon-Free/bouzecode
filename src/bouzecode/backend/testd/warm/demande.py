# [desc] testd : navigateur chaud à la demande pour tout job (le plugin `_bz_pw_patch` le réclame au démon au premier lancement), et classement « navigateur » appris des tests qu'il a servis [/desc]
"""Le navigateur chaud ne dépend plus du classement de la collecte : chaque sous-run reçoit
l'URL du démon qui le démarre au premier `chromium.launch()` (cf. plugin `_bz_pw_patch`). Un
job sans Playwright ne coûte rien ; un job qui en a ne démarre le navigateur que s'il en lance
un. Les tests servis ainsi désignent leurs fichiers comme « navigateur » : le job suivant passe
par les créneaux, les contextes et l'estimation navigateur."""
from __future__ import annotations

from pathlib import Path

from ..budget.classes import memoriser


def env_navigateur(job, ressources) -> dict:
    """Variables lues par le plugin `_bz_pw_patch` dans les process pytest du job."""
    env = {"BZ_PW_NOTES": str(job.dossier / "pw_notes.txt"),
           "BZ_PW_CONNECTS": str(job.dossier / "pw_connects.txt")}
    demande = getattr(ressources, "demande", None)
    if demande:
        url, jeton = demande
        env.update(BZ_PW_DEMANDE=f"{url}/jobs/{job.id}/navigateur", BZ_PW_JETON=jeton)
    return env


def apprendre(job, historique: Path) -> None:
    """Fichiers dont un test a été servi par le navigateur chaud : classés « navigateur »."""
    fichier = job.dossier / "pw_connects.txt"
    if not fichier.exists():
        return
    nodeids = sorted(set(fichier.read_text(encoding="utf-8").splitlines()) - {""})
    memoriser(historique, job.cwd, {"browser": nodeids}, filtre=True)
