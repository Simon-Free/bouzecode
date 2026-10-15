# [desc] PYTHONHTTPSVERIFY=0 ne coupe plus la vérification TLS ; bundle CA honoré ; repli BOUZECODE_TLS_INSECURE=1 journalisé une fois ; rien au niveau WARNING pour PYTHONHTTPSVERIFY ; plus de disable_warnings ni de GIT_SSL_NO_VERIFY. [/desc]
"""Vérification TLS des clients sortants.

Avant : `PYTHONHTTPSVERIFY=0` (posé d'office par les lanceurs) coupait la vérification
de tous les backends, et `openrouter_stream` faisait taire l'avertissement urllib3.
Chaque test ci-dessous échoue sur ce comportement-là.
"""
from __future__ import annotations

import logging
import ssl
from pathlib import Path

import pytest

from bouzecode.backend.core import tls

_REPO = Path(__file__).resolve().parents[3]
_TLS_VARS = ("PYTHONHTTPSVERIFY", tls.INSECURE_ENV, "GIT_SSL_NO_VERIFY", "GIT_SSL_CAINFO",
             "BOUZECODE_SERVER_PROFILE", "BOUZECODE_ALLOWED_PROVIDERS", *tls.CA_BUNDLE_VARS)


@pytest.fixture(autouse=True)
def _clean_tls_env(monkeypatch):
    for var in _TLS_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(tls, "_warned_legacy", False)
    monkeypatch.setattr(tls, "_warned_insecure", set())
    monkeypatch.setattr(tls, "_warned_missing", set())


@pytest.fixture
def bundle(tmp_path):
    """Un bundle CA réel (celui de certifi) recopié : `ssl` doit pouvoir le charger."""
    import certifi

    path = tmp_path / "ca_interne.pem"
    path.write_bytes(Path(certifi.where()).read_bytes())
    return path


def _verifie(verify) -> bool:
    """Vérification active : certifi (True), un bundle CA existant (chemin, p. ex. le magasin
    Windows exporté par défaut) ou un SSLContext exigeant le certificat — jamais False."""
    if isinstance(verify, ssl.SSLContext):
        return verify.verify_mode == ssl.CERT_REQUIRED and verify.check_hostname
    return verify is True or (isinstance(verify, str) and Path(verify).is_file())


def test_pythonhttpsverify_0_ne_coupe_plus_la_verification(monkeypatch, caplog):
    monkeypatch.setenv("PYTHONHTTPSVERIFY", "0")
    with caplog.at_level(logging.DEBUG, logger=tls.__name__):
        assert _verifie(tls.requests_verify())
        assert _verifie(tls.httpx_verify())
    traces = [r for r in caplog.records if "PYTHONHTTPSVERIFY=0 est ignoré" in r.getMessage()]
    assert [r.levelno for r in traces] == [logging.DEBUG]


def test_pythonhttpsverify_0_rien_au_niveau_warning_dans_le_chat(monkeypatch, caplog):
    """Sans handler, logging.lastResort écrit tout WARNING sur stderr, au milieu du REPL."""
    monkeypatch.setenv("PYTHONHTTPSVERIFY", "0")
    with caplog.at_level(logging.WARNING, logger=tls.__name__):
        tls.requests_verify()
    assert caplog.records == []


def test_bundle_ca_honore_pour_requests_et_httpx(monkeypatch, bundle):
    monkeypatch.setenv("SSL_CERT_FILE", str(bundle))
    assert tls.requests_verify() == str(bundle)
    ctx = tls.httpx_verify()
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname


def test_requests_ca_bundle_prioritaire_et_fichier_absent_ignore(monkeypatch, bundle, tmp_path):
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(tmp_path / "absent.pem"))
    monkeypatch.setenv("BOUZECODE_CA_BUNDLE", str(bundle))
    assert tls.requests_verify() == str(bundle)


def test_repli_explicite_journalise(monkeypatch, caplog):
    monkeypatch.setenv(tls.INSECURE_ENV, "1")
    with caplog.at_level(logging.WARNING, logger=tls.__name__):
        assert tls.requests_verify("OpenRouter") is False
    assert "DÉSACTIVÉE pour OpenRouter" in caplog.text


