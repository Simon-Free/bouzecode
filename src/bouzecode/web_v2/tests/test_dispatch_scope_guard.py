# [desc] La création de ticket d'un manager (outil Agent → POST /api/projects/{slug}/tickets) signale un ticket en doublon de périmètre et un mandat read-only non tenu. [/desc]
"""Le garde-fou de périmètre est branché sur la VRAIE voie de dispatch du manager.

Le détail des détections est couvert par `test_scope_guard.py` ; ici on vérifie qu'elles
sont effectivement appelées par la création de ticket de l'outil `Agent`, que le drapeau atterrit sur le ticket
(donc visible en UI et interrogeable) et que l'avertissement remonte dans la réponse — le
manager est le seul acteur capable de corriger son découpage.
"""
from __future__ import annotations

import json

import pytest

from bouzecode.backend.multi_agent import client_tickets
from bouzecode.web_v2.runtime.runner import agent_fiche
from bouzecode.web_v2.services import scope_guard
from bouzecode.web_v2.services.work import dispatch, projects, tickets
from bouzecode.web_v2.services.work.fsm import etats
from bouzecode.web_v2.tests.scope_guard_prompts import (
    DIRECTE_B, DIRECTE_ECRIVAIN, INDIRECTE_BLOQUANTE, INDIRECTE_TICKET_A,
)

SLUG = "demo-application"
MANAGER_ID = "6b4a9ce79dc1"


@pytest.fixture()
def projet(tmp_path):
    path = tmp_path / "demo_application"
    path.mkdir()
    projects.PROJECTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    projects.PROJECTS_PATH.write_text(
        json.dumps([{"slug": SLUG, "name": "demo_application", "path": str(path)}]),
        encoding="utf-8")
    return path


@pytest.fixture()
def manager(tmp_path, monkeypatch, projet):
    """Un manager déjà lancé : c'est lui le `parent` de tous les tickets dispatchés."""
    agents = tmp_path / "web_agents"
    agents.mkdir()
    monkeypatch.setattr(agent_fiche, "AGENTS_DIR", agents)
    (agents / f"{MANAGER_ID}.json").write_text(json.dumps({
        "agent_id": MANAGER_ID, "prompt": "implémente les deux mesures", "model": "opus",
        "cwd": str(projet), "pid": 4242, "started_at": "2026-07-27T10:00:00",
        "ticket_slug": SLUG, "ticket_id": "31b01ead", "parent": "dispatcher:manual",
    }), encoding="utf-8")
    return MANAGER_ID


@pytest.fixture(autouse=True)
def sans_lancement(monkeypatch):
    """Le dispatch crée le ticket pour de vrai ; seul le spawn du process est neutralisé."""
    class _Spawned:
        agent_id = "enfant-1"

    monkeypatch.setattr(dispatch, "_launch", lambda *_, **__: _Spawned())


def _dispatcher(prompt: str, manager: str, typology: str = "coder") -> dict:
    """Un enfant du manager, créé dans le store (le contrôle de périmètre est appelé à part)."""
    ticket = tickets.create_ticket(SLUG, prompt.splitlines()[0][:80], prompt)
    tickets.poser(SLUG, ticket, parent=manager, typology=typology, isolation="shared")
    return {"ticket_id": ticket["id"]}


def _relire(ticket_id: str) -> dict:
    return tickets.get_ticket(SLUG, ticket_id)


def test_le_second_ecrivain_sur_le_meme_livrable_est_drapeaute_sur_son_ticket(manager):
    premier = _dispatcher(DIRECTE_B, manager)
    second = _dispatcher(DIRECTE_ECRIVAIN, manager)

    avertissements = scope_guard.review_dispatch(
        SLUG, second["ticket_id"], DIRECTE_ECRIVAIN, "coder", manager)

    ticket = _relire(second["ticket_id"])
    assert ticket[scope_guard.OVERLAP_FLAG_KEY] == [premier["ticket_id"]]
    assert any(premier["ticket_id"] in c["text"] for c in ticket["comments"])
    assert any("DOUBLON" in a for a in avertissements)


def test_lautre_moitie_de_la_demande_passe_sans_etre_drapeautee(manager):
    _dispatcher(DIRECTE_B, manager)
    autre = _dispatcher(INDIRECTE_TICKET_A, manager, typology="general-purpose")

    scope_guard.review_dispatch(SLUG, autre["ticket_id"], INDIRECTE_TICKET_A,
                                "general-purpose", manager)

    assert scope_guard.OVERLAP_FLAG_KEY not in _relire(autre["ticket_id"])


