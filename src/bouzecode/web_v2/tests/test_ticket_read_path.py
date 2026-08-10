"""Ouvrir UN ticket, et voir un ticket en cours de lancement.

Trois comportements observés sur une VRAIE base SQLite (TICKETS_DIR temporaire via la
fixture autouse), sans aucun mock :
1. ouvrir un ticket ne lit QUE ce ticket, pas les mégaoctets des autres ;
2. consulter un ticket pendant qu'une écriture est en cours n'attend pas ;
3. un ticket tout juste créé, dont l'agent n'est pas encore spawné, est retrouvable.
"""
import json
import sqlite3
import threading

import pytest

from bouzecode.web_v2.services.work import _persistence, tickets


def _rendre_illisibles_les_autres_tickets(slug: str, ticket_epargne: str) -> None:
    """Sabote le JSON stocké des AUTRES tickets du slug : quiconque les décode explose.
    C'est la preuve, sans mock, qu'une lecture ciblée ne les a pas touchés."""
    connexion = sqlite3.connect(tickets.TICKETS_DIR / "tickets.db")
    connexion.execute(
        "UPDATE tickets SET data=? WHERE slug=? AND id<>?",
        ("{ceci n'est pas du JSON", slug, ticket_epargne),
    )
    connexion.commit()
    connexion.close()


# ── 1. Ouvrir un ticket ne lit que ce ticket ──────────────────────────────────

def test_ouvrir_un_ticket_rend_le_bon_ticket():
    """Demander un ticket par son id rend ce ticket-là, pas un autre."""
    premier = tickets.create_ticket("proj", "Premier", "prompt 1")
    second = tickets.create_ticket("proj", "Second", "prompt 2")

    assert tickets.get_ticket("proj", second["id"])["title"] == "Second"
    assert tickets.get_ticket("proj", premier["id"])["title"] == "Premier"


def test_ouvrir_un_ticket_inconnu_ne_rend_rien():
    """Un id qui n'existe pas ne rend rien (et ne lève pas) — le 404 de l'API en dépend."""
    tickets.create_ticket("proj", "Premier", "prompt 1")

    assert tickets.get_ticket("proj", "id-inexistant") is None
    assert tickets.get_ticket("slug-inexistant", "id-inexistant") is None


def test_ouvrir_un_ticket_ne_decode_pas_les_autres_tickets_du_projet():
    """Un projet chargé (ici 10 tickets, dont un gros) s'ouvre ticket par ticket : les
    autres lignes sont rendues indécodables et l'ouverture réussit quand même."""
    cible = tickets.create_ticket("proj", "Celui qu'on ouvre", "prompt")
    for numero in range(9):
        gros = tickets.create_ticket("proj", f"Voisin {numero}", "x" * 50_000)
        tickets.add_comment("proj", gros, "y" * 50_000, False)
    _rendre_illisibles_les_autres_tickets("proj", cible["id"])

    ouvert = tickets.get_ticket("proj", cible["id"])

    assert ouvert["title"] == "Celui qu'on ouvre"
    # Contre-preuve : lire la LISTE du projet décode bien ces lignes, donc elles étaient
    # sur le chemin de l'ancienne implémentation.
    with pytest.raises(json.JSONDecodeError):
        tickets.list_tickets("proj")


# ── 2. Lire n'attend pas derrière une écriture ────────────────────────────────

def test_consulter_un_ticket_pendant_une_ecriture_n_attend_pas():
    """Une écriture en cours ne met plus les lectures en file d'attente : le store est en
    WAL, un lecteur y prend un snapshot cohérent sans bloquer."""
    ticket = tickets.create_ticket("proj", "A", "prompt")
    lu = {}

    def lecteur():
        lu["ticket"] = tickets.get_ticket("proj", ticket["id"])
        lu["liste"] = tickets.list_tickets("proj")

    with _persistence._tickets_lock:  # un writer tient le verrou d'écriture du process
        thread = threading.Thread(target=lecteur)
        thread.start()
        thread.join(timeout=5)
        assert not thread.is_alive(), "la lecture attend encore derrière l'écriture"

    assert lu["ticket"]["id"] == ticket["id"]
    assert len(lu["liste"]) == 1


# ── 3. Tickets en cours de lancement ──────────────────────────────────────────

def test_un_ticket_en_cours_de_lancement_est_retrouve_sur_chaque_projet():
    """Le temps que son worktree et son agent se montent, un ticket reste visible :
    on le retrouve, projet par projet, tant qu'il est en cours de lancement."""
    lance_ici = tickets.create_ticket("projet-a", "Feature A", "prompt")
    lance_la = tickets.create_ticket("projet-b", "Feature B", "prompt")
    tickets.create_ticket("projet-a", "Ticket au repos", "prompt")
    tickets.set_launching("projet-a", lance_ici)
    tickets.set_launching("projet-b", lance_la)

    trouves = tickets.launching_tickets()

    assert {(slug, t["id"]) for slug, t in trouves} == {
        ("projet-a", lance_ici["id"]),
        ("projet-b", lance_la["id"]),
    }
    assert all(t.get("launching") for _slug, t in trouves)


def test_un_ticket_au_repos_n_est_jamais_annonce_en_lancement():
    """Un ticket créé sans lancement n'est jamais annoncé comme en cours de lancement."""
    tickets.create_ticket("proj", "Au repos", "prompt")

    assert tickets.launching_tickets() == []


def test_le_ticket_disparait_des_lancements_des_que_son_agent_demarre():
    """Dès que l'agent est spawné, le ticket cesse d'être « en cours de lancement » :
    c'est le vrai agent qui le représente désormais."""
    ticket = tickets.create_ticket("proj", "Feature", "prompt")
    tickets.set_launching("proj", ticket)

    tickets.add_run("proj", ticket, "agent-42", "work", "sonnet")

    assert tickets.launching_tickets() == []


def test_un_ticket_deja_lance_avant_le_passage_en_base_reste_invisible():
    """Un store legacy jamais rouvert (fichier `{slug}.json` d'avant SQLite) ne fabrique
    pas de faux lancements : seule la base fait foi."""
    tickets.TICKETS_DIR.mkdir(parents=True, exist_ok=True)
    (tickets.TICKETS_DIR / "vieux-projet.json").write_text(
        json.dumps([{"id": "vieux1", "title": "T", "launching": True, "runs": []}]),
        encoding="utf-8",
    )

    assert tickets.launching_tickets() == []
