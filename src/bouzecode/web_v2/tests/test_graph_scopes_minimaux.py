# [desc] scripts PowerShell Graph en scopes minimaux, application Entra ID dediee (-ClientId/-TenantId), repli BOUZECODE_GRAPH_LEGACY_SCOPES, garde des tests et reutilisation du contexte. [/desc]
"""Scopes Graph minimaux et application dediee.

Chaque script passe par `Connect-BureauGraph` (ps/graph_auth.ps1), qui porte l'application
dediee, la garde des tests et la reutilisation d'un contexte deja ouvert. Pas de PowerShell
dans la CI : on verifie le texte des scripts.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

PS = Path(__file__).resolve().parents[1] / "services" / "work" / "teams" / "ps"
SCRIPTS = ("graph_bureau.ps1", "graph_activite.ps1")


def _code(nom: str) -> str:
    texte = (PS / nom).read_text(encoding="utf-8-sig")
    return "\n".join(l for l in texte.splitlines() if not l.lstrip().startswith("#"))


@pytest.mark.parametrize("nom", SCRIPTS)
def test_chaque_script_passe_par_la_connexion_commune(nom):
    code = _code(nom)
    assert '. "$PSScriptRoot\\graph_auth.ps1"' in code
    # Plus aucun Connect-MgGraph direct : il ignorerait l'application dediee et la garde.
    appels = [l for l in code.splitlines() if re.search(r"^\s*Connect-MgGraph\b", l)]
    assert appels == []


def test_la_lecture_teams_ne_demande_que_chat_read():
    lignes = [l for l in _code("graph_activite.ps1").splitlines() if "Connect-BureauGraph" in l]
    assert any("'Chat.Read'" in l for l in lignes)
    assert not any("Chat.ReadWrite" in l or "ChatMessage.Send" in l for l in lignes)


def test_graph_auth_passe_client_et_locataire_et_refuse_un_client_seul():
    code = _code("graph_auth.ps1")
    assert "BOUZECODE_GRAPH_CLIENT_ID" in code and "BOUZECODE_GRAPH_TENANT_ID" in code
    assert "$params['ClientId']" in code and "$params['TenantId']" in code
    assert "throw 'BOUZECODE_GRAPH_CLIENT_ID est defini sans BOUZECODE_GRAPH_TENANT_ID" in code
    assert "BOUZECODE_GRAPH_LEGACY_SCOPES" in code
    assert (PS / "graph_auth.ps1").read_bytes().startswith(b"\xef\xbb\xbf")
    assert all(b < 128 for b in (PS / "graph_auth.ps1").read_bytes()[3:])


def test_graph_auth_refuse_de_se_connecter_sous_test_avant_connect_mggraph():
    code = _code("graph_auth.ps1")
    garde = code.index("BZ_TESTS_TEAMS_INTERDIT")
    assert garde < code.index("Connect-MgGraph @params"), "la garde doit passer AVANT la connexion"


def test_graph_auth_reutilise_un_contexte_qui_a_deja_les_scopes():
    code = _code("graph_auth.ps1")
    assert "Get-MgContext" in code
    assert "if (Test-BureauGraphDejaConnecte $params['Scopes']) { return }" in code
