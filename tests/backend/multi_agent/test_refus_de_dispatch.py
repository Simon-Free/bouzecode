# [desc] L'outil Agent relit un refus HTTP de la création de ticket (forme unique {"error": {code, message, details}}) comme avant : routed false + code + motif + détails. [/desc]
from __future__ import annotations

import pytest

from bouzecode.backend.core.local_http import LocalServerError
from bouzecode.backend.multi_agent.client_tickets import _refus as _refus_de_dispatch


def test_un_refus_structure_redevient_la_vue_de_l_outil():
    refus = LocalServerError("HTTP 409", status=409, corps={"error": {
        "code": "collision_isolation", "message": "2 agent(s) écrivent déjà dans le dépôt principal",
        "details": {"agents": ["a1", "a2"], "isolation": "shared"}}})

    vue = _refus_de_dispatch(refus)

    assert vue["routed"] is False and vue["code"] == "collision_isolation"
    assert vue["agents"] == ["a1", "a2"] and vue["isolation"] == "shared"
    assert vue["error"] == "2 agent(s) écrivent déjà dans le dépôt principal"


def test_sans_corps_structure_l_erreur_remonte_telle_quelle():
    """Serveur injoignable ou proxy : ce n'est pas un refus applicatif, on ne le maquille pas."""
    with pytest.raises(LocalServerError):
        _refus_de_dispatch(LocalServerError("injoignable"))
