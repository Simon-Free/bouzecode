"""Les outils multi-agents parlent au serveur web OÙ IL ÉCOUTE, pas au port 5056 en dur.

Trouvé en bac à sable le 2026-09-23 : un serveur lancé sur un autre port recevait des agents
dont les `Agent`/`MessageAgent` partaient vers 5056 — vers personne, ou vers un autre serveur.
`app.main` pose `BOUZECODE_WEB_BASE_URL`, hérité par les agents lancés.
"""
from bouzecode.backend.multi_agent import client_tickets


def test_sans_variable_le_port_historique_reste(monkeypatch):
    monkeypatch.delenv("BOUZECODE_WEB_BASE_URL", raising=False)
    assert client_tickets._url("/api/projects/p/tickets") == "http://127.0.0.1:5056/api/projects/p/tickets"


def test_la_variable_du_serveur_prime(monkeypatch):
    monkeypatch.setenv("BOUZECODE_WEB_BASE_URL", "http://127.0.0.1:5063/")
    assert client_tickets._url("/api/projects/p/tickets") == "http://127.0.0.1:5063/api/projects/p/tickets"
    assert client_tickets._url("/api/agents/a1/children") == "http://127.0.0.1:5063/api/agents/a1/children"


def test_une_url_deja_remplacee_passe_telle_quelle(monkeypatch):
    monkeypatch.setenv("BOUZECODE_WEB_BASE_URL", "http://127.0.0.1:5063")
    assert client_tickets._sur_le_serveur("http://127.0.0.1:9999/api/projects/p/tickets") \
        == "http://127.0.0.1:9999/api/projects/p/tickets"
