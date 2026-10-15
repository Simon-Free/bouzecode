"""La frontiere process Graph : ce qui sort de PowerShell devient une panne Teams.

Vecu en production : un tenant muet a fait pendre PowerShell ; au bout de 90 s
`subprocess.run` a leve `subprocess.TimeoutExpired`, qui n'est PAS une OSError et ne
ressemble a rien que les appelants filtrent. Ces tests verrouillent la traduction, avec un
FAUX Teams (runner injecte) : aucun vrai script n'est lance.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from bouzecode.web_v2.services.work.teams import graph_transport

SCRIPT = graph_transport.PS_DIR / "graph_activite.ps1"


def test_un_powershell_qui_pend_devient_une_panne_teams_lisible() -> None:
    def runner_qui_pend(args: list[str]) -> tuple[int, str, str]:
        raise subprocess.TimeoutExpired(cmd=["powershell", *args], timeout=90)

    transport = graph_transport.PowerShellTransport(SCRIPT, runner=runner_qui_pend, timeout=90)

    with pytest.raises(graph_transport.TeamsTransportError) as panne:
        transport._call("chats", Since="2026-09-01T00:00:00Z")

    motif = str(panne.value)
    assert "chats" in motif, motif
    assert "90" in motif, motif


def test_un_powershell_qui_repond_rend_la_charge_graph() -> None:
    appels: list[list[str]] = []

    def runner_qui_repond(args: list[str]) -> tuple[int, str, str]:
        appels.append(args)
        return 0, json.dumps({"value": [{"id": "c1"}]}), ""

    transport = graph_transport.PowerShellTransport(SCRIPT, runner=runner_qui_repond)

    charge = transport._call("chats", Since="2026-09-01T00:00:00Z", Top=30)

    assert charge["value"] == [{"id": "c1"}]
    assert appels == [["-Action", "chats", "-Since", "2026-09-01T00:00:00Z", "-Top", "30"]]


def test_une_panne_d_authentification_est_typee() -> None:
    def runner_refuse(args: list[str]) -> tuple[int, str, str]:
        return 1, json.dumps({"error": {"code": "AuthenticationError", "message": "AADSTS"}}), ""

    transport = graph_transport.PowerShellTransport(SCRIPT, runner=runner_refuse)

    with pytest.raises(graph_transport.TeamsAuthError):
        transport._call("chats")
