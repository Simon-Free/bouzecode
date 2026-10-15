"""Reglages de l'execution distante : Rundeck rec et file share Azure, lus dans l'environnement.

Seul l'environnement `rec` est servi : toute autre valeur leve `EnvironnementInterdit`.
Hotes et noms de share viennent des variables du .env (jamais ecrits en dur) ; les secrets ne
sont jamais journalises et `secrets_manquants()` ne rend que des NOMS de variables.
"""
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

ENVIRONNEMENT_AUTORISE = "rec"

RUNDECK_URL_REC = "https://rundeck.example.com"
RUNDECK_API_VERSION = 40
RUNDECK_PROJET = "DEMODB"
RUNDECK_FILTRE_NOEUDS = "tags:apprentissage"
RUNDECK_GROUPE_JOBS = "BOUZECODE/REMOTE"

FILESHARE_RACINE = "datascience/bouzecode_remote"
VM_MONTAGE_SHARE = "/data/filestorage"
VM_RACINE_TRAVAIL = "/data/projects/bouzecode_remote"
VM_CACHE_NAVIGATEURS = "/data/projects/bouzecode_remote/ms-playwright"
VM_UV = "/data/datainno/uv/uv"
VM_PYTHON = "python3.11"

VARIABLE_JETON_RUNDECK = "RUNDECK_PRIVATE_TOKEN_REC"
VARIABLE_CLE_FILESHARE = "AZURE_PRIVATE_TOKEN_REC"
VARIABLE_URL_FILESHARE = "AZURE_FILESHARE_URL"
VARIABLE_NOM_FILESHARE = "AZURE_FILESHARE_NAME"
VARIABLE_HOTE_ARTIFACTORY = "TRUSTED_HOST"
VARIABLES_REQUISES = (
    VARIABLE_JETON_RUNDECK,
    VARIABLE_CLE_FILESHARE,
    VARIABLE_URL_FILESHARE,
    VARIABLE_NOM_FILESHARE,
    VARIABLE_HOTE_ARTIFACTORY,
)


class EnvironnementInterdit(ValueError):
    """Levee pour tout environnement autre que rec (prod, pp, dev...)."""


@dataclass(frozen=True)
class ReglagesDistants:
    environnement: str
    rundeck_url: str
    rundeck_jeton: str
    fileshare_url: str
    fileshare_nom: str
    fileshare_cle: str
    index_pip: str

    @property
    def rundeck_api(self) -> str:
        return f"{self.rundeck_url}/api/{RUNDECK_API_VERSION}"


def verifier_environnement(environnement: str) -> None:
    if environnement != ENVIRONNEMENT_AUTORISE:
        raise EnvironnementInterdit(
            f"environnement {environnement!r} refuse : seul {ENVIRONNEMENT_AUTORISE!r} est autorise"
        )


def secrets_manquants() -> list[str]:
    return [nom for nom in VARIABLES_REQUISES if not os.environ.get(nom)]


def index_pip_artifactory() -> str:
    hote = os.environ.get(VARIABLE_HOTE_ARTIFACTORY, "")
    return f"https://{hote}/artifactory/api/pypi/pypi-remote/simple" if hote else ""


def charger_reglages(environnement: str = ENVIRONNEMENT_AUTORISE) -> ReglagesDistants:
    verifier_environnement(environnement)
    return ReglagesDistants(
        environnement=environnement,
        rundeck_url=os.environ.get("BOUZECODE_RUNDECK_URL", RUNDECK_URL_REC),
        rundeck_jeton=os.environ.get(VARIABLE_JETON_RUNDECK, ""),
        fileshare_url=os.environ.get(VARIABLE_URL_FILESHARE, "").rstrip("/"),
        fileshare_nom=os.environ.get(VARIABLE_NOM_FILESHARE, ""),
        fileshare_cle=os.environ.get(VARIABLE_CLE_FILESHARE, ""),
        index_pip=index_pip_artifactory(),
    )


def nouvel_identifiant_execution(prefixe: str = "bz") -> str:
    """Suffixe unique par execution : horodatage UTC + 8 hex aleatoires (aucun nom fixe partage)."""
    horodatage = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{prefixe}_{horodatage}_{uuid.uuid4().hex[:8]}"


VARIABLE_JETON_GITLAB = "GITLAB_TOKEN"  # le .env du poste (cf. memoire gitlab_connector_token_env)
VARIABLE_UTILISATEUR_GITLAB = "GITLAB_USERNAME"


def identifiants_gitlab() -> dict[str, str]:
    """Options secretes GIT_USER/GIT_TOKEN du clone sur la VM ; {} sans jeton (repli bundle complet)."""
    jeton = os.environ.get(VARIABLE_JETON_GITLAB, "")
    if not jeton:
        return {}
    return {"GIT_USER": os.environ.get(VARIABLE_UTILISATEUR_GITLAB, "") or "oauth2", "GIT_TOKEN": jeton}
