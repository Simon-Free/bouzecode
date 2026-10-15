# [desc] Un agent TUÉ dont l'IPC est resté figé à « running » : aucune surface (vue d'ensemble de l'assistant, garde-fou « un autre agent écrit dans ce dépôt », tâche occupée, enfants actifs) ne le croit encore au travail. Vrai sous-processus tué, pas de pid inventé. [/desc]
"""Essai du 2026-09-25 : la racine 6bafe9cd5ee7 a été tuée (SIGTERM) pendant une reprise
indésirable. Un process tué n'écrit plus rien : son `state.json` est resté `running`. Le serveur
sait réconcilier (`runner.processus_absent`, `fin_constatee`, `refresh_agent_status`) ; ce test
vérifie que CHAQUE lecteur qui décide « un agent travaille encore » passe par cet état réconcilié
et jamais par l'IPC brut.

On lance un vrai sous-processus, on écrit sa fiche comme le runner (pid + instant de création,
returncode inconnu, IPC `running`), puis on le tue SANS que le serveur l'observe."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time

import psutil
import pytest

from bouzecode.backend.tools import bureau_tools
from bouzecode.web_v2.runtime.runner import agent_chaud, agent_fiche, agent_registre, agent_vivacite
from bouzecode.web_v2.services.sessions import store
from bouzecode.web_v2.services.work import (
    bilan_chantier, enfants, file_messages, isolation, micros, taches_actions, tickets,
)
from bouzecode.web_v2.tests.aides_tickets import constater_tout

SLUG = "portail"
AGENT = "6bafe9cd5ee7"
PARENT = "aaaa11112222"


def _depot(tmp_path) -> str:
    depot = tmp_path / "portail-enigmes"
    depot.mkdir()
    subprocess.run(["git", "init", "-q", str(depot)], check=True)
    return str(depot)


def _fiche(agent_id: str, proc: subprocess.Popen, cwd: str, ticket_id: str) -> None:
    """La fiche telle que le runner l'écrit au spawn, et l'IPC tel que le process l'a laissé."""
    parc = agent_fiche.AGENTS_DIR
    session = parc / f"{agent_id}.session.json"
    (parc / f"{agent_id}.json").write_text(json.dumps({
        "agent_id": agent_id, "prompt": "Scraper les énigmes", "model": "m", "cwd": cwd,
        "pid": proc.pid, "pid_create_time": psutil.Process(proc.pid).create_time(),
        "started_at": "2026-09-24T21:18:54Z", "returncode": None, "finished_at": "",
        "session_path": str(session), "stdout_path": str(parc / f"{agent_id}.out.log"),
        "ipc_dir": str(parc / f"{agent_id}.ipc"), "parent": PARENT,
        "ticket_slug": SLUG, "ticket_id": ticket_id,
    }), encoding="utf-8")
    session.write_text(json.dumps({"messages": [{"role": "user", "content": "go"}],
                                   "close_reason": ""}), encoding="utf-8")
    (parc / f"{agent_id}.ipc").mkdir(parents=True, exist_ok=True)
    (parc / f"{agent_id}.ipc" / "state.json").write_text(
        json.dumps({"status": "running", "updated_at": time.time(), "turn": 144}),
        encoding="utf-8")
    agent_fiche._list_agents_cache.clear()
    agent_registre._agent_file_cache.clear()
    store.invalidate_status(agent_id)


def _mort_non_ramasse(pid: int) -> bool:
    """POSIX : l'état zombie. Windows n'a pas d'état zombie : un process tué dont le parent
    n'a pas encore lu le code de sortie (handle `Popen` encore ouvert) n'est plus listé par
    le système (psutil : NoSuchProcess) — c'est l'état équivalent à observer."""
    if os.name == "nt":
        return not psutil.pid_exists(pid)
    return psutil.Process(pid).status() == psutil.STATUS_ZOMBIE


def _attendre_zombie(pid: int) -> None:
    fin = time.monotonic() + 10
    while not _mort_non_ramasse(pid):
        assert time.monotonic() < fin, "le process tué n'est jamais devenu zombie"
        time.sleep(0.02)


@pytest.fixture(params=["ramasse", "zombie"])
def agent_tue(tmp_path, request):
    """Une tâche lancée dont l'agent (vrai process, cwd = le dépôt) vient d'être tué : son code
    de sortie déjà ramassé par son parent, ou pas encore (zombie, comme sous un serveur occupé)."""
    depot = _depot(tmp_path)
    macro = micros.ensure_macro("Portail des énigmes")
    micro = micros.create_micro(titre="Scraper les énigmes, interface Tinder",
                                macro_id=macro["id"], origine="assistant")
    ticket = tickets.create_ticket(SLUG, micro["titre"], micro["titre"])
    tickets.poser(SLUG, ticket, parent=PARENT)
    tickets.set_launching(SLUG, ticket)
    tickets.add_run(SLUG, ticket, AGENT, "work", "m")
    micros.lier_ticket(micro["id"], slug=SLUG, ticket_id=ticket["id"])
    micros.marquer_etat(micro["id"], "lancee")

    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        _fiche(AGENT, proc, depot, ticket["id"])
        #  Témoin : vivant, il est bien vu au travail (sinon le test ne prouverait rien).
        assert store.agent_status(agent_fiche.load_agent(AGENT))["state"] == "running"
        assert isolation.agents_sharing_cwd(depot) == [AGENT]
        store.invalidate_status(AGENT)
        os.kill(proc.pid, signal.SIGTERM)
        if request.param == "ramasse":
            proc.wait(timeout=10)
        else:
            _attendre_zombie(proc.pid)
        agent_fiche._list_agents_cache.clear()
        agent_registre._agent_file_cache.clear()
        ipc = json.loads((agent_fiche.AGENTS_DIR / f"{AGENT}.ipc" / "state.json").read_text())
        assert ipc["status"] == "running", "le process tué n'a rien pu réécrire"
        constater_tout()  # le watchdog est passé : la mort est CONSTATÉE (lot L2)
        yield {"depot": depot, "micro": micros.get_micro(micro["id"]), "ticket": ticket}
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)


