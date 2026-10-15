# [desc] L'assistant du Bureau est réveillé quand une tâche qu'il a lancée finit ou pose une question : le ticket lui est rattaché (parent), et le réveil nomme la tâche, son état et la question en attente. [/desc]
"""TODO du 2026-09-25, §6 : « impression que l'assistant du bureau n'est pas réveillé quand un
agent termine ou quand un agent pose une question ».

Trois trous, tous sur le chemin du réveil (`wake.process_wakes`) :

1. RATTACHEMENT. L'assistant lance ses agents par `Taches(lancer)` / `LancerAgent`, qui passent
   par `/api/micros/<id>/lancer` : le ticket naissait avec `parent = dispatcher:manual`, comme un
   clic à l'écran. Le réveil regroupe les enfants PAR PARENT : l'assistant n'avait donc aucun
   enfant, et personne ne le réveillait jamais.
2. PROCESS CHAUD. Une conversation lancée à la main reste chaude un quart d'heure (IPC `idle`)
   et ce délai repart à chaque message de l'humain. Le réveil exigeait `finished` : un parent
   chaud qui avait pourtant clos son tour n'était réveillé qu'à l'expiration de son process.
3. RÈGLE DU MANAGER. Un manager n'est réveillé que quand TOUS ses enfants ont fini. L'assistant
   pilote des tâches indépendantes : chacune doit lui revenir dès qu'elle finit ou demande.

Fiches, sessions, IPC et tickets sont écrits sur disque comme le runner les écrit ; seul
`runner.continue_agent` (qui lancerait un process) est remplacé par un espion."""
from __future__ import annotations

import json

import pytest

from bouzecode.web_v2.runtime.runner import agent_commande, agent_fiche
from bouzecode.web_v2.services.work import dispatch, micros, projects, tickets, wake
from bouzecode.web_v2.tests.aides_tickets import constater_tout
from bouzecode.web_v2.tests.test_v3_statut_des_taches import (  # noqa: F401
    SLUG, client, ecrire_agent,
)
from bouzecode.web_v2.runtime.runner import agent_reprise

ASSISTANT = "a55157a47000"


def _tick() -> None:
    """Un passage du watchdog : il CONSTATE ce que les agents ont fait (fins, questions),
    puis réveille les parents (lot L2)."""
    constater_tout()
    wake.process_wakes()
TACHE_A = "aaaa00000001"
TACHE_B = "bbbb00000002"
MANAGER = "3a3a3a3a3a3a"


@pytest.fixture()
def reveils(monkeypatch, tmp_path):
    """Le projet est ouvert ; chaque réveil est noté au lieu de lancer un process."""
    projects.PROJECTS_PATH.write_text(json.dumps([{"slug": SLUG, "name": SLUG,
                                                   "path": str(tmp_path)}]), encoding="utf-8")
    monkeypatch.setattr(wake, "WAKE_STATE_PATH", tmp_path / "wake_state.json")
    notes: list[tuple[str, str]] = []
    monkeypatch.setattr(agent_reprise, "continue_agent",
                        lambda agent, message: notes.append((agent.agent_id, message)) or agent)
    return notes


def _profil(agent_id: str, profil: str) -> None:
    chemin = agent_fiche.AGENTS_DIR / f"{agent_id}.json"
    fiche = json.loads(chemin.read_text(encoding="utf-8"))
    chemin.write_text(json.dumps({**fiche, "profile": profil}), encoding="utf-8")
    agent_fiche._list_agents_cache.clear()


def _assistant_chaud() -> dict:
    """L'assistant a répondu à l'humain et attend la suite : process gardé chaud (`idle`).
    Rend le ticket de sa conversation."""
    conversation = tickets.create_ticket(SLUG, "fais le point", "fais le point")
    conversation.update(parent="dispatcher:manual", typology="bureau-assistant")
    tickets.update_ticket(SLUG, conversation)
    tickets.add_run(SLUG, conversation, ASSISTANT, "work", "m")
    ecrire_agent(ASSISTANT, vivant=True, ipc="idle", ticket_id=conversation["id"],
                 final={"answer": "J'ai lancé les deux tâches."})
    _profil(ASSISTANT, "bureau-assistant")
    return conversation


def _tache_lancee(titre: str, agent_id: str) -> tuple[str, dict]:
    """Une tâche du Bureau lancée PAR l'assistant : son ticket lui est rattaché."""
    micro = micros.create_micro(titre=titre, origine="assistant")
    ticket = tickets.create_ticket(SLUG, titre, titre)
    ticket["parent"] = ASSISTANT
    tickets.update_ticket(SLUG, ticket)
    tickets.add_run(SLUG, ticket, agent_id, "work", "m")
    micros.lier_ticket(micro["id"], slug=SLUG, ticket_id=ticket["id"])
    micros.marquer_etat(micro["id"], "lancee")
    return micro["id"], tickets.get_ticket(SLUG, ticket["id"])


