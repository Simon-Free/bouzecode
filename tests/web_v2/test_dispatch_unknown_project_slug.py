# [desc] Un `project_slug` absent du registre (UI qui rejoue un projet supprimé/renommé) : la création de ticket refuse en 404 `projet_inconnu` qui NOMME le slug, sans 500 ni ticket fantôme. [/desc]
from __future__ import annotations

import pytest

from bouzecode.web_v2.services.work import _persistence, projects
from bouzecode.web_v2.services.work import tickets as tickets_svc
from bouzecode.web_v2.services.work.api_tickets import creation
from bouzecode.web_v2.services.work.api_tickets.refus import Refus


def _registry_with_only_p(monkeypatch, tmp_path):
    """Registre ne contenant QUE le projet 'p'. `projects.find` reste le VRAI :
    find('fantome') doit rendre None, exactement comme en production."""
    monkeypatch.setattr(_persistence, "TICKETS_DIR", tmp_path / "tickets")
    monkeypatch.setattr(tickets_svc, "TICKETS_DIR", tmp_path / "tickets")
    project = {"slug": "p", "name": "Projet", "path": str(tmp_path)}
    monkeypatch.setattr(projects, "list_projects", lambda: [project])
    return project


def test_un_slug_absent_du_registre_est_nomme_dans_un_404(monkeypatch, tmp_path):
    _registry_with_only_p(monkeypatch, tmp_path)

    with pytest.raises(Refus) as refus:
        creation.creer("fantome", {"title": "t", "prompt": "fais un truc"})

    assert (refus.value.status, refus.value.code) == (404, "projet_inconnu")
    # Le slug fautif est NOMMÉ : l'utilisateur doit comprendre que son projet mémorisé
    # n'existe plus, pas croire à une panne de configuration.
    assert "fantome" in refus.value.message


def test_un_slug_absent_ne_cree_aucun_ticket(monkeypatch, tmp_path):
    _registry_with_only_p(monkeypatch, tmp_path)

    with pytest.raises(Refus):
        creation.creer("fantome", {"title": "t", "prompt": "fais un truc"})

    assert tickets_svc.list_tickets("fantome") == []