def test_le_statut_reconcilie_dit_l_agent_arrete(agent_tue):
    agent = agent_fiche.load_agent(AGENT)
    statut = store.agent_status(agent)
    assert statut["state"] != "running"
    agent = agent_fiche.load_agent(AGENT)
    assert agent.returncode is not None and agent.fin_constatee
    assert not agent_vivacite.is_running(agent) and not agent_chaud.is_mid_turn(agent)


def test_le_garde_fou_de_depot_ne_compte_pas_l_agent_tue(agent_tue):
    """« Un autre agent modifie déjà ce dépôt » : faux, il est mort."""
    assert isolation.agents_sharing_cwd(agent_tue["depot"]) == []
    mode, raison, commentaire = isolation.resolve_isolation(agent_tue["depot"], "shared")
    assert (mode, commentaire) == ("shared", ""), raison


def test_la_tache_n_est_plus_occupee(agent_tue):
    assert taches_actions.agent_actif(agent_tue["micro"]) is None


def test_la_vue_d_ensemble_et_la_liste_de_l_assistant(agent_tue):
    vue = bilan_chantier.vue_ensemble("Portail des énigmes")
    assert vue["ok"], vue
    ligne_agent = next(l for l in vue["texte"].splitlines() if f"agent {AGENT[:8]}" in l)
    assert "En cours" not in ligne_agent and "running" not in ligne_agent, ligne_agent
    assert "fin constatée" in ligne_agent, ligne_agent
    [tache] = [t for t in bureau_tools.taches(action="lister")["taches"]
               if t["id"] == agent_tue["micro"]["id"]]
    assert tache["statut"] != "en_cours", tache


def test_le_parent_ne_voit_plus_un_enfant_actif(agent_tue):
    [fiche] = enfants.enfants_de(PARENT)
    assert fiche["actif"] is False, fiche


def test_un_message_n_est_pas_depose_dans_la_boite_d_un_mort(agent_tue):
    assert file_messages._deposer_si_en_tour(AGENT, {"id": "m1", "text": "précision"}) is False


def test_la_flotte_de_l_assistant_et_l_arbre(agent_tue):
    from bouzecode.web_v2.services.work import fleet
    rendu = bureau_tools.flotte()
    assert [t["id"] for t in rendu["en_cours"]] == [], rendu["en_cours"]
    noeuds = {n.get("agent_id"): n for n in fleet.agent_tree().get("nodes") or []}
    assert noeuds[AGENT]["state"] != "running", noeuds[AGENT]
    assert noeuds[AGENT].get("vivacite_propre") != "running", noeuds[AGENT]


def test_un_enfant_re_instruit_puis_tue_n_est_plus_en_cours(agent_tue):
    """Relancé (« continuer ») puis tué avant d'avoir reclos (cas réel du ticket de6724a5) :
    il ne répondra jamais. Sa mort constatée en fait un enfant ARRÊTÉ — le compter en cours
    bloquait à vie la clôture et l'intégration de son parent."""
    [fiche] = enfants.enfants_de(PARENT)
    assert fiche["actif"] is False and fiche["etat"] == enfants.ARRETE, fiche


def test_un_enfant_re_instruit_vivant_reste_en_cours(tmp_path):
    """Témoin : livré puis ré-instruit (reprise chaude), process vivant mais pas encore reparti
    (oisif) : il doit une réponse, son ticket est `running`."""
    from bouzecode.web_v2.services.work import constats, runs_ticket
    ticket = tickets.create_ticket(SLUG, "enfant", "enfant")
    tickets.poser(SLUG, ticket, parent=PARENT)
    tickets.set_launching(SLUG, ticket)
    tickets.add_run(SLUG, ticket, AGENT, "work", "m")
    constats.fin_de_run(SLUG, ticket["id"], AGENT, "final_answer")
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        _fiche(AGENT, proc, _depot(tmp_path), ticket["id"])
        ipc = agent_fiche.AGENTS_DIR / f"{AGENT}.ipc" / "state.json"
        ipc.write_text(json.dumps({"status": "idle", "updated_at": time.time()}), encoding="utf-8")
        store.invalidate_status(AGENT)
        runs_ticket.signaler(SLUG, ticket["id"], AGENT, "message")
        [fiche] = enfants.enfants_de(PARENT)
        assert fiche["etat"] == enfants.EN_COURS, fiche
    finally:
        proc.kill()
        proc.wait(timeout=10)