# ── 1. Rattachement : la tâche lancée par l'assistant est SON enfant ────────────

@pytest.fixture()
def depot(tmp_path):
    chemin = tmp_path / "depot"
    chemin.mkdir()
    projects.PROJECTS_PATH.write_text(json.dumps([{"slug": SLUG, "name": SLUG,
                                                   "path": str(chemin)}]), encoding="utf-8")


@pytest.fixture()
def sans_spawn(monkeypatch):
    appels: list[tuple] = []
    monkeypatch.setattr(dispatch, "_launch_bg", lambda *args, **kw: appels.append(args))
    return appels


def test_l_outil_taches_lancer_transmet_l_assistant_comme_parent(monkeypatch, tmp_path):
    """L'outil parle au serveur par HTTP : il doit dire QUI lance, sinon le serveur ne sait
    pas à qui rendre compte."""
    from bouzecode.backend.tools import bureau_tools

    monkeypatch.setenv("BOUZECODE_WEB_IPC_DIR", str(tmp_path / f"{ASSISTANT}.ipc"))
    appels: list[tuple] = []
    monkeypatch.setattr(bureau_tools, "_http",
                        lambda methode, chemin, corps=None: appels.append((chemin, corps)) or {})
    micro = micros.create_micro(titre="corriger l'export CSV")

    bureau_tools.taches(action="lancer", task_id=micro["id"], projet_slug=SLUG)
    bureau_tools.taches(action="relancer", task_id=micro["id"], texte="encore", projet_slug=SLUG)
    bureau_tools.lancer_agent(prompt="mesurer la latence", project_slug=SLUG)

    assert [corps.get("parent") for _, corps in appels] == [ASSISTANT] * 3


def test_hors_agent_web_aucun_parent_n_est_invente(monkeypatch):
    from bouzecode.backend.tools import bureau_tools

    monkeypatch.delenv("BOUZECODE_WEB_IPC_DIR", raising=False)
    appels: list[dict] = []
    monkeypatch.setattr(bureau_tools, "_http",
                        lambda methode, chemin, corps=None: appels.append(corps) or {})
    micro = micros.create_micro(titre="corriger l'export CSV")

    bureau_tools.taches(action="lancer", task_id=micro["id"], projet_slug=SLUG)

    assert "parent" not in appels[0]


def test_la_route_lancer_rattache_le_ticket_a_l_assistant_sans_changer_le_profil(
        client, depot, sans_spawn):
    """Le ticket porte l'assistant comme parent ; l'agent part avec le MÊME profil qu'un
    lancement depuis l'écran (pas de défaut « coder » parce qu'il a un parent)."""
    micro = micros.create_micro(titre="corriger l'export CSV")

    reponse = client.post(f"/api/micros/{micro['id']}/lancer",
                          json={"projet_slug": SLUG, "parent": ASSISTANT})

    assert reponse.status_code == 200, reponse.get_data(as_text=True)
    ticket = tickets.get_ticket(SLUG, reponse.get_json()["ticket_id"])
    assert ticket["parent"] == ASSISTANT
    (_slug, _ticket, _path, profil, _model, _mode, parent, *_reste), = sans_spawn
    assert (profil, parent) == ("", ASSISTANT)


def test_sans_parent_la_route_garde_le_lancement_manuel(client, depot, sans_spawn):
    micro = micros.create_micro(titre="corriger l'export CSV")

    reponse = client.post(f"/api/micros/{micro['id']}/lancer", json={"projet_slug": SLUG})

    ticket = tickets.get_ticket(SLUG, reponse.get_json()["ticket_id"])
    assert not ticket.get("parent")  # un humain : aucun parent, plus de faux parent littéral


@pytest.fixture()
def depot_git(tmp_path):
    """Un dépôt de CODE (git) : c'est là que le défaut `coder` d'un lancement managé mord."""
    import subprocess
    chemin = tmp_path / "depot_git"
    chemin.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=chemin, check=True)
    projects.PROJECTS_PATH.write_text(json.dumps([{"slug": SLUG, "name": SLUG,
                                                   "path": str(chemin)}]), encoding="utf-8")


