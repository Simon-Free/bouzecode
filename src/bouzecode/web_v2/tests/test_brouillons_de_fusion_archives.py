"""Un brouillon « Fusionner / Intégrer la branche agent/XXXX » est archivé automatiquement,
avec une trace visible, dès que cette branche est intégrée — jamais une tâche lancée.

Cas réel (2026-09-24) : l'assistant avait noté « Fusionner la branche de l'agent e9a71355 dans
main » ; l'agent a intégré sa branche lui-même et le brouillon est resté affiché comme un
travail à faire.

Vrai dépôt git en tmp, vraie intégration (`integration.integrate_ticket`, le chemin de l'outil
Environment et du bouton « Intégrer »), vraie base isolée ; on lit `/api/lignes` comme le front.
"""
import shutil
import subprocess
import uuid
from pathlib import Path

from bouzecode.web_v2.services.work import (brouillons_integres, constats, integration, micros,
                                             tickets, worktrees)
from bouzecode.web_v2.tests.test_v3_statut_des_taches import SLUG, client, ligne  # noqa: F401


def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   check=True, capture_output=True, text=True)


_MODELE: list[Path] = []


def _depot_modele(tmp_path) -> Path:
    """Le dépôt `main` d'un seul commit, construit UNE fois par worker (quatre appels git que
    chaque test repayait) puis copié. Rangé sous la racine temporaire de la session, à côté
    des `tmp_path` des tests ; jamais modifié."""
    if not _MODELE:
        modele = tmp_path.parent / f"modele_brouillons_{uuid.uuid4().hex[:8]}"
        modele.mkdir()
        _git(modele, "init", "-b", "main")
        (modele / "a.txt").write_text("base\n")
        _git(modele, "add", "-A")
        _git(modele, "commit", "-m", "init")
        _MODELE.append(modele)
    return _MODELE[0]


def _ticket_isole(tmp_path) -> dict:
    """Un ticket dont l'agent a travaillé dans son worktree (branche agent/<id>)."""
    depot = tmp_path / "depot"
    shutil.copytree(_depot_modele(tmp_path), depot)
    ticket = tickets.create_ticket(SLUG, "Scraper les énigmes", "go")
    meta = worktrees.provision(str(depot), ticket["id"], base_branch="main")
    (Path(meta["worktree"]) / "b.txt").write_text("livré\n")
    tickets.poser(SLUG, ticket, worktree=meta)
    tickets.set_launching(SLUG, ticket)
    tickets.add_run(SLUG, ticket, "codeur-" + ticket["id"], "work", "m")
    constats.fin_de_run(SLUG, ticket["id"], "codeur-" + ticket["id"], "final_answer")  # livré
    return tickets.get_ticket(SLUG, ticket["id"])


def _brouillon(client, titre, **extra):
    reponse = client.post("/api/micros", json={"titre": titre, **extra})
    assert reponse.status_code == 201
    return reponse.get_json()["micro"]["id"]


def test_integrer_la_branche_archive_le_brouillon_qui_la_vise_avec_une_trace(client, tmp_path):
    """Brouillon créé AVANT l'intégration : archivé (« faite »), la ligne dit pourquoi."""
    ticket = _ticket_isole(tmp_path)
    branche = f"agent/{ticket['id']}"
    brouillon = _brouillon(client, f"Fusionner la branche {branche} dans main")

    assert integration.integrate_ticket(SLUG, ticket)["ok"] is True

    vue = ligne(client, brouillon)
    assert (vue["statut_ui"], vue["segment"]) == ("faite", "archivees")
    assert vue["archive_auto"]["branche"] == branche
    assert vue["archive_auto"]["texte"].startswith(
        f"Archivée automatiquement : branche {branche} intégrée le ")
    assert any("Archivée automatiquement" in p["texte"] for p in vue["precisions"])


def test_seuls_les_brouillons_qui_visent_cette_branche_pour_l_integrer_sont_archives(client, tmp_path):
    """Contrôles : autre branche, simple mention sans « intégrer », tâche lancée → intacts."""
    ticket = _ticket_isole(tmp_path)
    branche = f"agent/{ticket['id']}"
    vise = _brouillon(client, f"Intégrer {branche}")
    autre = _brouillon(client, "Fusionner la branche agent/0badcafe dans main")
    mention = _brouillon(client, f"Relire le rapport de {branche}")
    lancee = _brouillon(client, f"Merger {branche} dans main")
    micros.lier_ticket(lancee, slug=SLUG, ticket_id="autre000")
    micros.marquer_etat(lancee, "lancee")

    integration.integrate_ticket(SLUG, ticket)

    assert ligne(client, vise)["statut_ui"] == "faite"
    assert [ligne(client, i)["statut_ui"] for i in (autre, mention)] == ["brouillon", "brouillon"]
    assert micros.get_micro(lancee)["etat"] == "lancee"
    assert ligne(client, lancee)["archive_auto"] is None


def test_le_tick_archive_un_ancien_brouillon_d_une_branche_deja_integree(client, tmp_path):
    """Brouillon sans cible enregistrée (données d'avant, ou brief réécrit ensuite) qui nomme
    « la branche de l'agent <id> », branche déjà intégrée → le tick l'archive (repli prudent)."""
    ticket = _ticket_isole(tmp_path)
    integration.integrate_ticket(SLUG, ticket)
    ancien = _brouillon(client, "Suite de la livraison")
    micros.update_micro(ancien, corps=f"Fusionner la branche de l'agent {ticket['id']} dans main")

    archives = brouillons_integres.balayer()

    assert ancien in archives
    assert ligne(client, ancien)["archive_auto"]["texte"].startswith("Archivée automatiquement")


def test_un_brouillon_rouvert_apres_un_archivage_automatique_n_est_plus_archive(client, tmp_path):
    """L'utilisateur a le dernier mot : Rouvrir tient, le tick suivant n'y retouche pas."""
    ticket = _ticket_isole(tmp_path)
    brouillon = _brouillon(client, f"Fusionner agent/{ticket['id']}")
    integration.integrate_ticket(SLUG, ticket)
    micros.marquer_etat(brouillon, "brouillon")

    assert brouillon not in brouillons_integres.balayer()
    vue = ligne(client, brouillon)
    assert (vue["statut_ui"], vue["archive_auto"]) == ("brouillon", None)


def test_une_branche_cible_donnee_a_la_creation_est_suivie_quel_que_soit_le_titre(client):
    """`branche_cible` posée à la création (branche de travail existante, titre libre)."""
    from bouzecode.web_v2.services.work.fsm import etats
    from bouzecode.web_v2.tests.aides_tickets import semer
    semer(SLUG, "export01", etats.CLOSED, "integre", title="Export",
          worktree={"branch": "feature/export", "retire_at": "2026-09-24T21:18:00"},
          integration={"merged_at": "2026-09-24T21:18:00"})
    brouillon = _brouillon(client, "Livrer l'export", branche_cible="feature/export")

    assert brouillon in brouillons_integres.balayer()
    assert ligne(client, brouillon)["archive_auto"]["texte"] == \
        "Archivée automatiquement : branche feature/export intégrée le 24/09/2026 à 21:18."
