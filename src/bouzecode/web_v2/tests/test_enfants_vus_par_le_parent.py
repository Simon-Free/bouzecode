# [desc] Un parent voit ses enfants lancés via le serveur tels qu'ils sont, ne détruit pas leur atelier et ne clôt pas par-dessus eux. [/desc]
"""Essai 3 du 2026-09-24 (racine 6bafe9cd, enfant « ui-tinder » 62a7742e / ticket fee42a91).

1. Tour 17 : ListAgentTasks répond « No sub-agent tasks » (27 ms, lu dans l'arbre en cache)
   alors que l'enfant tourne ; la racine le croit disparu et réécrit la vue Tinder.
2. Tours 40 et 42 : la racine tente `git worktree remove` + `git branch -D` sur le worktree de
   l'enfant actif ; il n'a survécu que parce qu'il n'était pas propre.
3. Tour 44 : la racine clôt (FinalAnswer accepté) pendant que l'enfant tourne ; l'enfant
   s'intègre ensuite par-dessus.

La boucle, les outils et le serveur (client Flask) tournent pour de vrai ; seul le modèle est
simulé. L'état des agents et des tickets est écrit sur disque comme le runner l'écrit.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

from bouzecode.web_v2.runtime.runner import agent_fiche
from bouzecode.web_v2.services.work import tickets
from bouzecode.web_v2.tests.test_v3_statut_des_taches import (  # noqa: F401
    SLUG, client, ecrire_agent,
)
from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

RACINE = "5a5a5a5a5a5a"
ENFANT = "6b6b6b6b6b6b"


def _outil(nom: str, i: str, **params) -> str:
    corps = "".join(f'<param name="{k}">{v}</param>' for k, v in params.items())
    return f'<tool_use name="{nom}" id="{i}">{corps}</tool_use>'


def _final(i: str) -> str:
    return _outil("FinalAnswer", i, answer="Vue Tinder livrée.",
                  taches_terminees='["vue Tinder"]', taches_restantes="[]")


def _config(client, **extra) -> dict:
    """Je suis l'agent RACINE du serveur ; mes lectures du serveur passent par le client Flask."""
    def get(url):
        return client.get("/" + url.split("127.0.0.1", 1)[-1].split("/", 1)[-1]).get_json()
    return {"_web_agent_dir": str(agent_fiche.AGENTS_DIR / f"{RACINE}.ipc"), "_web_get": get, **extra}


def _resultats(result, nom: str) -> list[str]:
    return [str(m.get("content", "")) for m in result.messages
            if m.get("role") == "tool" and m.get("name") == nom]


def _enfant(worktree: str = "", branche: str = "", vivant: bool = True) -> str:
    """La racine a délégué un lot (ticket parent=RACINE, run de l'agent ENFANT)."""
    ticket = tickets.create_ticket(SLUG, "ui-tinder", "Vue Tinder des énigmes")
    ticket["parent"] = RACINE
    if worktree:
        ticket["worktree"] = {"ok": True, "state": "ready", "worktree": worktree,
                              "branch": branche, "base": "main"}
    tickets.update_ticket(SLUG, ticket)
    tickets.set_launching(SLUG, ticket)
    tickets.add_run(SLUG, ticket, ENFANT, "work", "m")
    _etat_enfant(ticket["id"], vivant)
    return ticket["id"]


def _etat_enfant(ticket_id: str, vivant: bool) -> None:
    """Vivant : l'agent tourne. Sinon il a rendu sa réponse finale, et le hook de fin a
    terminé son run (ticket livré)."""
    if vivant:
        ecrire_agent(ENFANT, vivant=True, ipc="running", ticket_id=ticket_id)
    else:
        from bouzecode.web_v2.services.work import constats
        ecrire_agent(ENFANT, ticket_id=ticket_id, final={"answer": "vue Tinder faite"})
        constats.fin_de_run(SLUG, ticket_id, ENFANT, "final_answer")


@pytest.fixture()
def racine():
    ecrire_agent(RACINE, vivant=True, ipc="running")


# ── 1. Voir ses enfants ──────────────────────────────────────────────────────

def test_un_enfant_lance_apres_le_dernier_calcul_de_l_arbre_est_liste_en_cours(client, racine):
    """L'arbre a été calculé avant la délégation : ListAgentTasks montre quand même l'enfant."""
    client.get("/api/agents/tree")  # l'interface a lu l'arbre : il est en cache, sans enfant
    ticket_id = _enfant()

    mock = MockLLM([_outil("ListAgentTasks", "l1"), "Mon enfant tourne encore, je l'attends."])
    result = bouzecode(["Où en est ton sous-agent ?"], mock_llm=mock,
                       config_overrides=_config(client))

    sortie = _resultats(result, "ListAgentTasks")[0]
    assert ticket_id in sortie and ENFANT in sortie
    assert "en cours" in sortie
    assert "No sub-agent tasks" not in sortie


