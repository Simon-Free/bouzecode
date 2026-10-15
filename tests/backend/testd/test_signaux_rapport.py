# [desc] testd : le rapport signale les tests lents (au-delà de `timeouts.slow_signal`) sans les tuer, et neutralise puis nomme les relances automatiques `flaky(reruns=2)` : un test en échec n'est joué qu'une fois [/desc]
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from bouzecode.backend.testd.common import sans_fenetre
from bouzecode.backend.testd.rendu import attendre, texte_etat
from bouzecode.backend.tools.ops.shell_env import strip_inherited_python_home
from tests.backend.testd.aides import commande, projet

_LENTS = {
    "test_lents.py": """
        import time
        def test_rapide():
            assert True
        def test_attente_fixe():
            time.sleep(1.5)
    """,
    "test_range_lent.py": """
        import time
        def test_deja_range_en_lent():
            time.sleep(1.5)
    """,
}


def test_un_test_lent_est_signale_sans_etre_tue(demon, tmp_path):
    """Au-delà du seuil (`timeouts.slow_signal`, ici 1 s), le test est listé avec sa durée et un
    indice ; il passe quand même. Un test rangé sous `impacted.slow` reçoit l'autre indice."""
    racine = projet(tmp_path / "p", _LENTS)
    (racine / ".bouzecode").mkdir()
    (racine / ".bouzecode" / "tests.yaml").write_text(
        "timeouts:\n  slow_signal: 1\nimpacted:\n  slow: ['test_range_lent.py']\n", encoding="utf-8")
    job = demon.soumettre(commande("test_lents.py", "test_range_lent.py"), dict(os.environ),
                          str(racine), 300, "")
    final = attendre(job["job_id"], 120, au_premier_echec=False)
    rapport = texte_etat(final)
    assert final["passed"] == 3 and final["failed"] == 0, rapport
    assert "[testd] tests lents (> 1,0 s) :" in rapport, rapport
    lignes = {l.split(" — ")[0].strip(): l for l in rapport.splitlines() if " — " in l}
    assert "démarrage par test ou attente fixe probable" in lignes["test_lents.py::test_attente_fixe"]
    assert "désélectionné en lent ?" in lignes["test_range_lent.py::test_deja_range_en_lent"]
    assert "test_lents.py::test_rapide" not in lignes
    assert "bloqué depuis" not in rapport


#  pytest-rerunfailures n'est pas dans le venv de bouzecode : celui de demo_application l'a.
_PYTHON_AVEC_RELANCES = (Path(__file__).resolve().parents[5] / "demo_application" / ".venv"
                         / "Scripts" / "python.exe")

_FLAKY = {
    "test_instable.py": """
        import pytest
        from pathlib import Path
        @pytest.mark.flaky(reruns=2)
        def test_vrai_echec():
            with open(Path(__file__).with_name("passages.txt"), "a") as passages:
                passages.write("x\\n")
            raise ModuleNotFoundError("dependance_absente")
    """,
}


@pytest.mark.skipif(not _PYTHON_AVEC_RELANCES.exists(), reason="pas de venv avec pytest-rerunfailures")
def test_un_test_flaky_en_echec_ne_tourne_qu_une_fois(demon, tmp_path):
    """Hors du démon, le marqueur fait jouer l'échec 3 fois ; par le démon, une seule, et le
    rapport nomme le fichier marqué pour que l'auteur retire le marqueur."""
    racine = projet(tmp_path / "p", _FLAKY)
    cmd = [str(_PYTHON_AVEC_RELANCES), *commande("test_instable.py")[1:]]
    #  Le lanceur uv de bouzecode pose PYTHONHOME (son 3.12) : l'autre venv (3.13) ne doit pas l'hériter.
    env = strip_inherited_python_home(dict(os.environ))
    direct = subprocess.run(cmd, cwd=racine, env=env, capture_output=True, text=True, timeout=60,
                            **sans_fenetre())
    passages = racine / "passages.txt"
    #  Le plugin de relance est bien actif : sans le démon, l'échec est joué 3 fois.
    assert passages.exists() and passages.read_text().count("x") == 3, direct.stdout + direct.stderr
    (racine / "passages.txt").unlink()

    job = demon.soumettre(cmd, env, str(racine), 300, str(_PYTHON_AVEC_RELANCES))
    final = attendre(job["job_id"], 120, au_premier_echec=False)
    rapport = texte_etat(final)
    assert (racine / "passages.txt").read_text().count("x") == 1, rapport
    assert final["failed"] == 1, rapport
    assert ("relances automatiques neutralisées : 1 tests marqués flaky" in rapport
            and "test_instable.py" in rapport.split("neutralisées")[1]), rapport