@pytest.fixture()
def relance_depuis_l_ecran(monkeypatch, client):
    """POST /api/projects/<slug>/tickets/<id>/runs (bouton « relancer » d'un ticket), corps
    vide ; rend le profil avec lequel l'agent serait parti."""
    from bouzecode.web_v2 import api_sanity, python_env_sanity
    from bouzecode.web_v2.runtime.runner import agent_creation

    monkeypatch.setattr(api_sanity, "require_api_sanity", lambda: None)
    monkeypatch.setattr(python_env_sanity, "require_python_env", lambda: None)
    profils: list[str] = []

    class _Agent:
        agent_id = "relance00001"

    monkeypatch.setattr(agent_creation, "create_agent",
                        lambda *a, profile="", **kw: profils.append(profile) or _Agent())

    def relancer(ticket_id: str) -> str:
        reponse = client.post(f"/api/projects/{SLUG}/tickets/{ticket_id}/runs",
                              json={"defer": False})
        assert reponse.status_code == 202, reponse.get_data(as_text=True)
        return profils[-1]
    return relancer


def test_une_tache_de_l_assistant_relancee_depuis_l_ecran_garde_son_profil(
        client, depot_git, sans_spawn, relance_depuis_l_ecran):
    """Rattachée à l'assistant, la tâche a un parent agent ; relancée par le bouton du ticket,
    elle ne doit pas prendre le défaut `coder` d'un enfant de manager — même profil qu'au
    lancement (celui d'un lancement depuis l'écran)."""
    micro = micros.create_micro(titre="corriger l'export CSV")
    reponse = client.post(f"/api/micros/{micro['id']}/lancer",
                          json={"projet_slug": SLUG, "parent": ASSISTANT})
    ticket_id = reponse.get_json()["ticket_id"]
    (_slug, _ticket, _path, profil_initial, *_reste), = sans_spawn
    dispatch.record_launch_failure(SLUG, {"id": ticket_id}, "spawn simulé")  # rien n'a démarré

    assert relance_depuis_l_ecran(ticket_id) == profil_initial == ""


def test_un_passage_manuel_rattache_par_l_assistant_garde_son_profil_a_la_relance(
        depot_git, relance_depuis_l_ecran):
    """`_rattacher` (l'assistant relance en « continuer » un passage lancé à la main) le rend
    enfant de l'assistant pour le réveil, pas enfant MANAGÉ."""
    from bouzecode.web_v2.services.work import taches_actions

    ticket = tickets.create_ticket(SLUG, "passage manuel", "fais-le")
    ticket["parent"] = "dispatcher:manual"
    tickets.update_ticket(SLUG, ticket)
    taches_actions._rattacher(SLUG, ticket, ASSISTANT)

    assert tickets.get_ticket(SLUG, ticket["id"])["parent"] == ASSISTANT
    assert relance_depuis_l_ecran(ticket["id"]) == ""


def test_l_enfant_d_un_manager_relance_depuis_l_ecran_garde_le_defaut_coder(
        depot_git, relance_depuis_l_ecran):
    """Contrôle : un vrai enfant managé garde son défaut `coder` à la relance."""
    ticket = tickets.create_ticket(SLUG, "lot A", "lot A")
    ticket["parent"] = MANAGER
    tickets.update_ticket(SLUG, ticket)

    assert relance_depuis_l_ecran(ticket["id"]) == "coder"


def test_l_agent_d_une_tache_de_l_assistant_n_est_pas_traite_en_delegue(client, depot, sans_spawn):
    """Son parent (l'assistant) est prévenu, mais son prompt est la tâche de l'humain : l'env
    du process le dit (`BOUZECODE_BRIEF_HUMAIN`), la porte des parcours d'interface s'applique
    comme pour un lancement depuis l'écran. L'enfant d'un manager reste délégué."""
    micro = micros.create_micro(titre="corriger l'export CSV")
    ticket_id = client.post(f"/api/micros/{micro['id']}/lancer",
                            json={"projet_slug": SLUG, "parent": ASSISTANT}).get_json()["ticket_id"]
    enfant = tickets.create_ticket(SLUG, "lot A", "lot A")
    enfant["parent"] = MANAGER
    tickets.update_ticket(SLUG, enfant)

    def env(parent: str, tid: str) -> dict:
        return agent_commande._ticket_env(agent_fiche.Agent(
            agent_id="e0e0e0e0e0e0", prompt="p", model="m", cwd="/tmp", pid=0, started_at="",
            parent=parent, ticket_slug=SLUG, ticket_id=tid))

    tache = env(ASSISTANT, ticket_id)
    assert tache["BOUZECODE_PARENT"] == ASSISTANT and tache.get("BOUZECODE_BRIEF_HUMAIN") == "1"
    assert "BOUZECODE_BRIEF_HUMAIN" not in env(MANAGER, enfant["id"])


# ── 2 et 3. Le réveil : chaud, à chaque fin, à chaque question ─────────────────

