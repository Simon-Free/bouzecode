# [desc] `bouzecode tickets|projets` sans serveur web : lectures, création (brouillon, champ execution), clôture/réouverture, refus au code de l'API, routage depuis ui/cli.py. [/desc]
"""Aucun serveur ne tient le parc du test : chaque geste passe EN PROCESS par les services des
routes (`via: process`). Le parc, le store et le HOME sont ceux, jetables, du test."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import bouzecode
from bouzecode.ui import tickets_cli
from bouzecode.web_v2.services.work import tickets
from bouzecode.web_v2.tests.cli_tickets_aides import cli, cli_json, depot_demo

SRC = str(Path(bouzecode.__file__).resolve().parents[1])


def _creer_brouillon(capsys, *options: str) -> dict:
    code, corps = cli_json(capsys, "tickets", "creer", "--projet", "demo", "--titre", "Ajouter b",
                           "--prompt", "Ajoute b.txt", "--brouillon", *options)
    assert code == 0, corps
    return corps


def test_projets_fichiers_propose_le_plan_et_jamais_le_secret(tmp_path, capsys):
    depot_demo(tmp_path)
    code, corps = cli_json(capsys, "projets", "fichiers", "demo", "--indices", "plan")
    assert code == 0
    assert corps["proposes"] == ["notes/plan.md"]
    assert corps["secrets_signales"] == [".env"]
    code, texte, _ = cli(capsys, "projets", "fichiers", "demo")
    assert "! .env" in texte and "+ notes/plan.md" in texte


def test_creer_un_brouillon_puis_le_lire_le_lister_l_abandonner_et_le_rouvrir(tmp_path, capsys):
    depot_demo(tmp_path)
    corps = _creer_brouillon(capsys)
    ticket_id = corps["ticket_id"]
    assert corps["via"] == "process" and corps["state"] == "created"

    code, texte, _ = cli(capsys, "tickets", "lister", "--projet", "demo")
    assert code == 0 and ticket_id in texte and "Ajouter b" in texte
    code, fiche = cli_json(capsys, "tickets", "voir", "demo", ticket_id)
    assert fiche["prompt"] == "Ajoute b.txt" and fiche["runs"] == []
    assert any(e["kind"] for e in fiche["events"])

    code, texte, _ = cli(capsys, "tickets", "clore", "demo", ticket_id, "--abandon",
                         "--raison", "doublon")
    assert code == 0 and "abandoned" in texte
    assert tickets.get_ticket("demo", ticket_id)["state"] == "abandoned"
    code, corps = cli_json(capsys, "tickets", "rouvrir", "demo", ticket_id)
    assert code == 0 and tickets.get_ticket("demo", ticket_id)["state"] == "created"


def test_le_champ_execution_va_dans_le_prompt_et_sur_le_ticket(tmp_path, capsys):
    racine = depot_demo(tmp_path)
    corps = _creer_brouillon(capsys, "--fichier", "notes/plan.md", "--cible", "local")
    ticket = tickets.get_ticket("demo", corps["ticket_id"])
    assert ticket["execution"] == {"cible": "local", "projets": ["demo"],
                                   "fichiers_non_suivis": {"demo": ["notes/plan.md"]}}
    assert "## Execution" in ticket["prompt"]
    assert str(racine / "notes" / "plan.md") in ticket["prompt"]


def test_un_refus_dit_son_code_sur_stderr_et_sort_en_1(tmp_path, capsys):
    depot_demo(tmp_path)
    code, sortie, erreur = cli(capsys, "tickets", "voir", "demo", "inconnu")
    assert code == 1 and sortie == ""
    assert "Refus ticket_inconnu" in erreur
    code, corps = cli_json(capsys, "tickets", "creer", "--projet", "demo", "--titre", "t",
                           "--prompt", "p", "--brouillon", "--mode", "tests")
    assert code == 1 and corps["error"]["code"] == "options_distantes"
    code, corps = cli_json(capsys, "tickets", "creer", "--projet", "demo", "--titre", "t",
                           "--prompt", "p", "--fichier", "../hors.txt", "--brouillon")
    assert code == 1 and corps["error"]["code"] == "fichiers_invalides"


def test_un_geste_sur_un_ticket_sans_agent_est_refuse_comme_par_l_api(tmp_path, capsys):
    depot_demo(tmp_path)
    ticket_id = _creer_brouillon(capsys)["ticket_id"]
    code, corps = cli_json(capsys, "tickets", "message", "demo", ticket_id, "bonjour")
    assert code == 1 and corps["error"]["code"] == "pas_d_agent"
    assert corps["error"]["details"]["commentaire_conserve"] is True
    code, corps = cli_json(capsys, "tickets", "integrer", "demo", ticket_id)
    assert code == 1 and corps["error"]["code"] in ("pas_isole", "rien_a_integrer",
                                                     "transition_refusee")


def test_suivre_un_brouillon_rend_aussitot_fin_sans_livraison(tmp_path, capsys):
    depot_demo(tmp_path)
    ticket_id = _creer_brouillon(capsys)["ticket_id"]
    code, texte, _ = cli(capsys, "tickets", "suivre", "demo", ticket_id, "--intervalle", "0")
    assert code == 4 and "created" in texte


def test_la_ligne_de_commande_route_tickets_avant_le_parseur_du_repl(tmp_path):
    """`bouzecode tickets -h` n'est jamais pris pour un prompt : vrai process, HOME jetable."""
    assert tickets_cli.est_sous_commande(["tickets", "lister"])
    assert not tickets_cli.est_sous_commande(["corrige", "les", "tickets"])
    env = {**os.environ, "PYTHONPATH": SRC, "PYTHONIOENCODING": "utf-8"}
    fini = subprocess.run([sys.executable, "-m", "bouzecode", "tickets", "-h"], env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=120,
                          cwd=tmp_path)
    assert fini.returncode == 0, fini.stderr
    assert "suivre" in fini.stdout and "Codes de sortie" in fini.stdout
