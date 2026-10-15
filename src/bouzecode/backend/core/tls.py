# [desc] Point unique de la vérification TLS des clients HTTP sortants : bundle CA, repli explicite et journalisé. [/desc]
"""Vérification TLS des appels sortants (gateway IA, OpenRouter, GitLab).

AVANT : chaque backend lisait `PYTHONHTTPSVERIFY=0` et coupait la
vérification, et les lanceurs posaient cette variable d'office. Une variable
d'environnement héritée suffisait donc à accepter n'importe quel certificat
(interception sur le proxy, poste compromis), sans la moindre trace.

MAINTENANT :
  - la vérification est TOUJOURS active par défaut ;
  - le proxy corporate à certificat interne se traite en fournissant le bundle CA :
    `REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE`, `CURL_CA_BUNDLE` puis `BOUZECODE_CA_BUNDLE`
    (premier fichier existant) ;
  - `PYTHONHTTPSVERIFY=0` n'a plus AUCUN effet (trace DEBUG une fois) ;
  - repli poste de dev uniquement : `BOUZECODE_TLS_INSECURE=1` coupe la
    vérification, avec un avertissement une fois par process et par client ;
  - en profil serveur (`BOUZECODE_SERVER_PROFILE`), ce repli est IGNORÉ (erreur
    journalisée) : un App Setting oublié ne doit pas couper TLS en production.

`requests_verify()` rend ce qu'attend `requests` (`verify=`), `httpx_verify()`
un `ssl.SSLContext` pour httpx/httpx2 (`verify=<str>` y est déprécié),
`git_env()` les variables équivalentes pour `git`.

Les avertissements sont émis paresseusement, à la première requête HTTP : sans
handler configuré, `logging.lastResort` les écrit sur stderr, donc au milieu du
chat du REPL. D'où la règle : chaque message au plus une fois par process.
"""
from __future__ import annotations

import logging
import os
import ssl

logger = logging.getLogger(__name__)

INSECURE_ENV = "BOUZECODE_TLS_INSECURE"
CA_BUNDLE_VARS = ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "CURL_CA_BUNDLE", "BOUZECODE_CA_BUNDLE")

_warned_legacy = False
_warned_insecure: set[str] = set()
_warned_missing: set[tuple[str, str]] = set()


def insecure_opt_in() -> bool:
    """Vrai seulement si le repli poste de dev est demandé explicitement."""
    return (os.environ.get(INSECURE_ENV) or "").strip().lower() in ("1", "true", "yes", "oui")


def ca_bundle() -> str | None:
    """Premier bundle CA déclaré qui existe réellement ; à défaut, sous Windows, le magasin du
    système exporté (CA interne corporate compris) ; sinon None (certifi)."""
    for var in CA_BUNDLE_VARS:
        path = (os.environ.get(var) or "").strip()
        if not path:
            continue
        if os.path.exists(path):
            return path
        if (var, path) not in _warned_missing:
            _warned_missing.add((var, path))
            logger.warning("TLS : %s=%s introuvable, variable ignorée.", var, path)
    from .tls_magasin_macos import macos_store_bundle
    from .tls_magasin_windows import windows_store_bundle

    return windows_store_bundle() or macos_store_bundle()


def _warn_legacy_switch() -> None:
    global _warned_legacy
    if _warned_legacy or (os.environ.get("PYTHONHTTPSVERIFY") or "").strip() != "0":
        return
    _warned_legacy = True
    logger.debug(
        "TLS : PYTHONHTTPSVERIFY=0 est ignoré, la vérification des certificats reste active. "
        "Fournir le bundle CA interne (SSL_CERT_FILE / REQUESTS_CA_BUNDLE) ; sur un poste de dev "
        "seulement, %s=1 coupe la vérification.", INSECURE_ENV)


def _insecure(client: str) -> bool:
    _warn_legacy_switch()
    if not insecure_opt_in():
        return False
    from .server_profile import SERVER_PROFILE_ENV, server_profile_active

    if server_profile_active():
        logger.error(
            "TLS : %s=1 IGNORÉ pour %s : le profil serveur (%s) est actif, la vérification "
            "des certificats reste obligatoire. Retirer ce réglage de l'hébergement.",
            INSECURE_ENV, client, SERVER_PROFILE_ENV)
        return False
    if client not in _warned_insecure:
        _warned_insecure.add(client)
        logger.warning(
            "TLS : vérification des certificats DÉSACTIVÉE pour %s (%s=1). "
            "Réservé au poste de dev, jamais en production.", client, INSECURE_ENV)
    return True


def requests_verify(client: str = "requests"):
    """Valeur `verify=` pour requests : chemin du bundle CA, True, ou False sur opt-in."""
    if _insecure(client):
        return False
    return ca_bundle() or True


def httpx_verify(client: str = "httpx"):
    """Valeur `verify=` pour httpx/httpx2 : SSLContext sur le bundle CA, True, ou False sur opt-in."""
    if _insecure(client):
        return False
    bundle = ca_bundle()
    if bundle is None:
        return True
    if os.path.isdir(bundle):
        return ssl.create_default_context(capath=bundle)
    return ssl.create_default_context(cafile=bundle)


def git_env(env: dict | None = None) -> dict:
    """Variables TLS pour un sous-processus git : bundle CA, ou GIT_SSL_NO_VERIFY sur opt-in."""
    out = dict(os.environ if env is None else env)
    out.pop("GIT_SSL_NO_VERIFY", None)
    if _insecure("git"):
        out["GIT_SSL_NO_VERIFY"] = "1"
        return out
    bundle = ca_bundle()
    if bundle and not out.get("GIT_SSL_CAINFO") and os.path.isfile(bundle):
        out["GIT_SSL_CAINFO"] = bundle
    return out


class TlsVerificationError(RuntimeError):
    """Certificat serveur refusé : message actionnable plutôt que des reprises inutiles."""


def certificate_error_hint(exc: BaseException) -> str | None:
    """Message explicite si `exc` (ou sa cause) est un échec de vérification de certificat."""
    seen = set()
    cur = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(cur):
            return (
                f"Vérification du certificat TLS refusée ({type(exc).__name__}). Derrière le proxy "
                "corporate, fournir le bundle CA interne via SSL_CERT_FILE / REQUESTS_CA_BUNDLE (ou "
                "BOUZECODE_CA_BUNDLE dans .env). Ce bundle REMPLACE le magasin par défaut : il doit "
                "contenir aussi les autorités publiques (certifi + CA interne), sinon les hôtes "
                "joints sans interception échouent. PYTHONHTTPSVERIFY=0 n'est plus honoré ; "
                f"repli poste de dev uniquement : {INSECURE_ENV}=1.")
        cur = cur.__cause__ or cur.__context__
    return None
