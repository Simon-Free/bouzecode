"""Client REST minimal Rundeck (API 40, JSON) : importer un job, le lancer, le suivre, le supprimer.

Pourquoi pas `connectorlib.RundeckConnector` : il n'est pas installe dans le venv bouzecode et
tire its config stack/omegaconf/jinja2 ; ses appels utiles tiennent en cinq requetes REST, reproduites
ici avec `requests` (deja une dependance). Comme le connecteur, on parle a l'hote interne sans
proxy et sans verification TLS (CA interne corporate absente du magasin certifi).
"""
import time

import requests
import urllib3

from bouzecode.remote.transport.settings import RUNDECK_PROJET, ReglagesDistants

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

STATUTS_TERMINAUX = {"succeeded", "failed", "aborted", "timedout", "failed-with-retry", "other"}
DELAI_REQUETE_S = 30


class ErreurRundeck(RuntimeError):
    """Reponse HTTP inattendue du serveur Rundeck (le code et le corps tronque sont dans le message)."""


class ClientRundeck:
    def __init__(self, reglages: ReglagesDistants):
        self.reglages = reglages
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.verify = False
        self.session.headers.update(
            {"X-Rundeck-Auth-Token": reglages.rundeck_jeton, "Accept": "application/json"}
        )

    def _requete(self, methode: str, chemin: str, **kwargs) -> requests.Response:
        reponse = self.session.request(
            methode, f"{self.reglages.rundeck_api}{chemin}", timeout=DELAI_REQUETE_S, **kwargs
        )
        if reponse.status_code >= 400:
            raise ErreurRundeck(f"{methode} {chemin} -> HTTP {reponse.status_code} : {reponse.text[:300]}")
        return reponse

    def verifier_acces(self) -> dict:
        """Appel leger authentifie : rend la description du projet ou leve ErreurRundeck."""
        return self._requete("GET", f"/project/{RUNDECK_PROJET}").json()

    def chercher_job(self, nom: str) -> str | None:
        jobs = self._requete("GET", f"/project/{RUNDECK_PROJET}/jobs", params={"jobExactFilter": nom}).json()
        return jobs[0]["id"] if jobs else None

    def importer_job(self, yaml_job: str) -> str:
        """Cree le job ; dupeOption=skip garantit qu'un job existant du meme nom n'est jamais ecrase."""
        reponse = self._requete(
            "POST",
            f"/project/{RUNDECK_PROJET}/jobs/import",
            params={"fileformat": "yaml", "dupeOption": "skip", "uuidOption": "remove"},
            data=yaml_job.encode("utf-8"),
            headers={"Content-Type": "application/yaml"},
        ).json()
        if reponse.get("failed") or reponse.get("skipped"):
            raise ErreurRundeck(f"import refuse : failed={reponse.get('failed')} skipped={reponse.get('skipped')}")
        return reponse["succeeded"][0]["id"]

    def lancer_job(self, job_id: str, options: dict | None = None) -> dict:
        execution = self._requete("POST", f"/job/{job_id}/run", json={"options": options or {}}).json()
        return {"execution_id": str(execution["id"]), "url": execution.get("permalink", "")}

    def etat_execution(self, execution_id: str) -> dict:
        execution = self._requete("GET", f"/execution/{execution_id}").json()
        return {
            "execution_id": str(execution["id"]),
            "statut": execution["status"],
            "termine": execution["status"] in STATUTS_TERMINAUX,
            "url": execution.get("permalink", ""),
            "job_id": (execution.get("job") or {}).get("id", ""),
        }

    def journal_execution(self, execution_id: str) -> str:
        sortie = self._requete("GET", f"/execution/{execution_id}/output", params={"format": "json"}).json()
        return "\n".join(entree.get("log", "") for entree in sortie.get("entries", []))

    def attendre_fin(self, execution_id: str, delai_max_s: float, pas_s: float = 5.0) -> dict:
        echeance = time.monotonic() + delai_max_s
        etat = self.etat_execution(execution_id)
        while not etat["termine"] and time.monotonic() < echeance:
            time.sleep(pas_s)
            etat = self.etat_execution(execution_id)
        return etat

    def supprimer_job(self, job_id: str) -> None:
        self._requete("DELETE", f"/job/{job_id}")
