# [desc] Tests des marqueurs de crash (FIX #24) : derive_status 'planté', mark_run_completed idempotent. [/desc]
"""Marqueurs servant au watchdog : statut VISIBLE 'planté' d'un ticket crashé et
`mark_run_completed` (persiste le fait qu'un run a été clôturé proprement, ce qui
distingue une fin gracieuse d'un crash). No unittest.mock — fakes + monkeypatch."""
from __future__ import annotations

from bouzecode.web_v2.services.work import _persistence
from bouzecode.web_v2.services.work import tickets as tsvc


def test_derive_status_crashed_visible():
    ticket = {"crashed": True, "runs": [{"agent_id": "a", "kind": "work"}]}
    assert tsvc.derive_status(ticket) == "planté"


def test_a_manual_done_never_repaints_a_dead_agent_as_finished():
    """Cocher « terminé » à la main n'invente pas une livraison.

    Ce test s'appelait `test_derive_status_done_wins_over_crashed` et affirmait l'INVERSE
    (« done prime sur planté »). C'est exactement la règle qui a fait annoncer « terminé » le
    un ticket dont l'unique agent était mort avec rc -1, une session de
    102 octets et AUCUN bloc produit : un travail annoncé livré qui n'existait pas. La priorité
    est donc renversée pour un crash PROUVÉ. Ce n'est pas un relâchement de l'ancienne
    intention : sa part légitime (un crash PÉRIMÉ ne doit pas figer un ticket réellement livré)
    est prouvée par les deux tests suivants."""
    mort = {"done": True, "runs": [{"agent_id": "a", "kind": "work"}]}
    # Vivacité croisée (liveness.classify_ticket) : aucun run n'a de livraison prouvée.
    assert tsvc.derive_status(mort, liveness_state="crashed") == "planté"
    # Même verdict quand c'est le watchdog qui a posé le drapeau.
    assert tsvc.derive_status({**mort, "crashed": True}) == "planté"


def test_a_done_ticket_whose_agent_delivered_stays_finished():
    """Part LÉGITIME de l'ancienne règle : dès qu'une livraison est prouvée, `done` est honoré."""
    livre = {"done": True, "runs": [{"agent_id": "a", "kind": "work"}]}
    assert tsvc.derive_status(livre, liveness_state="delivered") == "terminé"
    # Appelant qui ne s'est pas renseigné sur la vivacité : comportement historique inchangé.
    assert tsvc.derive_status(livre) == "terminé"
    # Ticket JAMAIS joué (aucun run) : le `done` du user est le seul fait disponible — on ne
    # peut pas lui opposer une mort qui n'a pas eu lieu. C'est pourquoi la garde exige un run.
    assert tsvc.derive_status({"done": True, "runs": []}, liveness_state="crashed") == "terminé"


def test_a_revoked_crash_flag_no_longer_holds_a_finished_ticket_hostage():
    """L'autre part légitime : un crash PÉRIMÉ est RÉVOQUÉ à la source, pas masqué par `done`.

    Un agent repris qui livre fait retirer le drapeau par le watchdog
    (`wake.crash_is_contradicted`, prouvé par test_stale_crash_revoked.py) ; le ticket
    redevient alors « terminé » sans que `done` ait jamais eu à masquer quoi que ce soit."""
    repris = {"done": True, "crashed": True, "runs": [{"agent_id": "a", "kind": "work"}]}
    assert tsvc.derive_status(repris) == "planté"  # tant que le drapeau tient
    repris.pop("crashed")  # révoqué par le watchdog : l'agent est reparti et a livré
    assert tsvc.derive_status(repris, liveness_state="delivered") == "terminé"


def _count_saves(monkeypatch):
    """Compte les écritures disque RÉELLES : l'UPSERT d'une ligne, seul chemin d'écriture.

    Il comptait `_save_unlocked` (réécriture de la liste JSON complète), que la migration vers
    SQLite a laissé en place mais que `mark_run_completed` n'emprunte plus — le compteur restait
    donc à zéro : un rouge trompeur ici, et un vert VIDE dans le test d'idempotence (qui
    « prouvait » l'absence d'écriture sans jamais pouvoir en observer une). On espionne la
    fonction DANS `_persistence`, car `_mutate` l'appelle par son nom de module (patcher le
    ré-export `tsvc._upsert_one` n'intercepterait rien)."""
    saves: list = []
    orig = _persistence._upsert_one

    def counting(conn, slug, ticket):
        saves.append(slug)
        orig(conn, slug, ticket)

    monkeypatch.setattr(_persistence, "_upsert_one", counting)
    return saves


def test_mark_run_completed_sets_flag_and_persists(monkeypatch, tmp_path):
    monkeypatch.setattr(tsvc, "TICKETS_DIR", tmp_path)
    ticket = {"id": "t1", "comments": [], "runs": [
        {"agent_id": "coder", "kind": "work"},
        {"agent_id": "other", "kind": "validate"},
    ]}
    tsvc._save("proj", [ticket])  # persiste d'abord (mark_run_completed relit le disque)
    saves = _count_saves(monkeypatch)
    tsvc.mark_run_completed("proj", ticket, "coder")
    fresh = tsvc.get_ticket("proj", "t1")
    assert fresh["runs"][0]["completed"] is True
    assert "completed" not in fresh["runs"][1]  # seul le run de l'agent visé
    assert ticket["runs"][0]["completed"] is True  # miroir sur l'objet appelant
    assert len(saves) == 1


def test_a_second_close_on_the_same_run_counts_a_new_turn(monkeypatch, tmp_path):
    """Un agent RÉ-INSTRUIT reclôt un tour sur le MÊME run : le compteur de tours avance.

    C'est le seul signal qui distingue « l'enfant n'a rien fait » de « l'enfant a
    retravaillé et re-livré » — `completed` est un booléen, il ne rebouge plus. Sans lui,
    `wake.children_signature` était identique après le retravail et le manager qui attendait
    la réponse n'était JAMAIS réveillé."""
    monkeypatch.setattr(tsvc, "TICKETS_DIR", tmp_path)
    ticket = {"id": "t1", "comments": [],
              "runs": [{"agent_id": "coder", "kind": "work", "completed": True, "turns": 1}]}
    tsvc._save("proj", [ticket])

    tsvc.mark_run_completed("proj", ticket, "coder")

    assert tsvc.get_ticket("proj", "t1")["runs"][0]["turns"] == 2
    assert ticket["runs"][0]["turns"] == 2  # miroir sur l'objet appelant


def test_closing_a_run_of_another_agent_writes_nothing(monkeypatch, tmp_path):
    """Aucun run de cet agent → aucune réécriture (le watchdog ne doit rien coûter à vide)."""
    monkeypatch.setattr(tsvc, "TICKETS_DIR", tmp_path)
    ticket = {"id": "t1", "comments": [],
              "runs": [{"agent_id": "coder", "kind": "work", "completed": True}]}
    tsvc._save("proj", [ticket])
    saves = _count_saves(monkeypatch)

    tsvc.mark_run_completed("proj", ticket, "un-autre-agent")

    assert saves == []