def test_un_ticket_read_only_confie_a_coder_est_drapeaute(manager):
    ticket_id = _dispatcher(INDIRECTE_BLOQUANTE, manager)["ticket_id"]

    avertissements = scope_guard.review_dispatch(
        SLUG, ticket_id, INDIRECTE_BLOQUANTE, "coder", manager)

    ticket = _relire(ticket_id)
    assert "Write" in ticket[scope_guard.READONLY_FLAG_KEY]
    assert any("READ-ONLY" in c["text"] for c in ticket["comments"])
    assert any("READ-ONLY" in a for a in avertissements)


def test_un_premier_ticket_sans_frere_ne_declenche_rien(manager):
    ticket_id = _dispatcher(DIRECTE_B, manager)["ticket_id"]

    assert scope_guard.review_dispatch(SLUG, ticket_id, DIRECTE_B, "coder", manager) == []


@pytest.fixture()
def client_web(monkeypatch):
    """Client de la vraie app. `require_api_sanity` refuse 503 tout dispatch sans
    environnement API joignable : on passe par le seam d'injection prévu (env + sonde),
    pas par du mock, et on rend le module à son état neuf après le test."""
    from bouzecode.web_v2 import api_sanity
    from bouzecode.web_v2.app import create_app

    client = create_app().test_client()
    from bouzecode.web_v2.tests.client_de_l_outil import brancher
    brancher(monkeypatch, client)
    #  Modèle Anthropic explicite : le verdict ne dépend pas du modèle par défaut du code (un
    #  défaut préprod exigeait sinon PREPROD_ENDPOINT et toute la suite tombait en 503).
    api_sanity.capture_api_sanity(
        env={"ANTHROPIC_BASE_URL": "http://api.test", "ANTHROPIC_API_KEY": "test-key"},
        ping=lambda *_, **__: True, sleep=lambda *_: None, model="claude-opus-5")
    yield client
    api_sanity.reset_api_sanity()


def _vu_par_l_outil(corps: dict) -> dict:
    """La création telle que la fait l'outil Agent (`client_tickets.creer_ticket`, branché sur
    l'app de test) : un refus revient en `{routed: False, code, error}`."""
    return client_tickets.creer_ticket(corps)


def test_un_second_enfant_sur_le_perimetre_d_un_enfant_actif_est_refuse(manager, client_web):
    """Essai du 2026-09-25 : le doublon n'était qu'un avertissement, deux enfants ont réécrit
    le même scraper. Tant que le premier travaille, le second n'est PAS créé, et le refus dit
    lequel attendre ou réorienter."""
    corps = {"prompt": DIRECTE_B, "parent": manager, "typology": "coder", "isolation": "shared"}
    premier = _vu_par_l_outil(corps)

    corps["prompt"] = DIRECTE_ECRIVAIN
    reponse = _vu_par_l_outil(corps)

    assert reponse["routed"] is False and reponse["code"] == "doublon"
    assert "AUCUN enfant n'a été créé" in reponse["error"]
    assert premier["ticket_id"] in reponse["error"] and "doublon_assume" in reponse["error"]
    enfants = [t for t in tickets.list_tickets(SLUG) if t.get("parent") == manager]
    assert [t["id"] for t in enfants] == [premier["ticket_id"]]


def test_un_doublon_assume_avec_sa_raison_est_cree_et_signale(manager, client_web):
    """Le parent l'assume : l'enfant est créé, l'avertissement remonte, la raison est sur le ticket."""
    corps = {"prompt": DIRECTE_B, "parent": manager, "typology": "coder", "isolation": "shared"}
    _vu_par_l_outil(corps)

    corps.update(prompt=DIRECTE_ECRIVAIN, doublon_assume="ok")
    trop_court = _vu_par_l_outil(corps)
    corps["doublon_assume"] = "variante concurrente exprès : on gardera la plus rapide"
    reponse = _vu_par_l_outil(corps)

    assert trop_court["routed"] is False and "trop courte" in trop_court["error"]
    assert reponse["routed"] is True
    assert any("DOUBLON" in a for a in reponse["scope_warnings"])
    ticket = _relire(reponse["ticket_id"])
    assert ticket["lancement"]["doublon_assume"].startswith("variante concurrente")


