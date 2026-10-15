"""Les ecritures Microsoft Graph du Bureau : brouillon de mail, creneau, reunion.

Frontiere unique entre le Python et `teams/ps/graph_bureau.ps1`. Rien au-dessus de ce
module ne connait PowerShell : les outils d'agent appellent des fonctions, recoivent des
dicts, et n'attrapent que deux types d'erreur.

Trois choix payes d'avance :

1. `deposer_brouillon` n'envoie JAMAIS. La validation humaine demandee le 2026-09-21 est
   le dossier Brouillons d'Outlook : l'agent depose, l'humain relit et envoie. Ce n'est
   pas un detail d'implementation, c'est le contrat -- aucune action d'envoi n'existe ni
   ici ni dans le script.
2. Le script PowerShell est SEPARE de `teams/ps/graph_activite.ps1` (lecture seule) : la
   lecture garde des scopes de lecture. Ici chaque action demande son scope
   minimal, comme `graph_activite.ps1`.
3. Les exceptions sont REUTILISEES depuis `teams.graph_transport` (`TeamsAuthError`,
   `TeamsTransportError`). Les appelants les filtrent deja ; un troisieme type d'erreur
   n'aurait fait qu'ajouter un `except` a oublier.

Le `runner` est injectable : les tests passent un faux et ne lancent jamais PowerShell.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from .teams.graph_transport import TeamsAuthError, TeamsTransportError

__all__ = [
    "BureauGraph",
    "FUSEAU_DEFAUT",
    "GRAPH_BUREAU_PS1",
    "TeamsAuthError",
    "TeamsTransportError",
    "default_transport",
]

PS_DIR = Path(__file__).resolve().parent / "teams" / "ps"
GRAPH_BUREAU_PS1 = PS_DIR / "graph_bureau.ps1"

#  Fuseau WINDOWS (et non IANA) : c'est ce que Graph attend dans `timeZone` quand la
#  requete vient d'Outlook/Exchange. "Europe/Paris" est accepte par Graph mais rend des
#  reponses dans un autre referentiel selon la boite.
FUSEAU_DEFAUT = "Romance Standard Time"

DEFAULT_TIMEOUT = 120
DUREE_CRENEAU_DEFAUT = 60
DUREE_REUNION_DEFAUT = 30

#  Formats acceptes en entree. Un LLM ecrit indifferemment un T ou une espace, et parfois
#  sans les secondes : les trois formes sont lues, une seule forme est emise.
FORMAT_SORTIE = "%Y-%m-%dT%H:%M:%S"

Runner = Callable[[Sequence[str]], tuple[int, str, str]]


def _run_powershell(args: Sequence[str], timeout: int = DEFAULT_TIMEOUT) -> tuple[int, str, str]:
    """Lance `graph_bureau.ps1` avec les arguments donnes."""
    commande = [
        "powershell", "-NoProfile", "-NonInteractive",
        "-ExecutionPolicy", "Bypass",
        "-File", str(GRAPH_BUREAU_PS1),
        *[str(argument) for argument in args],
    ]
    acheve = subprocess.run(commande, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=timeout)
    return acheve.returncode, acheve.stdout or "", acheve.stderr or ""


def _liste(valeurs: Iterable[str] | str | None) -> list[str]:
    """Normalise destinataires/participants en liste d'adresses non vides."""
    if valeurs is None:
        return []
    if isinstance(valeurs, str):
        brut: Iterable[str] = valeurs.replace(";", ",").split(",")
    else:
        brut = valeurs
    return [str(valeur).strip() for valeur in brut if str(valeur).strip()]


def _lire_date(brut: str) -> datetime:
    """Lit une date locale ecrite par un humain ou un modele.

    Leve une `ValueError` NOMMEE : l'appelant la rend telle quelle a l'agent, qui peut
    alors redemander la date au lieu d'inventer un creneau.
    """
    texte = str(brut or "").strip()
    if not texte:
        raise ValueError("date_illisible: aucune date fournie")
    normalise = texte.replace(" ", "T", 1) if " " in texte and "T" not in texte else texte
    try:
        return datetime.fromisoformat(normalise)
    except ValueError as souci:
        raise ValueError(f"date_illisible: {texte}") from souci


def _duree(minutes: Any, defaut: int) -> int:
    #  `0` est falsy : un `minutes or defaut` le remplacait silencieusement par 60.
    #  Une duree explicitement nulle est une SAISIE (a refuser), pas une absence.
    if minutes is None or (isinstance(minutes, str) and not minutes.strip()):
        return defaut
    try:
        valeur = int(minutes)
    except (TypeError, ValueError) as souci:
        raise ValueError(f"duree_invalide: {minutes}") from souci
    if valeur <= 0:
        raise ValueError(f"duree_invalide: {valeur} minutes")
    return valeur


