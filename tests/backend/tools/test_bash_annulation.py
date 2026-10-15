# [desc] Tests that the agent's PowerShell bash tool is killed on cancellation and returns output otherwise [/desc]
from __future__ import annotations

import threading
import time

from bouzecode.backend.core.dossier_agent import Atelier, dans
from bouzecode.backend.tools.ops.shell_search import _bash


def test_bash_long_est_tue_quand_l_agent_est_interrompu(tmp_path):
    drapeau = threading.Event()
    atelier = Atelier(dossier=str(tmp_path), annule=drapeau.is_set)
    threading.Timer(1.5, drapeau.set).start()
    debut = time.time()
    with dans(atelier):
        resultat = _bash("Start-Sleep -Seconds 120", timeout=300)
    duree = time.time() - debut
    assert duree < 30, f"Bash non interrompu ({duree:.0f}s) : {resultat}"
    assert "Error" in resultat


def test_bash_sans_annulation_rend_sa_sortie(tmp_path):
    with dans(Atelier(dossier=str(tmp_path), annule=lambda: False)):
        resultat = _bash("Write-Output bonjour", timeout=60)
    assert "bonjour" in resultat