def test_relancer_le_meme_perimetre_apres_la_fin_du_premier_enfant_n_est_que_signale(
        manager, client_web):
    """Contrôle : le premier enfant a rendu la main (ici : son lancement a échoué) ; relancer le
    même travail est légitime — signalé, pas refusé."""
    corps = {"prompt": DIRECTE_B, "parent": manager, "typology": "coder", "isolation": "shared"}
    premier = _vu_par_l_outil(corps)
    dispatch.record_launch_failure(SLUG, _relire(premier["ticket_id"]), "provisionnement impossible")
    assert _relire(premier["ticket_id"])["state"] == etats.LAUNCH_FAILED

    corps["prompt"] = DIRECTE_ECRIVAIN
    reponse = _vu_par_l_outil(corps)

    assert reponse["routed"] is True
    assert any("DOUBLON" in a for a in reponse["scope_warnings"])


def test_deux_enfants_paralleles_sur_des_perimetres_disjoints_passent(manager, client_web):
    """Contrôle : l'autre moitié de la demande, lancée pendant que le premier travaille."""
    corps = {"prompt": DIRECTE_B, "parent": manager, "typology": "coder", "isolation": "shared"}
    _vu_par_l_outil(corps)

    corps.update(prompt=INDIRECTE_TICKET_A, typology="general-purpose")
    reponse = _vu_par_l_outil(corps)

    assert reponse["routed"] is True
    assert not any("DOUBLON" in a for a in reponse.get("scope_warnings") or [])


