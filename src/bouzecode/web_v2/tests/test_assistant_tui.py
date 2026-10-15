# [desc] L'assistant du Bureau dans le terminal : `--assistant`, `/assistant` aligne sur `--profile`, identite tui:<id> rattachant ses lancements, Flotte(attendre_s), serveur arrete, ligne d'alerte des signalements. [/desc]
from __future__ import annotations

import json
import types

import pytest

from bouzecode.backend.tools import bureau_tools
from bouzecode.backend.tools.bureau_suivi import attendre
from bouzecode.ui import assistant_tui
from bouzecode.ui.cli import build_parser, profil_des_raccourcis
from bouzecode.web_v2.services.work import projects, signalements
from bouzecode.web_v2.tests.test_v3_gestes_des_taches import (  # noqa: F401 — fixtures
    _ticket, client, sans_spawn,
)

TUI = "tui:0123456789ab"


@pytest.fixture()
def identite(monkeypatch):
    monkeypatch.setenv(assistant_tui.ENV_TUI, TUI)
    monkeypatch.delenv("BOUZECODE_WEB_IPC_DIR", raising=False)
    return TUI


def test_option_assistant_choisit_le_profil_et_arme_l_identite(monkeypatch):
    monkeypatch.delenv(assistant_tui.ENV_TUI, raising=False)
    args = build_parser().parse_args(["--assistant"])

    assert args.assistant is True
    assert profil_des_raccourcis(args) == "bureau-assistant"
    import os
    assert os.environ[assistant_tui.ENV_TUI].startswith("tui:")
    assert profil_des_raccourcis(build_parser().parse_args(["--monitor"])) == "monitor"
    assert profil_des_raccourcis(build_parser().parse_args([])) == ""


def test_commande_assistant_aligne_sur_profile(identite):
    from bouzecode.backend.commands.dispatcher import COMMANDS
    from bouzecode.backend.core.tool_registry import is_enabled, restaurer_desactives_par_defaut
    import bouzecode.backend.tools.registration  # noqa: F401
    config = {}
    etat = types.SimpleNamespace(context_state=types.SimpleNamespace(notes={}))
    try:
        COMMANDS["assistant"]("", etat, config)
        assert config["_active_agent"] == "bureau-assistant"
        assert config["_plan_mode_disabled"] is True
        assert config["agent_profile_extra"] is False
        assert is_enabled("Taches") and is_enabled("Signaler") and is_enabled("AskUserQuestion")
        assert not is_enabled("Edit") and not is_enabled("Bash")

        COMMANDS["agent"]("default", etat, config)
        assert "_plan_mode_disabled" not in config and "agent_profile_extra" not in config
        assert not is_enabled("Mails"), "/agent default ne rallume pas les outils Graph"
    finally:
        restaurer_desactives_par_defaut()


def test_un_lancement_depuis_le_terminal_est_rattache_a_l_assistant(
        identite, client, sans_spawn, monkeypatch, tmp_path):
    (tmp_path / "demo").mkdir()
    projects.PROJECTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    projects.PROJECTS_PATH.write_text(json.dumps(
        [{"slug": "demo", "name": "demo", "path": str(tmp_path / "demo")}]), encoding="utf-8")
    monkeypatch.setattr(bureau_tools, "_http", lambda m, chemin, corps=None:
                        client.open(chemin, method=m, json=corps).get_json())

    rendu = bureau_tools.lancer_agent(prompt="Mesurer le temps de build", project_slug="demo")

    _, ticket = _ticket(rendu["ticket_id"])
    assert ticket["parent"] == TUI


def test_flotte_attendre_rend_la_main_au_premier_signalement(identite):
    arrivees = []

    def dormir(_secondes):
        if not arrivees:
            arrivees.append(signalements.creer("alerte", "Build lent", "12 min",
                                               agent_id="a1", parents=[TUI]))

    rendu = attendre(TUI, 120, intervalle=0.01, dormir=dormir)

    assert rendu["ok"] and not rendu["expire"]
    assert [s["titre"] for s in rendu["nouveaux_signalements"]] == ["Build lent"]


def test_flotte_attendre_expire_a_sa_borne(identite):
    instants = iter([0.0, 0.0, 700.0])
    rendu = attendre(TUI, 9999, dormir=lambda _s: None, horloge=lambda: next(instants))
    assert rendu["expire"] is True and rendu["borne_s"] == 600


def test_serveur_arrete_le_dit_avec_la_commande(identite, monkeypatch, tmp_path):
    (tmp_path / "demo").mkdir()
    projects.PROJECTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    projects.PROJECTS_PATH.write_text(json.dumps(
        [{"slug": "demo", "name": "demo", "path": str(tmp_path / "demo")}]), encoding="utf-8")
    monkeypatch.setenv("BOUZECODE_WEB_BASE_URL", "http://127.0.0.1:9")

    rendu = bureau_tools.lancer_agent(prompt="x", project_slug="demo")

    assert rendu["ok"] is False and "bouzeui.ps1" in rendu["consigne"]


def test_la_ligne_d_alerte_montre_chaque_signalement_une_fois(identite):
    signalements.creer("bloquant", "Quota atteint", "job 42", agent_id="a2", parents=[TUI])
    signalements.creer("info", "Hors lignee", "", agent_id="a3", parents=["autre"])

    premieres = assistant_tui.lignes_d_alerte()
    assert len(premieres) == 1 and "[bloquant] Quota atteint" in premieres[0]
    assert assistant_tui.lignes_d_alerte() == []


def test_l_assistant_lit_des_fichiers_mais_n_ecrit_rien():
    from bouzecode.backend.tools.registration import enabled_tools_for_profile
    autorises = enabled_tools_for_profile("bureau-assistant")
    assert {"Read", "Glob", "Grep", "Agenda", "Projets", "Signaler", "AskUserQuestion"} <= autorises
    assert not {"Edit", "Write", "Bash"} & autorises
