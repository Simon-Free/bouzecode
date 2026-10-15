"""Cache disque, par jour, des lectures d'activite Microsoft 365.

Pourquoi : chaque lecture de `ms_activite` relance un process PowerShell, une
authentification Graph et le telechargement de TOUTE la fenetre demandee (2, 7 ou 30
jours) — alors que 29 de ces 30 jours ne bougeront plus jamais. Un jour REVOLU est
immuable : on l'ecrit une fois sur disque et on le relit ensuite. Le jour COURANT, lui,
est toujours re-telecharge (il evolue jusqu'a minuit).

Ce module ne connait ni PowerShell ni Graph : il ne manipule que les payloads deja
rendus par `graph_activite.ps1`. C'est ce qui le rend testable sans tenant Microsoft.

Formes de payload traitees (constatees dans `teams/ps/graph_activite.ps1`) :

* `mail`   : `{value: [{id, received, ...}], has_more}` — items PLATS.
* `chats`  : `{value: [{id, topic, kind, messages: [{id, created, ...}]}], has_more}`
* `canaux` : `{value: [{id: "<team>/<canal>", equipe, canal, messages: [...]}],
              has_more, messages_indisponibles}`
* `agenda` : `{value: [{id, start, end, subject, ...}], has_more}` — items PLATS dates par
  `start`. Seuls les jours REVOLUS se figent : l'agenda a venir est toujours relu.

Les deux dernieres sont des CONTENEURS : un meme chat chevauche plusieurs jours, il est
donc decoupe par jour puis refusionne sur son `id` a la lecture.
"""

from __future__ import annotations
from bouzecode.paths import data_dir as bouzecode_data_dir

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

#: Seules les actions bornees par une fenetre de temps sont cachables. `equipes`,
#: `equipes_ids`, `messages` et `mail`+`MessageId` repondent a la demande sur un objet
#: precis : les cacher n'economise rien et risque de servir un etat perime.
ACTIONS_CACHABLES = frozenset({"mail", "chats", "canaux", "agenda"})

#: Nom du champ date selon la forme du payload.
CHAMP_DATE = {"mail": "received", "chats": "created", "canaux": "created", "agenda": "start"}

#: Actions dont les elements sont des CONTENEURS portant une liste `messages`.
ACTIONS_CONTENEUR = frozenset({"chats", "canaux"})

#: Variable d'environnement : `0` desactive le cache, sinon racine via _CACHE_DIR.
ENV_CACHE = "BOUZECODE_MS_ACTIVITE_CACHE"
ENV_CACHE_DIR = "BOUZECODE_MS_ACTIVITE_CACHE_DIR"


def cache_actif() -> bool:
    """Faux seulement si `BOUZECODE_MS_ACTIVITE_CACHE` vaut `0`/`false`/`non`."""
    valeur = os.environ.get(ENV_CACHE, "").strip().lower()
    return valeur not in {"0", "false", "non", "off"}


def racine_cache() -> Path:
    """Racine du cache. Surchargeable pour que les tests n'ecrivent pas dans le HOME."""
    brut = os.environ.get(ENV_CACHE_DIR, "").strip()
    if brut:
        return Path(brut)
    return bouzecode_data_dir() / "cache" / "ms_activite"