def test_l_assistant_chaud_est_reveille_des_qu_une_de_ses_taches_finit(reveils):
    """Une tâche finie, l'autre tourne encore : l'assistant est réveillé pour la première,
    avec la tâche (titre, id), le ticket, l'agent et le rapport."""
    _assistant_chaud()
    micro_a, ticket_a = _tache_lancee("corriger l'export CSV", TACHE_A)
    _tache_lancee("mesurer la latence", TACHE_B)
    ecrire_agent(TACHE_A, ticket_id=ticket_a["id"], final={"answer": "Export corrigé, 3 tests."})
    ecrire_agent(TACHE_B, vivant=True, ipc="running")

    _tick()

    assert [agent for agent, _ in reveils] == [ASSISTANT]
    digest = reveils[0][1]
    assert "corriger l'export CSV" in digest and micro_a in digest
    assert ticket_a["id"] in digest and TACHE_A in digest
    assert "Export corrigé, 3 tests." in digest
    assert "mesurer la latence" in digest  # rappelée comme toujours en cours

    _tick()
    assert len(reveils) == 1, "la même fin a réveillé l'assistant deux fois"


def test_l_assistant_est_reveille_par_la_question_d_une_de_ses_taches(reveils):
    """La question arrive avec son texte, ses options, et la façon d'y répondre."""
    _assistant_chaud()
    micro_b, ticket_b = _tache_lancee("mesurer la latence", TACHE_B)
    ecrire_agent(TACHE_B, vivant=True, ipc="awaiting_input", ticket_id=ticket_b["id"],
                 question="Quel format de date ?")

    _tick()

    assert [agent for agent, _ in reveils] == [ASSISTANT]
    digest = reveils[0][1]
    assert "Quel format de date ?" in digest and "ISO" in digest and "Locale" in digest
    assert micro_b in digest and TACHE_B in digest
    assert 'Taches(action="repondre"' in digest


def test_l_assistant_en_plein_tour_n_est_pas_interrompu(reveils):
    """Il parle avec l'humain : le réveil attend la fin de son tour (tick suivant)."""
    _assistant_chaud()
    _, ticket_a = _tache_lancee("corriger l'export CSV", TACHE_A)
    ecrire_agent(TACHE_A, ticket_id=ticket_a["id"], final={"answer": "fait"})
    ecrire_agent(ASSISTANT, vivant=True, ipc="running", ticket_id="")
    _profil(ASSISTANT, "bureau-assistant")

    _tick()

    assert reveils == []


def test_une_fin_pendant_l_arret_de_l_assistant_lui_est_rendue_a_la_levee(reveils):
    """Arrêt demandé : pas de réveil. Mais la fin n'est pas marquée vue pour autant — l'humain
    lui reparle (arrêt levé), son tour se clôt : il apprend alors que la tâche a fini. Avant,
    les événements étaient notés AVANT le test d'arrêt et ne le réveillaient plus jamais."""
    from bouzecode.web_v2.services.work import arret

    conversation = _assistant_chaud()
    arret.poser(SLUG, tickets.get_ticket(SLUG, conversation["id"]), "humain")
    _, ticket_a = _tache_lancee("corriger l'export CSV", TACHE_A)
    ecrire_agent(TACHE_A, ticket_id=ticket_a["id"], final={"answer": "Export corrigé."})

    _tick()
    assert reveils == []

    arret.lever(SLUG, tickets.get_ticket(SLUG, conversation["id"]))
    _tick()

    assert [agent for agent, _ in reveils] == [ASSISTANT]
    assert "corriger l'export CSV" in reveils[0][1] and "Export corrigé." in reveils[0][1]


def test_un_manager_chaud_qui_a_clos_son_tour_est_reveille(reveils):
    """Même trou pour un manager lancé à la main : clos pour attendre, process gardé chaud —
    il n'était réveillé qu'à l'expiration de son process (15 min après son dernier message)."""
    manager = tickets.create_ticket(SLUG, "coordonner", "coordonner")
    manager.update(parent="dispatcher:manual", typology="manager")
    tickets.update_ticket(SLUG, manager)
    tickets.add_run(SLUG, manager, MANAGER, "work", "m")
    ecrire_agent(MANAGER, vivant=True, ipc="idle", ticket_id=manager["id"],
                 final={"answer": "Lot délégué, j'attends."})
    enfant = tickets.create_ticket(SLUG, "lot A", "lot A")
    enfant["parent"] = MANAGER
    tickets.update_ticket(SLUG, enfant)
    tickets.add_run(SLUG, enfant, TACHE_A, "work", "m")
    ecrire_agent(TACHE_A, ticket_id=enfant["id"], final={"answer": "lot A fait"})

    _tick()

    assert [agent for agent, _ in reveils] == [MANAGER]
    assert "Tous tes enfants ont fini leur tour" in reveils[0][1]
