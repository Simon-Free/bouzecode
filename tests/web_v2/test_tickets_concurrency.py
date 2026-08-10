"""Régression concurrence : les écritures du fichier tickets doivent être atomiques
(read-modify-write sous un seul verrou). Avant le fix, `_tickets_lock` protégeait `_load`
et `_save` séparément → 6 dispatches // perdaient 4 tickets (lost update). Ces tests
reproduisent la course : sans le fix ils échouent, avec le fix ils passent.

Le troisième test neutralisait le verrou sur le RÉ-EXPORT `tickets._tickets_lock`. `_mutate`
vit dans `_persistence` et y résout le nom : le verrou restait donc TENU, et le test observait
le chemin verrouillé tout en prétendant décrire N process sans arbitre commun. Prouvé par
mutation (retour du load-ALL/mute-one/save-ALL de l'ère JSON dans `_mutate`) : avec l'ancien
branchement, 3 passed ; avec le branchement corrigé, « 11 mutations perdues (lost update) ».
Le store est isolé par la fixture autouse `_isolate_production_state` — patcher
`tickets.TICKETS_DIR` (autre ré-export) n'isolait rien non plus."""
import contextlib
import threading

from bouzecode.web_v2.services.work import _persistence, tickets


def test_concurrent_create_ticket_loses_none(tmp_path):
    n = 12
    barrier = threading.Barrier(n)

    def worker(i):
        barrier.wait()  # maximise le chevauchement du read-modify-write
        tickets.create_ticket("proj", f"t{i}", f"prompt {i}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    stored = tickets._load("proj")
    assert len(stored) == n, f"attendu {n} tickets, {len(stored)} persistés (lost update)"
    assert len({t["id"] for t in stored}) == n


def test_concurrent_add_run_same_ticket_loses_none(tmp_path):
    ticket = tickets.create_ticket("proj", "cible", "p")
    n = 12
    barrier = threading.Barrier(n)

    def worker(i):
        barrier.wait()
        tickets.add_run("proj", dict(ticket), f"agent{i}", "work", "m")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    fresh = tickets.get_ticket("proj", ticket["id"])
    assert len(fresh["runs"]) == n, f"attendu {n} runs, {len(fresh['runs'])} (lost update)"
    assert len({r["agent_id"] for r in fresh["runs"]}) == n


def test_unsynced_writers_do_not_lose_updates(monkeypatch, tmp_path):
    """Révélateur du défaut de DESIGN (WinError5 & lost-update en prod) : le store est partagé
    entre le serveur ET N agents CLI, qui sont des PROCESS DIFFÉRENTS — `_tickets_lock`
    (threading) ne les coordonne PAS. On simule cette absence de coordination en neutralisant
    le verrou, puis on mute EN CONCURRENCE des tickets DISTINCTS.

    Backend JSON monolithique : chaque `_mutate` = load-ALL + mute-one + save-ALL. Deux writers
    entrelacés réécrivent la liste ENTIÈRE à partir d'un snapshot périmé → la mutation de l'autre
    est ÉCRASÉE (lost update) → ROUGE.
    Backend SQLite (upsert par id, transactionnel) : chaque mutation ne touche QUE sa ligne →
    aucune perte → VERT. Invariant testé contre l'API (`_mutate`), stable après migration."""
    n = 12
    ids = [tickets.create_ticket("proj", f"t{i}", f"p{i}")["id"] for i in range(n)]

    # Neutralise le verrou intra-process → reproduit fidèlement N process sans arbitre commun.
    # DANS `_persistence` : c'est là que `_mutate` résout le nom. Neutraliser le ré-export
    # `tickets._tickets_lock` ne touchait RIEN — le verrou restait tenu et le test observait
    # le chemin VERROUILLÉ tout en prétendant décrire des process non coordonnés.
    monkeypatch.setattr(_persistence, "_tickets_lock", contextlib.nullcontext())
    barrier = threading.Barrier(n)

    def worker(ticket_id):
        barrier.wait()  # maximise le chevauchement des read-modify-write non synchronisés

        def mark_done(t):
            t["done"] = True

        tickets._mutate("proj", ticket_id, mark_done)

    threads = [threading.Thread(target=worker, args=(tid,)) for tid in ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    fresh = tickets._load("proj")
    done_ids = {t["id"] for t in fresh if t.get("done")}
    missing = set(ids) - done_ids
    assert not missing, f"{len(missing)} mutations perdues (lost update) : {sorted(missing)}"
