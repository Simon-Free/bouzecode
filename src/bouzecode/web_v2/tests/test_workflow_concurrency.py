"""Régression concurrence de la machine à états : advance() est un check-then-act.
Appelé simultanément (hook on_completion + watchdog + poll liste), il doit tirer LA
transition UNE SEULE fois. Sans le verrou par-ticket + relecture fraîche, N advance
concurrents sur un ticket `work_done` tiraient N fois l'action.

L'enjeu a changé de nature avec le retrait de la chaîne automatique : l'action de ce
état n'est plus le test-gate (supprimé) mais la RÉCOLTE de livraison, qui fait un
`git commit`. Une double transition ne double-spawnerait plus un validateur : elle
poserait deux commits de livraison sur la branche de l'agent."""
import threading

from bouzecode.web_v2.services.work import delivery, tickets, workflow


def test_concurrent_advance_fires_the_delivery_harvest_once(monkeypatch, tmp_path):
    monkeypatch.setattr(tickets, "TICKETS_DIR", tmp_path)
    ticket = tickets.create_ticket("proj", "cible", "p")
    tickets.add_run("proj", ticket, "coder", "work", "m")
    ticket["worktree"] = {"state": "provisioned", "worktree": str(tmp_path),
                          "branch": "agent/t", "base": "develop", "repo_root": str(tmp_path)}
    tickets.update_ticket("proj", ticket)
    tickets.mark_run_completed("proj", ticket, "coder")  # état = work_done, récolte due

    calls: list = []

    def fake_harvest(slug, tk, done_agent=""):
        calls.append(1)
        # La vraie action persiste `harvested` sur le run : sans ça la garde reste vraie
        # et le test ne prouverait que la sérialisation, pas la transition unique.
        delivery.work_run(tk)["harvested"] = True
        tickets.update_ticket(slug, tk)

    monkeypatch.setitem(workflow.ACTIONS, "harvest_delivery", fake_harvest)

    n = 10
    barrier = threading.Barrier(n)

    def worker():
        barrier.wait()  # tous les advance frappent l'état work_done en même temps
        workflow.advance("proj", dict(ticket))  # snapshot périmé volontaire (sans `harvested`)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(calls) == 1, f"récolte tirée {len(calls)}x (attendu 1) → double commit"
    fresh = tickets.get_ticket("proj", ticket["id"])
    assert delivery.needs_delivery_harvest(fresh) is False
