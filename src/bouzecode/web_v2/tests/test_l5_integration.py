# [desc] Lot L5 — intégration ASYNCHRONE (202) fondée sur les fichiers de code : merge propre → closed, conflit → conflict sans relance, résidu de méta → 409 rien_a_integrer, worktree disparu → merge depuis la branche, shared → pas_isole, delivery/refresh, diff. [/desc]
"""Critère §10 n° 7, via le vrai client Flask, le vrai store et du vrai git (`delivery_repo`)."""
from __future__ import annotations

from pathlib import Path

from bouzecode.web_v2.services.work import tickets, worktrees

from aides_l3 import attendre_les_fils, ticket_isole
from delivery_repo import SLUG, client, develop_repo, git_out, project  # noqa: F401 — fixtures

URL = f"/api/projects/{SLUG}/tickets"


def _integrer(client, ticket_id: str):
    return client.post(f"{URL}/{ticket_id}/integrate", json={"wait": True})


def test_l_integration_repond_202_puis_un_merge_propre_clot_le_ticket(client, project):
    ticket = ticket_isole(project, "propre", {"module.py": "x = 1\n"})

    reponse = client.post(f"{URL}/{ticket['id']}/integrate")

    assert reponse.status_code == 202 and reponse.get_json()["state"] in ("integrating", "closed")
    attendre_les_fils("integration-")
    frais = tickets.get_ticket(SLUG, ticket["id"])
    assert frais["state"] == "closed" and frais["state_reason"]["code"] == "integre"
    assert frais["integration"]["merge_commit"] or frais["integration"]["merged_at"]
    assert "module.py" in git_out(project, "ls-tree", "--name-only", "develop")
    assert not Path(ticket["worktree"]["worktree"]).exists()  # récolte propre → retiré


def test_un_conflit_donne_conflict_sans_relancer_personne(client, project):
    (project / "README.md").write_text("version de la base\n", encoding="utf-8")
    git_out(project, "checkout", "-q", "develop")
    git_out(project, "-c", "user.email=t@t.t", "-c", "user.name=t", "commit", "-qam", "base")
    git_out(project, "checkout", "-q", "main")
    ticket = ticket_isole(project, "conflit", {"README.md": "version de l'agent\n"},
                          branche_de_base="main")
    tickets.poser(SLUG, ticket, worktree={**ticket["worktree"], "base": "develop"})
    runs_avant = len(tickets.get_ticket(SLUG, ticket["id"])["runs"])

    assert _integrer(client, ticket["id"]).status_code == 202

    frais = tickets.get_ticket(SLUG, ticket["id"])
    assert frais["state"] == "conflict"
    assert "README.md" in frais["integration"]["conflict_files"]
    assert len(frais["runs"]) == runs_avant  # aucun run lancé d'office


def test_un_residu_de_fichiers_de_meta_n_est_pas_a_integrer(client, project):
    ticket = ticket_isole(project, "méta", {"uv.lock": "x\n", "SYMBOLS.md": "y\n"})

    reponse = _integrer(client, ticket["id"])

    assert reponse.status_code == 409
    erreur = reponse.get_json()["error"]
    assert erreur["code"] == "rien_a_integrer"
    assert erreur["details"]["delivery"]["commits_ahead"] == 1
    assert erreur["details"]["delivery"]["code_files_ahead"] == 0
    assert tickets.get_ticket(SLUG, ticket["id"])["state"] == "delivered"


def test_un_worktree_disparu_s_integre_depuis_sa_branche(client, project):
    ticket = ticket_isole(project, "disparu", {"tardif.py": "y = 2\n"})
    worktrees.reap(ticket["worktree"], delete_branch=False)  # effacé hors du serveur
    assert not Path(ticket["worktree"]["worktree"]).exists()

    assert _integrer(client, ticket["id"]).status_code == 202

    assert tickets.get_ticket(SLUG, ticket["id"])["state"] == "closed"
    assert "tardif.py" in git_out(project, "ls-tree", "--name-only", "develop")


def test_un_ticket_shared_n_a_rien_a_fusionner(client, project):
    ticket = tickets.create_ticket(SLUG, "partagé", "p")
    tickets.set_launching(SLUG, ticket)
    tickets.add_run(SLUG, ticket, "agshared01", "work", "")
    from bouzecode.web_v2.services.work import constats
    constats.fin_de_run(SLUG, ticket["id"], "agshared01", "final_answer")

    reponse = _integrer(client, ticket["id"])

    assert reponse.status_code == 409 and reponse.get_json()["error"]["code"] == "pas_isole"


def test_un_agent_actif_bloque_l_integration(client, project):
    ticket = ticket_isole(project, "actif", {"a.py": "a\n"}, etat_livre=False)

    reponse = _integrer(client, ticket["id"])

    assert reponse.status_code == 409 and reponse.get_json()["error"]["code"] == "agent_actif"


def test_delivery_refresh_mesure_la_branche_sans_rien_ecrire_dans_git(client, project):
    ticket = ticket_isole(project, "mesure", {"code.py": "c\n", "uv.lock": "l\n"})
    tete = git_out(project, "rev-parse", ticket["worktree"]["branch"])

    reponse = client.post(f"{URL}/{ticket['id']}/delivery/refresh")

    assert reponse.status_code == 200
    constat = reponse.get_json()["delivery"]
    assert constat["head"] == tete and constat["commits_ahead"] == 1
    assert constat["code_files_ahead"] == 1 and constat["dirty"] is False
    assert tickets.get_ticket(SLUG, ticket["id"])["delivery"]["head"] == tete
    assert git_out(project, "rev-parse", ticket["worktree"]["branch"]) == tete


def test_le_diff_decrit_la_branche_du_ticket(client, project):
    ticket = ticket_isole(project, "diff", {"code.py": "c\n", "uv.lock": "l\n"})

    corps = client.get(f"{URL}/{ticket['id']}/diff").get_json()

    assert corps["branch"] == ticket["worktree"]["branch"] and corps["base"] == "develop"
    assert [c["subject"] for c in corps["commits"]] == ["travail diff"]
    assert {f["path"]: f["code"] for f in corps["files"]} == {"code.py": True, "uv.lock": False}


def test_harvest_commite_le_travail_et_refuse_sous_un_run_vivant(client, project, monkeypatch):
    ticket = ticket_isole(project, "récolte", {"a.py": "a\n"})
    (Path(ticket["worktree"]["worktree"]) / "b.py").write_text("b\n", encoding="utf-8")

    reponse = client.post(f"{URL}/{ticket['id']}/harvest")

    assert reponse.status_code == 200 and reponse.get_json()["commit"]
    assert "b.py" in git_out(project, "ls-tree", "--name-only", ticket["worktree"]["branch"])
    from bouzecode.web_v2.services.work import nettoyage
    monkeypatch.setattr(nettoyage, "run_vivant", lambda t: "agvivant")
    refus = client.post(f"{URL}/{ticket['id']}/harvest")
    assert refus.status_code == 409 and refus.get_json()["error"]["code"] == "run_vivant"
