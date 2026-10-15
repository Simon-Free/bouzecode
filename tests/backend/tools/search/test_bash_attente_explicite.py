"""Une commande qui ANNONCE son attente n'est pas tuée avant la fin de cette attente.

Constat (session 3799b8e2, poste Windows) : une boucle PowerShell bornée par
`(Get-Date).AddSeconds(275)` a été tuée à 180 s — le délai par défaut — parce que le modèle
n'avait pas répété 275 dans le paramètre `timeout`. Tour perdu, et le téléchargement surveillé
a dû être re-sondé.
"""
import sys

import pytest

from bouzecode.backend.tools.ops import shell_search
from bouzecode.backend.tools.ops.shell_search import attente_explicite, bash_handler

_POLL = ('$target = Join-Path $env:LOCALAPPDATA "ms-playwright\\chromium-1234"\n'
         '$deadline = (Get-Date).AddSeconds(275)\n'
         'while ((Get-Date) -lt $deadline) { if (Test-Path $target) { break } ; '
         'Start-Sleep -Seconds 10 }')


@pytest.mark.parametrize("commande,attendu", [
    (_POLL, 275),
    ("Start-Sleep -Seconds 400 ; Get-Date", 400),
    ("Start-Sleep 90", 90),
    ("Start-Sleep -s 200", 200),
    ("sleep 300 && echo ok", 300),
    ("timeout /t 250 /nobreak", 250),
    ("Start-Sleep -Milliseconds 500", 0),
    ("git status", 0),
])
def test_attente_explicite(commande, attendu):
    assert attente_explicite(commande) == attendu


@pytest.mark.skipif(sys.platform == "win32", reason="sleep POSIX")
def test_le_delai_par_defaut_couvre_lattente_annoncee(monkeypatch):
    monkeypatch.setattr(shell_search, "_DEFAULT_BASH_TIMEOUT", 1)
    out = bash_handler({"command": "sleep 2 ; echo fini"}, {})
    assert "fini" in out
    assert "timed out" not in out


@pytest.mark.skipif(sys.platform == "win32", reason="sleep POSIX")
def test_un_timeout_explicite_plus_long_est_respecte_tel_quel(monkeypatch):
    seen = {}
    monkeypatch.setattr(shell_search, "_bash", lambda c, t: seen.setdefault("t", t) and "")
    bash_handler({"command": "sleep 5", "timeout": 900}, {})
    assert seen["t"] == 900
