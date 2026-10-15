# [desc] Frontière process Graph : PowerShellTransport (runner injectable, un script de ps/ par transport) et erreurs typées TeamsAuthError / TeamsTransportError. [/desc]
"""Toute la frontière process vers Microsoft Graph passe par ici : aucun autre module ne lance
PowerShell pour Graph.

L'authentification vit dans le cache MSAL .NET protégé par DPAPI, que Python ne sait pas lire :
ce sont les scripts de `ps/` qui l'utilisent (connexion commune `ps/graph_auth.ps1`). Chaque
transport vise UN script (`graph_activite.ps1` pour la lecture Teams/Outlook). Le `runner` est
injectable pour que les tests jouent le contrat sans process ni réseau : c'est le « faux Teams ».
Les pannes d'authentification lèvent `TeamsAuthError` — un TYPE, pas une chaîne à inspecter.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Callable

PS_DIR = Path(__file__).parent / "ps"
DEFAULT_TIMEOUT = 90
#: Codes rendus par les scripts (ou par Graph) qui signifient « l'utilisateur doit se reconnecter ».
CODES_AUTH = frozenset(
    {"AuthenticationError", "InvalidAuthenticationToken", "TokenExpired", "Unauthenticated", "Unauthorized"}
)

#: `runner(args) -> (code_de_sortie, stdout, stderr)`
Runner = Callable[[list[str]], "tuple[int, str, str]"]

#: Prefixe des lignes stderr par lesquelles les scripts annoncent l'etape en cours
#: (`connexion scopes=...`, `GET <uri>`) : sur timeout, la derniere dit OU ca a pendu.
MARQUE_ETAPE = "BZ_ETAPE:"
#: Fragments (minuscules) du message MSAL quand il tente un login navigateur impossible.
MARQUES_LOGIN_INTERACTIF = ("écouteur", "ecouteur", "listener", "interactive")


def derniere_etape(stderr: Any) -> str:
    """Derniere etape `BZ_ETAPE:` lue dans un stderr (bytes ou str, eventuellement partiel)."""
    if not stderr:
        return ""
    texte = stderr.decode("utf-8", errors="replace") if isinstance(stderr, bytes) else str(stderr)
    etape = ""
    for ligne in texte.splitlines():
        ligne = ligne.strip()
        if ligne.startswith(MARQUE_ETAPE):
            etape = ligne[len(MARQUE_ETAPE):].strip()
    return etape


class TeamsTransportError(RuntimeError):
    """L'appel Graph a échoué pour une raison qui n'est pas un problème d'authentification."""


class TeamsAuthError(TeamsTransportError):
    """Le jeton délégué n'est plus utilisable : seul l'utilisateur peut y remédier."""


class PowerShellTransport:
    """Délègue chaque appel Graph au script `script` (`-Action <nom> -Param valeur ...`)."""

    def __init__(
        self,
        script: Path,
        runner: Runner | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self._script = Path(script)
        self._timeout = timeout
        self._runner: Runner = runner if runner is not None else self._run_powershell

    def _call(self, action: str, **parametres: Any) -> dict:
        args = ["-Action", action]
        for nom, valeur in parametres.items():
            args += [f"-{nom}", str(valeur)]
        try:
            code, sortie, erreur = self._runner(args)
        except subprocess.TimeoutExpired as souci:
            #  Un tenant muet fait pendre le process PowerShell : TimeoutExpired n'est PAS une
            #  OSError, elle traversait donc tous les filtres appelants. Ici, la frontiere
            #  process la traduit dans SON type metier.
            etape = derniere_etape(souci.stderr)
            if etape and etape.startswith("connexion"):
                #  Mesure du 2026-10-15 : Mails ET Teams pendaient 120 s dans
                #  Connect-MgGraph (login interactif impossible sous -NonInteractive),
                #  AVANT toute requete Graph. Le dire evite de chercher un Graph lent.
                raise TeamsTransportError(
                    f"Graph ({action}) n'a pas repondu en {self._timeout}s : bloque a "
                    f"l'etape « {etape} » (aucune requete Graph envoyee). Le jeton en "
                    "cache est expire ou ne couvre pas ces scopes : une reconnexion "
                    "interactive (Connect-MgGraph) est requise."
                ) from souci
            ou = f" pendant « {etape} »" if etape else ""
            raise TeamsTransportError(
                f"Graph ({action}) n'a pas repondu en {self._timeout}s{ou}"
            ) from souci
        charge = self._parse(sortie, code, erreur, action)
        if isinstance(charge.get("error"), dict) or code != 0:
            self._lever(charge, code, erreur, action)
        return charge

    def _parse(self, sortie: str, code: int, erreur: str, action: str) -> dict:
        nom = self._script.name
        texte = (sortie or "").strip()
        if not texte:
            raise TeamsTransportError(
                f"{nom} -Action {action} n'a rien écrit sur stdout "
                f"(code {code}) : {(erreur or '').strip() or 'aucune erreur rapportée'}"
            )
        try:
            charge = json.loads(texte)
        except json.JSONDecodeError as souci:
            raise TeamsTransportError(
                f"{nom} -Action {action} a écrit autre chose que du JSON "
                f"(code {code}) : {texte[:400]}"
            ) from souci
        if not isinstance(charge, dict):
            raise TeamsTransportError(
                f"{nom} -Action {action} a rendu un {type(charge).__name__} là où un objet est attendu."
            )
        return charge

    @staticmethod
    def _lever(charge: dict, code: int, erreur: str, action: str) -> None:
        detail = charge.get("error") if isinstance(charge.get("error"), dict) else {}
        message = str(detail.get("message") or (erreur or "").strip() or charge)
        if any(marque in message.lower() for marque in MARQUES_LOGIN_INTERACTIF):
            #  « Une erreur s'est produite lors de l'ecriture dans un ecouteur » : MSAL a
            #  tente d'ouvrir le login navigateur (listener loopback) dans un process non
            #  interactif. C'est un probleme d'AUTHENTIFICATION, pas de reseau.
            raise TeamsAuthError(
                f"Graph ({action}) : connexion interactive requise (jeton en cache "
                f"expire ou scopes non consentis), Connect-MgGraph a echoue : {message}"
            )
        if str(detail.get("code")) in CODES_AUTH:
            raise TeamsAuthError(f"Teams ({action}) : {message}")
        raise TeamsTransportError(f"Teams ({action}) a échoué (code {code}) : {message}")

    def _run_powershell(self, args: list[str]) -> tuple[int, str, str]:
        commande = [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(self._script),
            *args,
        ]
        try:
            acheve = subprocess.run(commande, capture_output=True, timeout=self._timeout)
        except FileNotFoundError as souci:
            #  Hors Windows (ou PowerShell absent du PATH), l'outil levait un FileNotFoundError
            #  brut : l'assistant plantait au lieu de dire que la boîte Outlook est inaccessible.
            raise TeamsTransportError(
                "PowerShell introuvable : l'accès Outlook/Teams n'est disponible que sous Windows."
            ) from souci
        decoder = lambda flux: (flux or b"").decode("utf-8", errors="replace")
        return acheve.returncode, decoder(acheve.stdout), decoder(acheve.stderr)
