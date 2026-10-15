# [desc] Teste le repli TLS sur le magasin de certificats macOS (keychain + certifi) pour les hôtes internes [/desc]
"""Mesure du 2026-10-01 sur le poste macOS de l'utilisateur : `ANTHROPIC_BASE_URL` vaut
`https://llm-gateway.example.com`, hôte interne, et `.example.com` est dans `NO_PROXY` — il est donc joint
en direct. Son certificat est émis par `AC INFRASTRUCTURE corporate 2023`, absente de certifi, et le
serveur n'envoie pas l'intermédiaire (`openssl verify` : code 21). Résultat : tout appel LLM
échouait en `CERTIFICATE_VERIFY_FAILED` -> `anthropic.APIConnectionError`.

Le repli « magasin de certificats du système » n'existait que sous Windows
(`tls_magasin_windows`) : sous macOS `ca_bundle()` renvoyait None, donc certifi seul, donc échec
garanti sur tout hôte interne. Les AC corporate sont pourtant présentes dans
`/Library/Keychains/System.keychain`, et un bundle fusionné (keychain + certifi) valide à la
fois `llm-gateway.example.com` et `api.anthropic.com`. La vérification reste active : on change
seulement d'autorités.
"""
from __future__ import annotations

import ssl
import subprocess
import sys
from pathlib import Path

import pytest

from bouzecode.backend.core import tls

pytestmark = pytest.mark.skipif(sys.platform != "darwin",
                                reason="magasin de certificats macOS : macOS seulement")

_SYSTEM_KEYCHAIN = "/Library/Keychains/System.keychain"


@pytest.fixture(autouse=True)
def _sans_bundle_declare(monkeypatch):
    for var in (tls.INSECURE_ENV, "PYTHONHTTPSVERIFY", "GIT_SSL_CAINFO", *tls.CA_BUNDLE_VARS):
        monkeypatch.delenv(var, raising=False)


def _blocs_pem(texte: str) -> list[str]:
    blocs, courant = [], None
    for ligne in texte.splitlines():
        if ligne.startswith("-----BEGIN CERTIFICATE-----"):
            courant = [ligne]
        elif courant is not None:
            courant.append(ligne)
            if ligne.startswith("-----END CERTIFICATE-----"):
                blocs.append("\n".join(courant))
                courant = None
    return blocs


def _est_autorite(pem: str) -> bool:
    """Vrai si ce PEM est une CA : le store `ssl` ne compte en `x509_ca` que celles-là."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    try:
        ctx.load_verify_locations(cadata=pem + "\n")
    except ssl.SSLError:
        return False
    return ctx.cert_store_stats()["x509_ca"] == 1


def _autorites_du_keychain() -> set[str]:
    """Autorités du magasin système, relues indépendamment de l'implémentation testée."""
    sortie = subprocess.run(["security", "find-certificate", "-a", "-p", _SYSTEM_KEYCHAIN],
                            capture_output=True, text=True, check=False).stdout
    return {pem for pem in _blocs_pem(sortie) if _est_autorite(pem)}


def test_le_bundle_par_defaut_contient_le_magasin_macos_et_certifi():
    import certifi

    autorites = _autorites_du_keychain()
    if not autorites:
        pytest.skip(f"aucune autorité dans {_SYSTEM_KEYCHAIN} sur ce poste")

    chemin = Path(tls.requests_verify("gateway"))
    assert chemin.is_file()
    contenu = chemin.read_text(encoding="utf-8")
    manquantes = [pem for pem in autorites if pem not in contenu]
    assert not manquantes, f"{len(manquantes)} autorité(s) du keychain absente(s) du bundle"
    assert Path(certifi.where()).read_text(encoding="utf-8").strip()[-200:] in contenu


def test_httpx_et_git_utilisent_le_meme_bundle_verifiant():
    ctx = tls.httpx_verify("gateway")
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    assert ctx.cert_store_stats()["x509_ca"] > 100
    assert tls.git_env({})["GIT_SSL_CAINFO"] == tls.requests_verify("gateway")


def test_des_resolutions_simultanees_d_un_bundle_perime_ne_se_marchent_pas_dessus():
    """ImageQuestion résout le bundle depuis 15 threads à la fois : un seul écrivain."""
    import os
    import threading

    from bouzecode.backend.core import tls_magasin_macos

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
    assert tls_magasin_macos.macos_store_bundle() == str(chemin)


def test_un_bundle_declare_reste_prioritaire(monkeypatch, tmp_path):
    import certifi

    declare = tmp_path / "ca.pem"
    declare.write_bytes(Path(certifi.where()).read_bytes())
    monkeypatch.setenv("SSL_CERT_FILE", str(declare))
    assert tls.requests_verify() == str(declare)


def test_le_repli_insecure_explicite_reste_prioritaire(monkeypatch):
    monkeypatch.setenv(tls.INSECURE_ENV, "1")
    assert tls.requests_verify("gateway") is False
