# [desc] Sanctioned HTTP client for the LOCAL bouzecode server: never proxied, actionable errors. [/desc]
"""Appels HTTP vers le serveur bouzecode LOCAL (BouzéqUI, boucle locale).

POURQUOI CE MODULE EXISTE — panne du 2026-07-28 : le dispatch d'un manager est parti dans
le proxy d'entreprise et a reçu `HTTP Error 407: Proxy Authentication Required`, deux fois,
alors que le même dispatch avait fonctionné vingt minutes plus tôt.

`urllib.request.urlopen` utilise l'opener PAR DÉFAUT, dont le `ProxyHandler` est construit
à partir de l'environnement, et qui ne saute le proxy que si `urllib.request.proxy_bypass()`
dit oui. Sous Windows cette décision repose ENTIÈREMENT sur `NO_PROXY` : le repli registre
est inopérant ici (`ProxyEnable=0`, et l'entrée `<local>` ne matche jamais une IP pointée
comme 127.0.0.1). Le succès d'un appel LOCAL dépendait donc d'une variable d'environnement
qu'aucun code ne garantit — et que chaque respawn d'agent ré-hérite telle quelle.

Quatre environnements à UNE variable près produisent le 407 (mesurés contre le serveur réel) :
  - `NO_PROXY` absent ;
  - `NO_PROXY` présent mais ne couvrant pas la boucle locale ;
  - `NO_PROXY` correct ANNULÉ par un `no_proxy` minuscule VIDE (CPython retire la clé
    lorsqu'une variable `*_proxy` est présente avec une valeur vide) ;
  - `NO_PROXY` ne couvrant que `localhost` alors que l'appel vise l'IP littérale.

La boucle locale n'a par construction AUCUNE raison de traverser un proxy. Cet opener est
donc construit avec `ProxyHandler({})` — une carte de proxys explicitement VIDE, qui ne
consulte NI l'environnement NI le registre. Aucun `NO_PROXY` n'est plus requis.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

# Variables qui feraient partir un appel dans un proxy si l'on utilisait l'opener par
# défaut. Servent UNIQUEMENT au diagnostic : on nomme les variables, JAMAIS leur valeur
# (une URL de proxy peut porter des identifiants).
_PROXY_ENV_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                   "http_proxy", "https_proxy", "all_proxy")


class LocalServerError(RuntimeError):
    """Un appel au serveur bouzecode LOCAL a échoué, avec un diagnostic exploitable.

    Le message distingue toujours les trois causes que « 407 » seul confondait :
    requête partie dans un proxy, serveur qui refuse, serveur injoignable."""


def proxy_vars_in_env(env: dict | None = None) -> list[str]:
    """Noms — jamais valeurs — des variables de proxy présentes dans l'environnement.

    Dédupliqué sur (nom majuscule, valeur) : sous Windows `os.environ` est insensible à la
    casse, donc `http_proxy` et `HTTP_PROXY` désignent la MÊME variable et la nommer deux
    fois brouillerait le diagnostic. Sous POSIX, deux variables de casse différente portant
    des valeurs différentes restent toutes deux listées."""
    env = os.environ if env is None else env
    found: list[str] = []
    seen: set[tuple[str, str]] = set()
    for name in _PROXY_ENV_VARS:
        value = env.get(name)
        if value and (name.upper(), value) not in seen:
            seen.add((name.upper(), value))
            found.append(name)
    return found


def no_proxy_opener() -> urllib.request.OpenerDirector:
    """Opener réservé aux appels LOCAUX.

    `ProxyHandler({})` = carte de proxys explicitement vide. Contrairement à
    `ProxyHandler()` (proxys déduits de `getproxies()`), elle ne consulte ni
    l'environnement ni le registre Windows : la sortie ne dépend d'AUCUNE variable
    d'environnement. Construit à chaque appel plutôt que mis en cache — un opener mémorisé
    au premier appel figerait pour des heures l'état d'un process de longue vie."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def local_json(method: str, url: str, body: dict | None = None,
               timeout: int = 60) -> dict:
    """Appel JSON vers le serveur LOCAL, SANS jamais traverser de proxy.

    Renvoie le corps décodé ({} si la réponse est vide). Toute erreur remonte en
    `LocalServerError` porteuse d'un diagnostic actionnable."""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with no_proxy_opener().open(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise LocalServerError(_http_error_message(exc, url)) from exc
    except urllib.error.URLError as exc:
        raise LocalServerError(
            f"Serveur local INJOIGNABLE sur {url} ({exc.reason}) : personne n'écoute. "
            "Ce n'est ni un refus applicatif ni un proxy — le serveur BouzéqUI est arrêté "
            "ou sur un autre port.") from exc
    return json.loads(raw) if raw.strip() else {}


def _http_error_message(exc: urllib.error.HTTPError, url: str) -> str:
    """Message qui nomme le COUPABLE : le proxy, ou le serveur local lui-même."""
    if exc.code == 407:
        offenders = ", ".join(proxy_vars_in_env()) or "(aucune)"
        return (
            f"407 sur l'appel LOCAL {url} : ta requête est PARTIE DANS UN PROXY. Un serveur "
            f"local ne renvoie jamais 407 — c'est le proxy d'entreprise qui a répondu, la "
            f"requête n'a jamais atteint bouzecode et RIEN n'a été créé côté serveur. "
            f"Variables de proxy présentes dans l'environnement : {offenders}. Le client "
            f"local est pourtant construit sans proxy : voir ce message signifie qu'un "
            f"opener global proxyfiant a été installé (urllib.request.install_opener), ou "
            f"que l'appel n'est pas passé par backend.core.local_http.")
    return (
        f"Le serveur local a REFUSÉ l'appel {url} : HTTP {exc.code} {exc.reason}"
        f"{_server_detail(exc)}. La requête a bien ATTEINT le serveur — aucun proxy en "
        f"cause, corrige l'appel lui-même.")


def _server_detail(exc: urllib.error.HTTPError) -> str:
    """Motif renvoyé par le serveur, extrait de son corps JSON quand il y en a un."""
    raw = exc.read().decode("utf-8", errors="replace").strip()
    if not raw:
        return ""
    if raw.startswith("{") and '"error"' in raw:
        return f" — {json.loads(raw)['error']}"
    return f" — {raw[:200]}"
