"""La garde `pytest_teams_etanche` : aucun test ne peut lancer le vrai PowerShell Teams.

Chaque tentative vise un EXÉCUTABLE INEXISTANT : si la garde tombait, le test échouerait sur
`FileNotFoundError` au lieu d'ouvrir une connexion Microsoft sur le poste.
"""
from __future__ import annotations

import os
import subprocess

import pytest

from bouzecode.web_v2.tests import pytest_teams_etanche as garde

EXE_ABSENT = "exe-inexistant-garde-teams"


def test_la_variable_est_posee_pour_les_descendants():
    assert os.environ[garde.VAR_INTERDIT] == "1"


def test_les_scripts_du_dossier_ps_sont_tous_couverts():
    assert "graph_activite.ps1" in garde.SCRIPTS_TEAMS
    assert "graph_auth.ps1" in garde.SCRIPTS_TEAMS


@pytest.mark.parametrize("args", [
    [EXE_ABSENT, "-File", str(garde.DOSSIER_PS / "graph_activite.ps1")],
    f'{EXE_ABSENT} -File "{garde.DOSSIER_PS / "graph_bureau.ps1"}"',
], ids=["liste", "chaine"])
def test_un_lancement_du_vrai_script_est_bloque_avant_le_processus(args):
    with pytest.raises(garde.TeamsReelInterdit, match="graph_"):
        subprocess.run(args, capture_output=True, timeout=5)
    #  La tentative est notée pour faire échouer le test : ici elle est attendue, on la retire.
    garde._tentatives.clear()


def test_un_autre_processus_passe():
    assert garde.script_teams_vise("python", ["python", "-c", "print(1)"]) is None
    assert garde.script_teams_vise("powershell", ["powershell", "-File", "bouzeui.ps1"]) is None
