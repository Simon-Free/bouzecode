"""Cote VM (stdlib seule) : environnement de la commande (uv, TMPDIR/HOME jetables, CA systeme,
variables LLM, jamais le jeton GitLab) et preparation du navigateur Playwright."""
import json
import os
import subprocess
import sys
from pathlib import Path

UV = "/data/datainno/uv/uv"
CACHE_UV = "/data/projects/bouzecode_remote/uv_cache"
CACHE_NAVIGATEUR = "/data/projects/bouzecode_remote/navigateur"
# Magasin CA du systeme (Ubuntu) : il porte l'autorite interne corporate du gateway LLM, que certifi
# (utilise par requests/httpx) ignore -> TlsVerificationError, execution 257421 du 2026-10-06.
BUNDLE_CA_SYSTEME = Path("/etc/ssl/certs/ca-certificates.crt")
PREFIXE_LLM = "RD_OPTION_LLM_"
IDENTITE_GIT = {"GIT_AUTHOR_NAME": "bouzecode distant", "GIT_AUTHOR_EMAIL": "bouzecode-distant@invalid",
                "GIT_COMMITTER_NAME": "bouzecode distant", "GIT_COMMITTER_EMAIL": "bouzecode-distant@invalid"}


def environnement_vm(travail: Path, resultat: Path, bundle_ca: Path = BUNDLE_CA_SYSTEME) -> dict:
    """Variables de la commande : uv/Artifactory, TMPDIR hors de /tmp (200 Mo sur la VM), jeton LLM.
    UV_PYTHON force le 3.11 de la VM : un `.python-version` (3.12 chez bouzecode) ferait telecharger
    un CPython depuis github.com, coupe (mesure 2026-10-05, execution 257364).
    HOME jetable dans le dossier de travail : l'agent y ecrit sessions et journaux (~/.bouzecode),
    qui ne doivent pas s'accumuler dans le HOME partage du compte app1."""
    env = dict(os.environ, BZ_RESULTAT=str(resultat), BZ_TRAVAIL=str(travail), BZ_UV=UV, **IDENTITE_GIT,
               TMPDIR=str(travail / "tmp"), HOME=str(travail / "home"), UV_CACHE_DIR=CACHE_UV, UV_PYTHON=sys.executable, UV_PYTHON_DOWNLOADS="never",
               PATH=f"{Path(UV).parent}:{os.environ.get('PATH', '')}")
    for dossier in ("tmp", "home"):
        (travail / dossier).mkdir(parents=True, exist_ok=True)
    if os.environ.get("RD_OPTION_INDEX_PIP"):
        env["UV_INDEX_URL"] = os.environ["RD_OPTION_INDEX_PIP"]
    if bundle_ca.is_file():
        for nom in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
            env.setdefault(nom, str(bundle_ca))
    for option in ("RD_OPTION_GIT_USER", "RD_OPTION_GIT_TOKEN"):  # le jeton GitLab ne sert qu'au clone
        env.pop(option, None)
    for option in [cle for cle in env if cle.startswith(PREFIXE_LLM)]:
        valeur = env.pop(option)
        if valeur:
            env[option[len(PREFIXE_LLM):]] = valeur
    return env


def preparer_navigateur(resultat: Path) -> dict | None:
    """Lance installer_navigateur.py (depose a cote) ; rend ses variables, ou None si l'installation echoue."""
    installeur = Path(__file__).with_name("installer_navigateur.py")
    sortie = subprocess.run([sys.executable, str(installeur), CACHE_NAVIGATEUR, os.environ.get("RD_OPTION_INDEX_PIP", ""),
                             os.environ.get("RD_OPTION_NPM", ""), os.environ.get("RD_OPTION_CONDA", ""),
                             os.environ.get("RD_OPTION_RUN_ID", "x"), os.environ.get("RD_OPTION_PW_VERSION", "")],
                            capture_output=True, text=True)
    (resultat / "navigateur.log").write_text(sortie.stdout + sortie.stderr, encoding="utf-8")
    lignes = [l for l in sortie.stdout.splitlines() if l.startswith("BZ_NAVIGATEUR|")]
    if not lignes:
        return None
    variables = json.loads(lignes[-1].split("|", 1)[1])
    variables.pop("reutilise", None)
    return variables