def test_repli_explicite_un_seul_avertissement_par_client(monkeypatch, caplog):
    monkeypatch.setenv(tls.INSECURE_ENV, "1")
    with caplog.at_level(logging.WARNING, logger=tls.__name__):
        assert tls.requests_verify("OpenRouter") is False
        assert tls.requests_verify("OpenRouter") is False
        assert tls.httpx_verify("gateway") is False
    clients = [r.args[0] for r in caplog.records if r.levelno == logging.WARNING]
    assert clients == ["OpenRouter", "gateway"]


def test_bundle_absent_signale_une_seule_fois(monkeypatch, caplog, tmp_path):
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(tmp_path / "absent.pem"))
    with caplog.at_level(logging.WARNING, logger=tls.__name__):
        tls.requests_verify()
        tls.requests_verify()
    assert len([r for r in caplog.records if "introuvable" in r.getMessage()]) == 1


def test_git_env_retire_git_ssl_no_verify_et_passe_le_bundle(monkeypatch, bundle):
    monkeypatch.setenv("GIT_SSL_NO_VERIFY", "1")
    monkeypatch.setenv("SSL_CERT_FILE", str(bundle))
    env = tls.git_env()
    assert "GIT_SSL_NO_VERIFY" not in env
    assert env["GIT_SSL_CAINFO"] == str(bundle)


def test_gitlab_resolve_ne_desactive_plus_tls(monkeypatch):
    from bouzecode.backend.core import gitlab_resolve

    seen = {}

    def fake_run(cmd, capture_output, text, env):
        seen.update(env)

        class _P:
            returncode, stdout, stderr = 0, "", ""
        return _P()

    monkeypatch.setattr(gitlab_resolve.subprocess, "run", fake_run)
    gitlab_resolve._git("status")
    assert "GIT_SSL_NO_VERIFY" not in seen
    assert seen["GIT_TERMINAL_PROMPT"] == "0"


def test_client_anthropic_verifie_malgre_pythonhttpsverify(monkeypatch):
    from bouzecode.backend.agent.providers.backends import anthropic_client

    captured = {}
    real = anthropic_client._httpx_module_for()

    class _Transport(real.HTTPTransport):
        def __init__(self, **kw):
            captured.update(kw)
            super().__init__(**kw)

    fake = type("M", (), {"Client": real.Client, "Timeout": real.Timeout, "HTTPTransport": _Transport})
    monkeypatch.setattr(anthropic_client, "_httpx_module_for", lambda *a: fake)
    monkeypatch.setenv("PYTHONHTTPSVERIFY", "0")
    anthropic_client.build_anthropic_client("cle-de-test", None)
    assert _verifie(captured["verify"])


def test_readme_sync_verifie_malgre_pythonhttpsverify(monkeypatch, bundle):
    from readme_sync import regen

    monkeypatch.setenv("PYTHONHTTPSVERIFY", "0")
    assert regen._tls_verify() is True
    monkeypatch.setenv("SSL_CERT_FILE", str(bundle))
    assert isinstance(regen._tls_verify(), ssl.SSLContext)
    monkeypatch.setenv(tls.INSECURE_ENV, "1")
    assert regen._tls_verify() is False


def test_openrouter_stream_verifie_et_ne_fait_plus_taire_urllib3():
    src = (_REPO / "src/bouzecode/backend/agent/providers/backends/openrouter_stream.py").read_text(
        encoding="utf-8")
    assert "disable_warnings" not in src.replace("plus de urllib3.disable_warnings", "")
    assert 'os.environ.get("PYTHONHTTPSVERIFY"' not in src
    assert "verify = requests_verify(" in src


@pytest.mark.parametrize("launcher", [
    "bouzecode.sh", "bouzecode.ps1", "bouzeui.sh", "bouzeui.ps1",
    "scripts/bouzeui.sh", "scripts/bouzeui.ps1",
])
def test_lanceurs_ne_posent_plus_pythonhttpsverify(launcher):
    text = (_REPO / launcher).read_text(encoding="utf-8-sig")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert "PYTHONHTTPSVERIFY" not in code
    assert "SSL_CERT_FILE" in code