def test_deux_freres_du_meme_lot_au_meme_perimetre_ne_sont_pas_crees_ensemble(
        manager, client_web, monkeypatch):
    """Les N Agent d'un même message partent ensemble : leurs créations de ticket arrivent en
    même temps. Le second doit voir le ticket du premier ; sans verrou par parent autour du
    contrôle ET de la création, les deux passaient le contrôle avant qu'aucun n'existe.

    La barrière force l'entrelacement du défaut : chaque requête attend, AVANT de créer son
    ticket, que l'autre ait fini son contrôle. Sous le verrou, la seconde n'atteint jamais ce
    point pendant que la première l'occupe : la barrière expire et la première crée seule."""
    import threading

    barriere = threading.Barrier(2)
    creer = tickets.create_ticket

    def creer_apres_le_controle_du_frere(*args, **kwargs):
        try:
            barriere.wait(timeout=1.5)
        except threading.BrokenBarrierError:
            pass  # attendu sous le verrou : le frère n'atteint jamais ce point en même temps
        return creer(*args, **kwargs)
    monkeypatch.setattr(tickets, "create_ticket", creer_apres_le_controle_du_frere)

    reponses: list[dict] = []

    def lancer(prompt: str) -> None:
        corps = {"prompt": prompt, "parent": manager, "typology": "coder", "defer": True,
                 "isolation": "shared"}
        reponses.append(_vu_par_l_outil(corps))
    fils = [threading.Thread(target=lancer, args=(p,)) for p in (DIRECTE_B, DIRECTE_ECRIVAIN)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(timeout=30)

    enfants = [t for t in tickets.list_tickets(SLUG) if t.get("parent") == manager]
    assert len(enfants) == 1, [r.get("ticket_id") or r.get("code") for r in reponses]
    assert sorted(bool(r["routed"]) for r in reponses) == [False, True]
    assert next(r for r in reponses if not r["routed"])["code"] == "doublon"


def _avec_la_note_de_l_outil(brief: str) -> str:
    """Le brief tel que l'outil Agent l'envoie quand le parent a des fichiers non commités."""
    return (f"{brief}\n\n[Note de l'outil] Ton agent parent avait des fichiers NON commités au "
            "moment de te déléguer (SPEC_COMMUNE.md) : ils ne sont pas dans ta branche de départ. "
            "Si tu en as besoin, lis-les (lecture seule) dans son worktree "
            "/tmp/bz-sb/.bouzecode/worktrees/demo-api/2b682b8e, ou demande-lui de les commiter.")


def test_la_note_de_l_outil_commune_aux_briefs_ne_fait_pas_un_doublon(manager, client_web):
    """E2E du 2026-09-25 (scénario manager-worktree) : « écrire enfant_a.md » puis « écrire
    enfant_b.md », chacun suivi de la même note sur la spec non commitée du parent, étaient
    refusés comme doublons à 93 % — la note et le chemin du worktree faisaient le périmètre."""
    corps = {"prompt": _avec_la_note_de_l_outil("Enfant A : écrire enfant_a.md\nFichier : enfant_a.md"),
             "parent": manager, "typology": "coder", "isolation": "shared"}
    _vu_par_l_outil(corps)

    corps["prompt"] = _avec_la_note_de_l_outil("Enfant B : écrire enfant_b.md\nFichier : enfant_b.md")
    reponse = _vu_par_l_outil(corps)

    assert reponse["routed"] is True, reponse.get("error")
    assert not any("DOUBLON" in a for a in reponse.get("scope_warnings") or [])


def test_un_vrai_doublon_reste_refuse_meme_avec_la_note_de_l_outil(manager, client_web):
    """Contrôle : retirer la note ne masque pas le périmètre du brief lui-même."""
    corps = {"prompt": _avec_la_note_de_l_outil(DIRECTE_B), "parent": manager, "typology": "coder", "isolation": "shared"}
    _vu_par_l_outil(corps)

    corps["prompt"] = _avec_la_note_de_l_outil(DIRECTE_ECRIVAIN)
    reponse = _vu_par_l_outil(corps)

    assert reponse["routed"] is False and reponse["code"] == "doublon"

def test_le_parent_retrouve_le_tour_et_le_nom_de_chaque_lancement(manager, client_web):
    """Ce que l'outil Agent envoie (tour, nom) est gardé sur le ticket et rendu dans /children."""
    corps = {"prompt": DIRECTE_B, "parent": manager, "typology": "coder",
             "name": "scraper-fix", "parent_turn": 66, "isolation": "shared"}
    ticket_id = _vu_par_l_outil(corps)["ticket_id"]

    enfants = client_web.get(f"/api/agents/{manager}/children").get_json()["children"]

    fiche = next(f for f in enfants if f["ticket_id"] == ticket_id)
    assert fiche["lancement"] == {"tour": 66, "nom": "scraper-fix"}
    assert fiche["objectif"].startswith("OBJECTIF : compter les ouvertures")


def _outil(nom: str, i: str, **params) -> str:
    corps = "".join(f'<param name="{k}">{v}</param>' for k, v in params.items())
    return f'<tool_use name="{nom}" id="{i}">{corps}</tool_use>'


def test_la_racine_ne_peut_pas_relancer_son_enfant_et_sait_qu_elle_l_a_lance(
        manager, client_web, monkeypatch):
    """Conversation de l'essai du 2026-09-25 rejouée : Agent « scraper-fix », puis le même
    périmètre deux tours plus tard. Le second est refusé en nommant le premier ; ListAgentTasks
    et la note disent que c'est elle qui l'a lancé, à quel tour, sous quel nom."""
    from tests.e2e_harness import bouzecode
    from tests.fake_llm import MockLLM

    monkeypatch.setenv("BOUZECODE_WEB_IPC_DIR", str(agent_fiche.AGENTS_DIR / f"{manager}.ipc"))

    def get(url):
        return client_web.get("/" + url.split("127.0.0.1", 1)[-1].split("/", 1)[-1]).get_json()
    config = {"_web_dispatch": lambda corps: _vu_par_l_outil(corps),
              "_web_get": get}
    mock = MockLLM([
        _outil("Agent", "a1", prompt=DIRECTE_B, name="scraper-fix", subagent_type="coder",
               background="true"),
        _outil("Bash", "b1", command="echo travail"),
        _outil("Agent", "a2", prompt=DIRECTE_ECRIVAIN, name="scraper-fix", subagent_type="coder",
               background="true"),
        _outil("ListAgentTasks", "l1"),
        "J'attends mon enfant.",
    ])
    result = bouzecode(["Délègue le scraper."], mock_llm=mock, config_overrides=config)

    sorties = {m["tool_call_id"]: str(m["content"]) for m in result.messages if m["role"] == "tool"}
    premier = next(t["id"] for t in tickets.list_tickets(SLUG) if t.get("parent") == manager)
    assert sorties["a2"].startswith("Error: dispatch REFUSÉ, aucun enfant n'a été créé")
    assert "PÉRIMÈTRE EN DOUBLON" in sorties["a2"] and premier in sorties["a2"]
    assert "lancé par toi au tour 1 sous le nom « scraper-fix »" in sorties["a2"]
    assert f"{premier} | lancé par toi au tour 1 sous le nom « scraper-fix »" in sorties["l1"]
    assert "objectif : OBJECTIF : compter les ouvertures" in sorties["l1"]
    note = str(result.state.context_state.notes)
    assert f"Enfant lancé au tour 1 : ticket {premier} « scraper-fix »" in note
    assert len([t for t in tickets.list_tickets(SLUG) if t.get("parent") == manager]) == 1