def _empreinte(parametres: dict[str, Any]) -> str:
    """Signature des parametres HORS borne de temps.

    `Top` et `Messages` changent le CONTENU rendu (un plafond de 20 messages n'est pas
    un plafond de 50) : deux plafonds differents sont donc deux caches differents, sinon
    on servirait une tranche tronquee comme si elle etait complete.
    """
    utiles = {
        nom: str(valeur)
        for nom, valeur in sorted(parametres.items())
        if nom not in {"Since", "Until"}
    }
    brut = json.dumps(utiles, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(brut.encode("utf-8")).hexdigest()[:16]


def dossier_tranches(
    action: str, parametres: dict[str, Any], racine: Path | None = None
) -> Path:
    """`<racine>/<action>/<empreinte des parametres>/`."""
    base = racine or racine_cache()
    return base / action / _empreinte(parametres)


def chemin_tranche(
    action: str, parametres: dict[str, Any], jour: str, racine: Path | None = None
) -> Path:
    """Fichier d'une tranche d'un jour (`2026-09-24.json`)."""
    return dossier_tranches(action, parametres, racine) / f"{jour}.json"


def _en_datetime(iso: str) -> datetime | None:
    """Lit une date ISO Graph (`2026-09-01T08:00:00Z`) en UTC, ou None si illisible."""
    if not iso:
        return None
    texte = str(iso).strip().replace("Z", "+00:00")
    try:
        valeur = datetime.fromisoformat(texte)
    except ValueError:
        return None
    if valeur.tzinfo is None:
        valeur = valeur.replace(tzinfo=timezone.utc)
    return valeur.astimezone(timezone.utc)


def jour_de(iso: str) -> str | None:
    """Jour UTC (`2026-09-01`) d'une date ISO, ou None si illisible."""
    valeur = _en_datetime(iso)
    return None if valeur is None else valeur.strftime("%Y-%m-%d")


def jour_courant(maintenant: datetime | None = None) -> str:
    """Le jour UTC en cours : le SEUL qui ne doit jamais etre figé sur disque."""
    reference = maintenant or datetime.now(timezone.utc)
    return reference.astimezone(timezone.utc).strftime("%Y-%m-%d")


def minuit_iso(jour: str) -> str:
    """`2026-09-01` -> `2026-09-01T00:00:00Z`, la borne basse envoyee au script."""
    return f"{jour}T00:00:00Z"


def jours_couverts(since: str, maintenant: datetime | None = None) -> list[str]:
    """Jours UTC de `since` (inclus) au jour courant (inclus), dans l'ordre.

    Rend une liste vide si `since` est illisible ou dans le futur : mievaut vaut
    retomber sur l'appel direct que d'inventer une couverture.
    """
    debut = _en_datetime(since)
    if debut is None:
        return []
    fin = (maintenant or datetime.now(timezone.utc)).astimezone(timezone.utc)
    jour = debut.replace(hour=0, minute=0, second=0, microsecond=0)
    borne = fin.replace(hour=0, minute=0, second=0, microsecond=0)
    jours: list[str] = []
    while jour <= borne:
        jours.append(jour.strftime("%Y-%m-%d"))
        jour += timedelta(days=1)
    return jours


def figeable(action: str, charge: dict) -> bool:
    """Peut-on figer cette reponse ?

    Non si elle est PLAFONNEE (`has_more`) ou incomplete (`messages_indisponibles`) :
    ecrire une tranche tronquee la ferait passer pour definitive a chaque relecture.
    """
    if action not in ACTIONS_CACHABLES:
        return False
    return not bool(charge.get("has_more")) and not bool(
        charge.get("messages_indisponibles")
    )


def decouper(
    action: str, charge: dict, maintenant: datetime | None = None
) -> dict[str, dict]:
    """Repartit un payload en une tranche par jour REVOLU (le jour courant est exclu).

    Pour `chats`/`canaux`, un conteneur est recopie dans chaque jour ou il a au moins un
    message, avec ses metadonnees et ses messages de ce jour-la seulement.
    """
    aujourdhui = jour_courant(maintenant)
    champ = CHAMP_DATE.get(action, "created")
    tranches: dict[str, dict] = {}
    for element in charge.get("value") or []:
        if not isinstance(element, dict):
            continue
        if action in ACTIONS_CONTENEUR:
            par_jour: dict[str, list[dict]] = {}
            for message in element.get("messages") or []:
                jour = jour_de(message.get(champ, ""))
                if jour is None or jour >= aujourdhui:
                    continue
                par_jour.setdefault(jour, []).append(message)
            for jour, messages in par_jour.items():
                copie = {
                    nom: valeur
                    for nom, valeur in element.items()
                    if nom != "messages"
                }
                copie["messages"] = messages
                tranches.setdefault(jour, {"value": []})["value"].append(copie)
        else:
            jour = jour_de(element.get(champ, ""))
            if jour is None or jour >= aujourdhui:
                continue
            tranches.setdefault(jour, {"value": []})["value"].append(element)
    return tranches


def _cle(element: dict, rang: int) -> str:
    """Identite d'un element : son `id` Graph, sinon son rang (jamais de perte)."""
    identifiant = element.get("id")
    return str(identifiant) if identifiant else f"#{rang}"


def _fusionner_messages(action: str, existants: list[dict], ajouts: list[dict]) -> list[dict]:
    champ = CHAMP_DATE.get(action, "created")
    vus = {_cle(message, rang): message for rang, message in enumerate(existants)}
    for rang, message in enumerate(ajouts):
        vus.setdefault(_cle(message, len(vus) + rang), message)
    return sorted(
        vus.values(), key=lambda message: str(message.get(champ, "")), reverse=True
    )


def fusionner(action: str, payloads: Iterable[dict]) -> dict:
    """Recompose UN payload de la meme forme que le script a partir de N tranches.

    Dedup par `id` (le jour courant re-telecharge recouvre souvent la derniere tranche),
    conteneurs fusionnes sur leur `id`, tri decroissant par date comme Graph le rend.
    `has_more` / `messages_indisponibles` : vrai des qu'un morceau l'etait.
    """
    champ = CHAMP_DATE.get(action, "created")
    elements: dict[str, dict] = {}
    has_more = False
    indisponibles = False
    for payload in payloads:
        if not payload:
            continue
        has_more = has_more or bool(payload.get("has_more"))
        indisponibles = indisponibles or bool(payload.get("messages_indisponibles"))
        for rang, element in enumerate(payload.get("value") or []):
            if not isinstance(element, dict):
                continue
            cle = _cle(element, rang)
            connu = elements.get(cle)
            if connu is None:
                elements[cle] = dict(element)
                continue
            if action in ACTIONS_CONTENEUR:
                connu["messages"] = _fusionner_messages(
                    action,
                    list(connu.get("messages") or []),
                    list(element.get("messages") or []),
                )
                for nom, valeur in element.items():
                    if nom != "messages" and not connu.get(nom):
                        connu[nom] = valeur
    if action in ACTIONS_CONTENEUR:
        def date_conteneur(element: dict) -> str:
            dates = [
                str(message.get(champ, ""))
                for message in element.get("messages") or []
            ]
            return max(dates) if dates else ""

        ordonnes = sorted(elements.values(), key=date_conteneur, reverse=True)
        if action == "chats":
            # Le script EXCLUT un chat sans message recent (graph_activite.ps1 L380) :
            # la fusion doit rendre la meme forme, sinon l'appelant voit des chats
            # fantomes qui n'existaient pas sans cache.
            ordonnes = [
                element for element in ordonnes if element.get("messages")
            ]
    else:
        ordonnes = sorted(
            elements.values(),
            key=lambda element: str(element.get(champ, "")),
            reverse=True,
        )
    resultat: dict[str, Any] = {"value": ordonnes, "has_more": has_more}
    if action == "canaux":
        resultat["messages_indisponibles"] = indisponibles
    return resultat


def lire_tranche(
    action: str, parametres: dict[str, Any], jour: str, racine: Path | None = None
) -> dict | None:
    """Tranche d'un jour deja figee, ou None. Un fichier corrompu vaut une absence."""
    chemin = chemin_tranche(action, parametres, jour, racine)
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def ecrire_tranche(
    action: str,
    parametres: dict[str, Any],
    jour: str,
    payload: dict,
    racine: Path | None = None,
) -> None:
    """Fige la tranche d'un jour revolu. Une ecriture impossible n'est PAS une erreur
    metier : le cache est un confort, l'appel a deja reussi."""
    chemin = chemin_tranche(action, parametres, jour, racine)
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        return
