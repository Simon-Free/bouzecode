# [desc] testd : une collecte qui dépasse son délai est tuée avec TOUT son arbre de process, et le job tourne quand même, d'un seul tenant, avec une note — jamais « erreur interne du démon » [/desc]
"""Job cd6cf0cd (2026-10-14) : `tests/focus -k …` sur un worktree neuf, collecte > 180 s ;
`subprocess.run(timeout=…)` levait TimeoutExpired, le job finissait en « erreur interne du démon »
sans un test lancé, et seul le process direct était tué."""
from __future__ import annotations

import time

import psutil

from bouzecode.backend.tools.ops.test_runner import run_python_test
from tests.backend.testd.aides import projet

_COLLECTE_LENTE = {
    "conftest.py": """
        import os, subprocess, sys, time
        from pathlib import Path
        if "--collect-only" in sys.argv:
            #  Un petit-enfant (comme un serveur lancé par un conftest) : l'arbre entier doit partir.
            enfant = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"],
                                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            Path(os.environ["BZ_TEST_PIDS"]).write_text(f"{os.getpid()} {enfant.pid}")
            time.sleep(120)
    """,
    "test_rapide.py": "def test_ok():\n    assert True\n",
}


def test_collecte_trop_longue_arbre_tue_et_job_lance_d_un_seul_tenant(demon, tmp_path, monkeypatch):
    pids = tmp_path / "pids.txt"
    monkeypatch.setenv("BZ_TEST_PIDS", str(pids))
    monkeypatch.setenv("BZ_TESTD_COLLECTE_S", "4")
    racine = projet(tmp_path / "p", _COLLECTE_LENTE)
    debut = time.monotonic()
    rendu = run_python_test(targets=[str(racine / "test_rapide.py")], parallel="off")
    assert time.monotonic() - debut < 60, rendu
    assert "collecte interrompue après 4 s (arbre de process tué)" in rendu, rendu
    assert "1 passed" in rendu and "erreur interne" not in rendu, rendu
    collecte, petit_enfant = (int(p) for p in pids.read_text().split())
    fin = time.monotonic() + 10
    while (psutil.pid_exists(collecte) or psutil.pid_exists(petit_enfant)) and time.monotonic() < fin:
        time.sleep(0.2)
    assert not psutil.pid_exists(collecte) and not psutil.pid_exists(petit_enfant)
