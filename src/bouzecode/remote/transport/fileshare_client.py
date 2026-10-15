"""Client REST minimal Azure Files (authentification Shared Key) : deposer, lire, lister, supprimer.

Pourquoi pas `connectorlib.azure.FileShareConnector` : il exige `azure-storage-file-share`,
absent du venv bouzecode. Les cinq operations utiles se font en REST signe HMAC-SHA256 avec
`requests` ; le share est celui que les noeuds rec montent en /data/filestorage.
"""
import base64
import hashlib
import hmac
import xml.etree.ElementTree as ElementTree
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

import requests

from bouzecode.remote.transport.settings import ReglagesDistants

VERSION_API = "2022-11-02"
TAILLE_PLAGE = 4 * 1024 * 1024
DELAI_REQUETE_S = 120
ENTETES_SIGNEES = ("Content-Encoding", "Content-Language", "Content-Length", "Content-MD5", "Content-Type",
                   "Date", "If-Modified-Since", "If-Match", "If-None-Match", "If-Unmodified-Since", "Range")


class ErreurFileShare(RuntimeError):
    """Reponse HTTP inattendue du service Azure Files."""


class ClientFileShare:
    def __init__(self, reglages: ReglagesDistants):
        self.base = reglages.fileshare_url
        self.compte = urlparse(reglages.fileshare_url).hostname.split(".")[0]
        self.share = reglages.fileshare_nom
        self.cle = base64.b64decode(reglages.fileshare_cle) if reglages.fileshare_cle else b""
        self.session = requests.Session()
        self.session.trust_env = False

    def _signer(self, methode: str, chemin_encode: str, parametres: dict, entetes: dict) -> str:
        valeurs = [entetes.get(nom, "") for nom in ENTETES_SIGNEES]
        if valeurs[2] == "0":
            valeurs[2] = ""
        canoniques = "".join(f"{k.lower()}:{v}\n" for k, v in sorted(entetes.items()) if k.lower().startswith("x-ms-"))
        ressource = f"/{self.compte}{chemin_encode}" + "".join(
            f"\n{k.lower()}:{v}" for k, v in sorted(parametres.items()))
        a_signer = "\n".join([methode, *valeurs, canoniques + ressource])
        signature = base64.b64encode(hmac.new(self.cle, a_signer.encode("utf-8"), hashlib.sha256).digest()).decode()
        return f"SharedKey {self.compte}:{signature}"

    def _requete(self, methode: str, chemin: str, parametres: dict | None = None, entetes: dict | None = None,
                 donnees: bytes = b"", accepter: tuple = ()) -> requests.Response:
        parametres = parametres or {}
        chemin_encode = "/" + quote(f"{self.share}/{chemin.strip('/')}".rstrip("/"))
        entetes = {"x-ms-date": datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT"),
                   "x-ms-version": VERSION_API, "Content-Length": str(len(donnees)), **(entetes or {})}
        entetes["Authorization"] = self._signer(methode, chemin_encode, parametres, entetes)
        reponse = self.session.request(methode, self.base + chemin_encode, params=parametres, headers=entetes,
                                       data=donnees, timeout=DELAI_REQUETE_S)
        if reponse.status_code >= 400 and reponse.status_code not in accepter:
            raise ErreurFileShare(f"{methode} {chemin} -> HTTP {reponse.status_code} : {reponse.text[:300]}")
        return reponse

    def creer_dossiers(self, chemin_dossier: str) -> None:
        cumul = ""
        for morceau in chemin_dossier.strip("/").split("/"):
            cumul = f"{cumul}/{morceau}" if cumul else morceau
            self._requete("PUT", cumul, {"restype": "directory"}, accepter=(409,))

    def deposer(self, chemin: str, contenu: bytes) -> None:
        if "/" in chemin.strip("/"):
            self.creer_dossiers(chemin.strip("/").rsplit("/", 1)[0])
        self._requete("PUT", chemin, entetes={"x-ms-type": "file", "x-ms-content-length": str(len(contenu))})
        for debut in range(0, len(contenu), TAILLE_PLAGE):
            morceau = contenu[debut:debut + TAILLE_PLAGE]
            self._requete("PUT", chemin, {"comp": "range"}, donnees=morceau, entetes={
                "x-ms-write": "update", "x-ms-range": f"bytes={debut}-{debut + len(morceau) - 1}"})

    def lire(self, chemin: str) -> bytes:
        return self._requete("GET", chemin).content

    def existe(self, chemin: str) -> bool:
        return self._requete("HEAD", chemin, accepter=(404,)).status_code == 200

    def lister(self, chemin_dossier: str) -> list[dict]:
        """Rend [{nom, dossier: bool}] ; liste vide si le dossier n'existe pas."""
        reponse = self._requete("GET", chemin_dossier, {"restype": "directory", "comp": "list"}, accepter=(404,))
        if reponse.status_code == 404:
            return []
        racine = ElementTree.fromstring(reponse.content)
        return [{"nom": e.findtext("Name"), "dossier": e.tag == "Directory"} for e in racine.iter()
                if e.tag in ("File", "Directory")]

    def supprimer_arborescence(self, chemin_dossier: str) -> None:
        for entree in self.lister(chemin_dossier):
            chemin = f"{chemin_dossier.rstrip('/')}/{entree['nom']}"
            if entree["dossier"]:
                self.supprimer_arborescence(chemin)
            else:
                self._requete("DELETE", chemin, accepter=(404,))
        self._requete("DELETE", chemin_dossier, {"restype": "directory"}, accepter=(404,))
