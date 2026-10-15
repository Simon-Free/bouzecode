# [desc] Bundle CA par défaut sous Windows : magasins ROOT et CA du système + certifi, exportés en PEM et mis en cache (CA interne corporate compris). [/desc]
"""Sous Windows, certifi ne connaît pas l'autorité interne corporate : avec la vérification TLS
toujours active, le gateway répondait CERTIFICATE_VERIFY_FAILED (mesuré le 2026-09-29),
alors que le magasin de certificats du système la contient. On exporte ce magasin (plus
certifi, pour les hôtes publics) dans un PEM unique, utilisable tel quel par requests, httpx
et git. Rafraîchi au plus une fois par jour."""
from __future__ import annotations
from bouzecode.paths import data_dir as bouzecode_data_dir

import os
import ssl
import sys
import threading
import time
from pathlib import Path

_MAX_AGE_S = 24 * 3600
_write_lock = threading.Lock()
_SERVER_AUTH_OID = "1.3.6.1.5.5.7.3.1"


def _bundle_path() -> Path:
    # Lu à l'appel (pas figé à l'import) : suit le HOME courant.
    return bouzecode_data_dir() / "tls" / "magasin_windows.pem"


def _system_pems() -> list[str]:
    pems = []
    for store in ("ROOT", "CA"):
        for der, encoding, trust in ssl.enum_certificates(store):
            if encoding != "x509_asn":
                continue
            if trust is True or _SERVER_AUTH_OID in trust:
                pems.append(ssl.DER_cert_to_PEM_cert(der))
    return pems


def _is_fresh(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0 and time.time() - path.stat().st_mtime < _MAX_AGE_S


def windows_store_bundle() -> str | None:
    """Chemin du PEM (magasin Windows + certifi), ou None hors Windows."""
    if sys.platform != "win32":
        return None
    path = _bundle_path()
    # Un seul écrivain par process : ImageQuestion résout le bundle depuis 15 threads à la fois.
    with _write_lock:
        if not _is_fresh(path):
            _write_bundle(path)
    return str(path)


def _write_bundle(path: Path) -> None:
    import certifi

    content = "".join(_system_pems()) + Path(certifi.where()).read_text(encoding="ascii")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(content, encoding="ascii")
    try:
        os.replace(tmp, path)
    except PermissionError:
        # Windows refuse de remplacer un fichier qu'un AUTRE process lit à cet instant : ce
        # process vient de l'écrire ou de le relire, il est donc présent et à jour.
        tmp.unlink()
        if not path.is_file():
            raise