def test_un_enfant_encore_en_provisionnement_est_liste_en_lancement(client, racine):
    """Dispatch différé : le ticket existe, l'agent pas encore. L'enfant n'a pas « disparu »."""
    client.get("/api/agents/tree")
    ticket = tickets.create_ticket(SLUG, "ui-tinder", "Vue Tinder")
    ticket["parent"] = RACINE
    tickets.update_ticket(SLUG, ticket)
    tickets.set_launching(SLUG, ticket)

    mock = MockLLM([_outil("ListAgentTasks", "l1"), "Il démarre."])
    result = bouzecode(["Et ton sous-agent ?"], mock_llm=mock, config_overrides=_config(client))

    sortie = _resultats(result, "ListAgentTasks")[0]
    assert ticket["id"] in sortie and "en lancement" in sortie


def test_un_second_list_agent_tasks_voit_l_enfant_qui_a_fini_entre_temps(client, racine):
    """Rien n'est écrit par la racine entre deux ListAgentTasks identiques, mais l'enfant, lui,
    a fini : le second appel le dit (pas de réponse mémorisée « déjà joué »)."""
    ticket_id = _enfant()

    mock = MockLLM([_outil("ListAgentTasks", "l1"), _outil("ListAgentTasks", "l2"), "Il a fini."])
    appels = []
    original = mock.stream

    def stream(*a, **k):
        appels.append(1)
        if len(appels) == 2:  # entre les deux lectures, l'enfant livre
            _etat_enfant(ticket_id, vivant=False)
        yield from original(*a, **k)
    mock.stream = stream
    result = bouzecode(["Surveille ton enfant."], mock_llm=mock, config_overrides=_config(client))

    premiere, seconde = _resultats(result, "ListAgentTasks")
    assert "en cours" in premiere
    assert "livré" in seconde and "DÉJÀ JOUÉ" not in seconde


def test_check_agent_result_donne_etat_branche_et_worktree_d_un_enfant_web(
        client, racine, tmp_path):
    """CheckAgentResult retrouve l'enfant par son ticket : fini, livré, sa branche, son worktree."""
    ticket_id = _enfant(str(tmp_path / "wt"), "agent/lot", vivant=False)

    mock = MockLLM([_outil("CheckAgentResult", "c1", task_id=ticket_id), "Il a livré."])
    result = bouzecode(["Ton enfant a-t-il fini ?"], mock_llm=mock,
                       config_overrides=_config(client))

    sortie = _resultats(result, "CheckAgentResult")[0]
    assert "livré" in sortie and "agent/lot" in sortie and str(tmp_path / "wt") in sortie
    assert "(supprimé)" in sortie  # le worktree n'existe pas sur disque : c'est dit


# ── 2. Ne pas détruire l'atelier d'un enfant vivant ──────────────────────────

def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _depot_avec_worktree_d_enfant(tmp_path) -> tuple[str, str]:
    """Un vrai dépôt, et le worktree PROPRE de l'enfant sur sa branche."""
    depot = tmp_path / "depot"
    depot.mkdir()
    _git("init", "-q", "-b", "main", cwd=depot)
    (depot / "index.html").write_text("<h1>Portail</h1>", encoding="utf-8")
    _git("add", ".", cwd=depot)
    _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init", cwd=depot)
    worktree = tmp_path / "worktrees" / "lot"
    _git("worktree", "add", "-q", "-b", "agent/lot", str(worktree), cwd=depot)
    return str(depot), str(worktree)


def _commande_de_menage(depot: str, worktree: str) -> str:
    """La commande de l'essai 3 (tour 42), chemin passé par variable. Sous Windows l'outil Bash
    exécute PowerShell : `WT=...` y est une commande inconnue et rien n'était supprimé."""
    affecte = f"$WT='{worktree}'" if sys.platform == "win32" else f"WT={worktree}"
    return (f'cd {depot}; {affecte}; git worktree remove "$WT"; git branch -D agent/lot; '
            'git worktree list')