class BureauGraph:
    """Les trois ecritures Graph du Bureau, derriere un runner injectable."""

    def __init__(self, runner: Runner | None = None, timeout: int = DEFAULT_TIMEOUT,
                 script: Path = GRAPH_BUREAU_PS1) -> None:
        self._timeout = timeout
        self._script = script
        self._runner: Runner = runner or (lambda args: _run_powershell(args, timeout))

    # ---------------------------------------------------------------- ecritures

    def deposer_brouillon(self, destinataires: Iterable[str] | str, objet: str,
                          corps: str = "", cc: Iterable[str] | str = ()) -> dict:
        """Depose un brouillon dans Brouillons d'Outlook. N'ENVOIE PAS."""
        adresses = _liste(destinataires)
        if not adresses:
            raise ValueError("destinataire_manquant: aucune adresse fournie")
        if not str(objet or "").strip():
            raise ValueError("objet_manquant: un brouillon sans objet est illisible")

        parametres: dict[str, str] = {
            "Destinataires": ",".join(adresses),
            "Objet": str(objet).strip(),
        }
        copies = _liste(cc)
        if copies:
            #  Ne JAMAIS passer -Cc vide : `Require-Param` cote PowerShell le refuserait.
            parametres["Cc"] = ",".join(copies)
        return self._call_avec_corps("brouillon", corps or "", parametres)

    def bloquer_creneau(self, sujet: str, debut: str,
                        duree_minutes: int = DUREE_CRENEAU_DEFAUT,
                        fuseau: str = FUSEAU_DEFAUT) -> dict:
        """Bloque du temps dans l'agenda : aucun participant, aucune invitation."""
        if not str(sujet or "").strip():
            raise ValueError("sujet_manquant: un creneau sans sujet n'est pas relisible")
        debut_lu = _lire_date(debut)
        minutes = _duree(duree_minutes, DUREE_CRENEAU_DEFAUT)
        #  La fin est CALCULEE depuis une duree : la classe d'erreur « fin avant debut »
        #  n'existe pas, et un modele raisonne naturellement en duree.
        fin = debut_lu + timedelta(minutes=minutes)
        return self._call("creneau",
                          Sujet=str(sujet).strip(),
                          Debut=debut_lu.strftime(FORMAT_SORTIE),
                          Fin=fin.strftime(FORMAT_SORTIE),
                          Fuseau=fuseau)

    def organiser_reunion(self, sujet: str, debut: str,
                          participants: Iterable[str] | str,
                          duree_minutes: int = DUREE_REUNION_DEFAUT,
                          fuseau: str = FUSEAU_DEFAUT, corps: str = "") -> dict:
        """Cree une reunion Teams et invite les participants."""
        if not str(sujet or "").strip():
            raise ValueError("sujet_manquant: une reunion sans sujet n'est pas relisible")
        invites = _liste(participants)
        if not invites:
            raise ValueError("participants_manquants: une reunion sans invite est un creneau")
        debut_lu = _lire_date(debut)
        minutes = _duree(duree_minutes, DUREE_REUNION_DEFAUT)
        fin = debut_lu + timedelta(minutes=minutes)
        parametres = {
            "Sujet": str(sujet).strip(),
            "Debut": debut_lu.strftime(FORMAT_SORTIE),
            "Fin": fin.strftime(FORMAT_SORTIE),
            "Fuseau": fuseau,
            "Participants": ",".join(invites),
        }
        if corps:
            return self._call_avec_corps("reunion", corps, parametres)
        return self._call("reunion", **parametres)

    # ---------------------------------------------------------------- transport

    def _call_avec_corps(self, action: str, corps: str, parametres: dict[str, str]) -> dict:
        """Passe un texte libre par un fichier temporaire (`-CorpsPath`).

        Un fichier plutot que la ligne de commande : ni echappement de guillemets, ni
        limite de longueur de ligne de commande. Le fichier est REFERME avant l'appel et
        supprime apres -- Windows refuse de supprimer un fichier reste ouvert.
        """
        descripteur, chemin = tempfile.mkstemp(prefix="bureau_corps_", suffix=".txt")
        try:
            with os.fdopen(descripteur, "w", encoding="utf-8") as fichier:
                fichier.write(corps)
            return self._call(action, CorpsPath=chemin, **parametres)
        finally:
            try:
                os.unlink(chemin)
            except OSError:
                pass

    def _call(self, action: str, **parametres: Any) -> dict:
        args = ["-Action", action]
        for nom, valeur in parametres.items():
            args += [f"-{nom}", str(valeur)]
        try:
            code, sortie, erreur = self._runner(args)
        except subprocess.TimeoutExpired as souci:
            #  TimeoutExpired n'est PAS une OSError : sans cette traduction elle traverse
            #  tous les filtres appelants (lecon deja payee dans graph_transport._call).
            raise TeamsTransportError(
                f"Graph bureau ({action}) n'a pas repondu en {self._timeout}s"
            ) from souci
        charge = self._parse(sortie, code, erreur, action)
        if isinstance(charge.get("error"), dict) or code != 0:
            self._lever(charge, code, erreur, action)
        return charge

    @staticmethod
    def _parse(sortie: str, code: int, erreur: str, action: str) -> dict:
        texte = (sortie or "").strip()
        if not texte:
            motif = (erreur or "").strip() or f"code {code}"
            raise TeamsTransportError(f"Graph bureau ({action}) n'a rien rendu : {motif}")
        try:
            charge = json.loads(texte)
        except json.JSONDecodeError as souci:
            raise TeamsTransportError(
                f"Graph bureau ({action}) a rendu autre chose que du JSON : {texte[:200]}"
            ) from souci
        if not isinstance(charge, dict):
            raise TeamsTransportError(
                f"Graph bureau ({action}) a rendu un {type(charge).__name__}, pas un objet")
        return charge

    @staticmethod
    def _lever(charge: dict, code: int, erreur: str, action: str) -> None:
        detail = charge.get("error") if isinstance(charge.get("error"), dict) else {}
        message = str(detail.get("message") or erreur or f"code {code}")
        if str(detail.get("code") or "") == "AuthenticationError":
            raise TeamsAuthError(f"Graph bureau ({action}) : {message}")
        raise TeamsTransportError(f"Graph bureau ({action}) : {message}")


def default_transport() -> BureauGraph:
    """Le transport utilise par les outils d'agent (remplace par un faux en test)."""
    return BureauGraph()
