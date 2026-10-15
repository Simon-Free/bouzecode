# [desc] Sous Windows, sans bundle CA déclaré, la vérification TLS s'appuie sur le magasin de certificats du système (CA interne corporate compris) au lieu de certifi seul. [/desc]
"""Mesure du 2026-09-29 sur le poste : depuis (vérification toujours active), le gateway
répond CERTIFICATE_VERIFY_FAILED avec certifi seul (CA interne corporate absent), et 200 avec le
magasin Windows. Aucun lanceur ne déclare de bundle ; les agents lancés par un serveur web_v2
déjà démarré n'en hériteraient pas non plus. Sans repli sur le magasin système, tout appel LLM
échouait sur ce poste. La vérification reste active : on change seulement d'autorités."""
from __future__ import annotations

import ssl
import sys
from pathlib import Path

import pytest

from bouzecode.backend.core import tls

pytestmark = pytest.mark.skipif(sys.platform != "win32",
                                reason="magasin de certificats Windows : Windows seulement")


@pytest.fixture(autouse=True)
def _sans_bundle_declare(monkeypatch):
    for var in (tls.INSECURE_ENV, "PYTHONHTTPSVERIFY", "GIT_SSL_CAINFO", *tls.CA_BUNDLE_VARS):
        monkeypatch.delenv(var, raising=False)


def _racines_du_systeme() -> set[str]:
    """Racines approuvées pour authentifier un serveur (toutes usages, ou serverAuth)."""
    return {ssl.DER_cert_to_PEM_cert(der).strip()
            for der, encodage, usages in ssl.enum_certificates("ROOT")
            if encodage == "x509_asn" and (usages is True or "1.3.6.1.5.5.7.3.1" in usages)}


def test_le_bundle_par_defaut_contient_le_magasin_windows_et_certifi():
    import certifi

    chemin = Path(tls.requests_verify("gateway"))
    contenu = chemin.read_text(encoding="ascii")
    racines = _racines_du_systeme()
    assert racines and all(pem in contenu for pem in racines)
    assert Path(certifi.where()).read_text(encoding="ascii").strip()[-200:] in contenu


def test_httpx_et_git_utilisent_le_meme_bundle_verifiant():
    ctx = tls.httpx_verify("gateway")
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    assert ctx.cert_store_stats()["x509_ca"] > 100
    assert tls.git_env({})["GIT_SSL_CAINFO"] == tls.requests_verify("gateway")


def test_des_resolutions_simultanees_d_un_bundle_perime_ne_se_marchent_pas_dessus():
    """ImageQuestion lance 15 appels en parallèle : chacun résolvait le bundle, réécrivait le
    même `.tmp` et `os.replace` échouait (WinError 32, fichier lu par un autre thread)."""
    import os
    import threading

    from bouzecode.backend.core import tls_magasin_windows

    chemin = Path(tls.requests_verify("gateway"))
    os.utime(chemin, (0, 0))   # périmé : chaque appel voudrait le réécrire
    erreurs, depart = [], threading.Barrier(16)

    def resoudre():
        depart.wait()
        try:
            ctx = tls.httpx_verify("gateway")
            assert isinstance(ctx, ssl.SSLContext)
        except Exception as exc:  # noqa: BLE001 — on relève l'échec de chaque thread
            erreurs.append(repr(exc))

    fils = [threading.Thread(target=resoudre) for _ in range(16)]
    for f in fils:
        f.start()
    for f in fils:
        f.join()
    assert erreurs == []
    assert not list(chemin.parent.glob("*.tmp"))
    assert tls_magasin_windows.windows_store_bundle() == str(chemin)


def test_un_bundle_declare_reste_prioritaire(monkeypatch, tmp_path):
    import certifi

    declare = tmp_path / "ca.pem"
    declare.write_bytes(Path(certifi.where()).read_bytes())
    monkeypatch.setenv("SSL_CERT_FILE", str(declare))
    assert tls.requests_verify() == str(declare)


def test_le_repli_insecure_explicite_reste_prioritaire(monkeypatch):
    monkeypatch.setenv(tls.INSECURE_ENV, "1")
    assert tls.requests_verify("gateway") is False
