# [desc] Aucune migration de boot n'écrit dans le store du vrai HOME hors du serveur de référence (create_app d'un script d'agent, 2026-10-06), et le bac à sable refuse un HOME non isolé. [/desc]
"""Incident du 2026-10-06, 08:54:02 (heure locale) : un agent a lancé
`python -c "from bouzecode.web_v2.app import create_app; a=create_app(); ..."` depuis son worktree,
avec le vrai HOME, pour lister les routes. `create_app()` a migré le vrai store au format L2.

Le « vrai HOME » d'un sous-processus lancé ici est un dossier jetable : HORS de pytest (pas de
`BZ_TESTS_VRAI_HOME`), son `Path.home()` EST son vrai HOME — exactement la situation du script
de l'agent, sans jamais toucher au profil réel."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from bouzecode.web_v2 import migrations_au_boot

RACINE = Path(__file__).resolve().parent.parent
TIMEOUT_S = 120
ATTENTE_REFUS = "migrations de boot NON jouées"


def _store_ancien(home: Path) -> Path:
    """Un store d'avant L2 (runs dans le JSON, pas de colonne `version`) au HOME donné."""
    dossier = home / ".bouzecode" / "web_v2" / "tickets"
    dossier.mkdir(parents=True)
    base = dossier / "tickets.db"
    conn = sqlite3.connect(base)
    conn.execute("CREATE TABLE tickets (seq INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT NOT"
                 " NULL, id TEXT NOT NULL, data TEXT NOT NULL, UNIQUE(slug, id))")
    ticket = {"id": "ancien01", "title": "t", "prompt": "p", "created_at": "2099-01-01T00:00:00",
              "done": True, "closed": {"outcome": "accepted"}, "runs": []}
    conn.execute("INSERT INTO tickets(slug, id, data) VALUES('p', 'ancien01', ?)", (json.dumps(ticket),))
    conn.commit()
    conn.close()
    return base


def _hors_pytest(home: Path, code: str) -> subprocess.CompletedProcess:
    """Lance `code` dans un python HORS pytest dont le vrai HOME est `home`."""
    env = {k: v for k, v in os.environ.items() if k != "BZ_TESTS_VRAI_HOME"}
    env.update(HOME=str(home), USERPROFILE=str(home), PYTHONPATH=str(RACINE / "src"),
               PYTHONIOENCODING="utf-8", BOUZECODE_WAKE_POLLER="0")
    return subprocess.run([sys.executable, "-c", code], cwd=str(home), env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT_S)


def _migrations_notees(base: Path) -> list:
    conn = sqlite3.connect(f"file:{base}?mode=ro", uri=True)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    notees = conn.execute("SELECT nom FROM store_migrations").fetchall() if "store_migrations" in tables else []
    conn.close()
    return notees


def test_create_app_d_un_script_ne_migre_pas_le_store_du_vrai_home(tmp_path):
    """Le geste exact de l'agent : create_app() hors de main(), avec le vrai HOME."""
    base = _store_ancien(tmp_path)
    fini = _hors_pytest(tmp_path, "from bouzecode.web_v2.app import create_app; create_app()")
    assert fini.returncode == 0, fini.stderr
    assert _migrations_notees(base) == [], "le store du vrai HOME a été migré hors du serveur de référence"
    assert ATTENTE_REFUS in fini.stderr, fini.stderr


def test_le_serveur_de_reference_migre_le_store_au_boot(tmp_path):
    """`main()` prend le verrou de référence AVANT create_app() : lui migre, comme avant."""
    base = _store_ancien(tmp_path)
    code = ("from bouzecode.web_v2 import reference; assert reference.acquerir(0); "
            "from bouzecode.web_v2.app import create_app; create_app()")
    fini = _hors_pytest(tmp_path, code)
    assert fini.returncode == 0, fini.stderr
    assert _migrations_notees(base) == [("l2_etat_unique",)], fini.stderr


def test_pendant_les_tests_le_store_n_est_jamais_celui_du_vrai_home():
    """Sous pytest, le store courant est hors du vrai HOME : les migrations de boot des tests
    (create_app in-process) ne peuvent pas viser le profil réel."""
    assert os.environ.get("BZ_TESTS_VRAI_HOME"), "pytest_home_etanche n'est pas chargé"
    assert not migrations_au_boot.store_du_vrai_home()
    assert migrations_au_boot.autorisees()


def _bac_a_sable(home_du_bac: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "BZ_SANDBOX_HOME": home_du_bac, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, str(RACINE / "tests/sandbox/run_sandbox.py"), "status"],
                          env=env, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=TIMEOUT_S)


def test_le_bac_a_sable_refuse_le_vrai_home_et_son_store():
    vrai = os.environ["BZ_TESTS_VRAI_HOME"]
    for home_du_bac in (vrai, str(Path(vrai) / ".bouzecode" / "bac")):
        fini = _bac_a_sable(home_du_bac)
        assert fini.returncode != 0, f"{home_du_bac} accepté :\n{fini.stdout}"
        assert "REFUS" in fini.stderr and "isolé" in fini.stderr, fini.stderr


def test_le_bac_a_sable_accepte_un_home_jetable(tmp_path):
    fini = _bac_a_sable(str(tmp_path / "bac"))
    assert fini.returncode == 0, fini.stderr
    assert "[sandbox]" in fini.stdout