def test_certificat_refuse_openrouter_message_explicite_sans_reprises():
    import requests

    from bouzecode.backend.agent.providers.backends.openrouter_retry import post_with_retry

    calls, sleeps = [], []

    def post_once():
        calls.append(1)
        raise requests.exceptions.SSLError(
            "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate")

    with pytest.raises(tls.TlsVerificationError) as info:
        post_with_retry(post_once, sleep=sleeps.append)
    assert "SSL_CERT_FILE" in str(info.value) and tls.INSECURE_ENV in str(info.value)
    assert len(calls) == 1 and not sleeps


def test_certificat_refuse_anthropic_message_explicite_sans_reprises():
    import anthropic
    import httpx

    from bouzecode.backend.agent.providers.backends.anthropic_helpers import (
        _create_anthropic_stream_with_retry,
    )

    request = httpx.Request("POST", "https://gateway.invalid/v1/messages")
    calls, warnings, sleeps = [], [], []

    class _Client:
        class messages:
            @staticmethod
            def create(**kw):
                calls.append(1)
                try:
                    raise ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED]")
                except ssl.SSLCertVerificationError as cause:
                    raise anthropic.APIConnectionError(request=request) from cause

    with pytest.raises(anthropic.APIConnectionError):
        _create_anthropic_stream_with_retry(_Client, {}, sleep=sleeps.append, warn=warnings.append)
    assert len(calls) == 1 and not sleeps
    assert any("SSL_CERT_FILE" in w for w in warnings)


def test_repli_insecure_ignore_en_profil_serveur(monkeypatch, caplog):
    """Un App Setting BOUZECODE_TLS_INSECURE=1 oublié ne coupe pas TLS dans un process hébergé."""
    monkeypatch.setenv(tls.INSECURE_ENV, "1")
    monkeypatch.setenv("BOUZECODE_SERVER_PROFILE", "1")
    with caplog.at_level(logging.ERROR):
        assert _verifie(tls.requests_verify("gateway"))
        assert _verifie(tls.httpx_verify("gateway"))
        assert "GIT_SSL_NO_VERIFY" not in tls.git_env({})
    assert "IGNORÉ" in caplog.text


def test_client_anthropic_passe_verify_au_client_pour_les_montages_proxy(monkeypatch, bundle):
    """Avec HTTPS_PROXY, httpx monte des transports proxy qui prennent le verify du CLIENT."""
    from bouzecode.backend.agent.providers.backends import anthropic_client

    captured = {}
    real = anthropic_client._httpx_module_for()

    class _Client(real.Client):
        def __init__(self, **kw):
            captured.update(kw)
            super().__init__(**kw)

    fake = type("M", (), {"Client": _Client, "Timeout": real.Timeout, "HTTPTransport": real.HTTPTransport})
    monkeypatch.setattr(anthropic_client, "_httpx_module_for", lambda *a: fake)
    monkeypatch.setenv("SSL_CERT_FILE", str(bundle))
    anthropic_client.build_anthropic_client("cle-de-test", None)
    assert isinstance(captured.get("verify"), ssl.SSLContext)


def test_message_de_certificat_refuse_exige_un_bundle_complet():
    hint = tls.certificate_error_hint(ssl.SSLCertVerificationError("CERTIFICATE_VERIFY_FAILED"))
    assert hint and "autorités publiques" in hint and "certifi +" in hint


def test_clients_directs_respectent_la_liste_blanche_des_fournisseurs(monkeypatch):
    """readme_sync joint ANTHROPIC_BASE_URL hors de dispatch.stream ;
    BOUZECODE_ALLOWED_PROVIDERS s'y applique aussi."""
    import anthropic
    import httpx

    from readme_sync import regen

    monkeypatch.setattr(httpx, "Client", lambda **kw: object())
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: kw)
    monkeypatch.setenv("BOUZECODE_ALLOWED_PROVIDERS", "gateway_openai")
    with pytest.raises(RuntimeError, match="BOUZECODE_ALLOWED_PROVIDERS"):
        regen._make_client()
    monkeypatch.setenv("BOUZECODE_ALLOWED_PROVIDERS", "anthropic,gateway_openai")
    assert regen._make_client()