def test_bash_refuse_de_supprimer_le_worktree_d_un_enfant_en_cours(client, racine, tmp_path):
    """`git worktree remove` + `git branch -D` sur l'atelier d'un enfant actif : refusé, intact."""
    depot, worktree = _depot_avec_worktree_d_enfant(tmp_path)
    ticket_id = _enfant(worktree, "agent/lot")

    mock = MockLLM([_outil("Bash", "b1", command=_commande_de_menage(depot, worktree)),
                    "Je le laisse."])
    result = bouzecode(["Range les worktrees résiduels."], mock_llm=mock,
                       config_overrides=_config(client))

    sortie = _resultats(result, "Bash")[0]
    assert sortie.startswith("Error: refusé")
    assert ticket_id in sortie and "Fleet(action='kill'" in sortie and "wait=true" in sortie
    assert (tmp_path / "worktrees" / "lot").is_dir()


def test_bash_supprime_le_worktree_d_un_enfant_qui_a_fini(client, racine, tmp_path):
    """Contrôle négatif : l'enfant a livré, la même commande passe et le worktree disparaît."""
    depot, worktree = _depot_avec_worktree_d_enfant(tmp_path)
    _enfant(worktree, "agent/lot", vivant=False)

    mock = MockLLM([_outil("Bash", "b1", command=_commande_de_menage(depot, worktree)),
                    "Rangé."])
    result = bouzecode(["Range les worktrees résiduels."], mock_llm=mock,
                       config_overrides=_config(client))

    assert not _resultats(result, "Bash")[0].startswith("Error")
    assert not (tmp_path / "worktrees" / "lot").exists()


def test_environment_refuse_de_ranger_tant_qu_un_enfant_travaille(client, racine):
    """Environment(cleanup) pendant qu'un enfant tourne : refus qui le nomme."""
    ticket_id = _enfant()

    mock = MockLLM([_outil("Environment", "e1", action="cleanup"), "J'attends."])
    result = bouzecode(["Range ton atelier."], mock_llm=mock, config_overrides=_config(client))

    sortie = _resultats(result, "Environment")[0]
    assert sortie.startswith("Error: refusé") and ticket_id in sortie


# ── 3. Ne pas clore par-dessus un enfant qui travaille ──────────────────────

def test_un_manager_clot_son_tour_pour_attendre_ses_enfants(client, racine):
    """Contrôle : pour un manager, clore EST attendre (le réveil le relancera) — accepté."""
    _enfant()

    mock = MockLLM([_final("f1"), "fin"])
    result = bouzecode(["Délègue et attends."], mock_llm=mock,
                       config_overrides=_config(client, _task_classification_result="manager"))

    assert result.state.final_answer == "Vue Tinder livrée."


def test_des_la_premiere_cloture_le_harnais_attend_l_enfant_et_rend_son_rapport(client, racine):
    """FinalAnswer avec un enfant qui tourne : le harnais l'attend lui-même dès le 1er essai et
    rend son compte rendu ; la clôture suivante passe (un seul tour de refus)."""
    ticket_id = _enfant()
    attentes = []

    def attendre(tid, slug):
        attentes.append(tid)
        _etat_enfant(ticket_id, vivant=False)  # pendant l'attente, l'enfant finit
        return "OK : vue Tinder commitée sur agent/lot"

    mock = MockLLM([_final("f1"), _final("f2"), "fin"])
    result = bouzecode(["Livre la vue Tinder."], mock_llm=mock,
                  config_overrides=_config(client, _web_wait_verdict=attendre))

    refus = _resultats(result, "FinalAnswer")
    assert len(refus) == 2 and attentes == [ticket_id]
    assert refus[0].startswith("CLÔTURE DIFFÉRÉE — 1 sous-agent(s)")
    assert ticket_id in refus[0] and "OK : vue Tinder commitée sur agent/lot" in refus[0]
    assert result.state.final_answer == "Vue Tinder livrée."


def test_un_enfant_qui_ne_finit_jamais_ne_bloque_pas_la_cloture_a_l_infini(client, racine):
    """Plafond : après six refus, la clôture passe, mais la réponse livrée nomme l'enfant actif."""
    ticket_id = _enfant()

    mock = MockLLM([_final(f"f{i}") for i in range(7)] + ["fin"])
    result = bouzecode(["Livre."], mock_llm=mock,
                       config_overrides=_config(client,
                                                _web_wait_verdict=lambda t, s: "toujours là"))

    assert len(_resultats(result, "FinalAnswer")) == 7
    assert result.state.final_answer.startswith("Vue Tinder livrée.")
    assert "Clôture forcée" in result.state.final_answer and ticket_id in result.state.final_answer
