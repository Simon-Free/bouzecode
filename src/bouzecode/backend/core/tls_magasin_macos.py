"""Magasin de certificats macOS exporté en bundle PEM (autorités internes comprises).

Symétrique de `tls_magasin_windows` : sur un poste macOS d'entreprise, les autorités
internes (AC RACINE / AC INFRASTRUCTURE corporate…) vivent dans le keychain système et sont
invisibles pour certifi — tout hôte interne en HTTPS échoue alors en
CERTIFICATE_VERIFY_FAILED. On les exporte, au plus une fois par 24 h, dans
`~/.bouzecode/tls/magasin_macos.pem`, concaténées à certifi : le bundle déclaré à
httpx/requests/git REMPLACE le magasin par défaut, il doit donc porter aussi les
autorités publiques.
"""

from __future__ import annotations

import logging
import os
import ssl
import subprocess
import sys
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_MAX_AGE_S = 24 * 3600
_write_lock = threading.Lock()

SYSTEM_KEYCHAIN = "/Library/Keychains/System.keychain"
_SECURITY = "/usr/bin/security"
_END = "-----END CERTIFICATE-----"


def _bundle_path() -> Path:
    # Lu à l'appel (pas figé à l'import) : suit le HOME courant.
    return Path.home() / ".bouzecode" / "tls" / "magasin_macos.pem"


def _is_fresh(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0 and time.time() - path.stat().st_mtime < _MAX_AGE_S


def macos_store_bundle() -> str | None:
    """Chemin du PEM (keychain système + certifi), ou None hors macOS."""
    if sys.platform != "darwin" or not os.path.exists(_SECURITY):
        return None
    path = _bundle_path()
    # Un seul écrivain par process : ImageQuestion résout le bundle depuis 15 threads à la fois.
    with _write_lock:
        if not _is_fresh(path):
            try:
                _write_bundle(path)
            except Exception as exc:  # keychain verrouillé, disque plein… : on ne casse rien
                logger.warning("TLS : export du keychain macOS impossible (%s), repli certifi.", exc)
                return str(path) if path.is_file() else None
    return str(path)


def _pem_blocks(text: str) -> list[str]:
    """Découpe une suite de PEM concaténés en blocs complets, un certificat chacun."""
    blocs, reste = [], text
    while _END in reste:
        tete, _, reste = reste.partition(_END)
        debut = tete.find("-----BEGIN CERTIFICATE-----")
        if debut != -1:
            blocs.append(tete[debut:] + _END + "\n")
    return blocs


def _is_authority(pem: str) -> bool:
    """Vrai si ce PEM est une CA : le store `ssl` ne compte en `x509_ca` que celles-là.

    Pourquoi `ssl` et pas `cryptography` : stdlib seule (cryptography n'est pas une
    dépendance), et `ssl.enum_certificates` n'existe que sous Windows.
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    try:
        ctx.load_verify_locations(cadata=pem)
    except ssl.SSLError:
        return False
    return ctx.cert_store_stats()["x509_ca"] == 1


def _system_pems() -> list[str]:
    """Les autorités du keychain système, en PEM. Les feuilles sont écartées."""
    try:
        sortie = subprocess.run(
            [_SECURITY, "find-certificate", "-a", "-p", SYSTEM_KEYCHAIN],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("TLS : `security find-certificate` a échoué (%s).", exc)
        return []
    if sortie.returncode != 0:
        logger.warning("TLS : `security find-certificate` code %s.", sortie.returncode)
        return []
    return [pem for pem in _pem_blocks(sortie.stdout) if _is_authority(pem)]


def _write_bundle(path: Path) -> None:
    import certifi

    autorites = _system_pems()
    if not autorites:
        raise RuntimeError(f"aucune autorité trouvée dans {SYSTEM_KEYCHAIN}")
    content = "".join(autorites) + Path(certifi.where()).read_text(encoding="utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)
