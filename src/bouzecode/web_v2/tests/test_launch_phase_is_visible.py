"""Pendant qu'un ticket se lance, l'utilisateur doit voir CE QUI se passe : création du
worktree (~50 s par essai sur ce poste, jusqu'à 3 essais), installation de l'environnement uv
(jusqu'à 600 s), démarrage de l'agent.

Le défaut : le champ `phase` était LU par l'arbre des agents et écrit par PERSONNE — toutes
ces étapes se présentaient sous un unique « provisioning » muet.

Aucun mock : de vrais tickets dans le store SQLite, et les vraies fonctions de dispatch. Seuls
les gestes coûteux et hors sujet ici (git, uv, Popen d'un agent) sont remplacés par des seams
qui enregistrent la phase visible à l'instant où ils tournent.
"""
import pytest

from bouzecode.web_v2.services.work import dispatch, launch_phase, provisioning, tickets

SLUG = "projet-test"


@pytest.fixture()
def ticket():
    """Un ticket neuf dans le store isolé par la fixture autouse de conftest."""
    return tickets.create_ticket(SLUG, "Déployer", "Déployer la branche develop")


def _phase_of(ticket_id):
    """La phase telle qu'elle est SERVIE (donc telle que l'UI et l'API la lisent)."""
    return launch_phase.phase_view(tickets.get_ticket(SLUG, ticket_id))


def test_la_creation_du_worktree_est_annoncee_avec_sa_branche_de_base(ticket, monkeypatch,
                                                                     tmp_path):
    """Pendant `git worktree add`, le ticket dit « création du worktree » et depuis quelle
    branche il part."""
    vue_pendant_git = {}

    def _provision_qui_observe(root, ticket_id, **kwargs):
        vue_pendant_git.update(_phase_of(ticket_id))
        return {"ok": True, "state": "provisioned", "repo_root": root,
                "worktree": str(tmp_path), "branch": "agent/x", "base": "develop"}

    monkeypatch.setattr(dispatch.repos, "repo_root", lambda path: str(tmp_path))
    monkeypatch.setattr(provisioning.worktrees, "current_branch", lambda root: "develop")
    monkeypatch.setattr(provisioning.worktrees, "provision", _provision_qui_observe)

    dispatch._provision_worktree(SLUG, ticket, str(tmp_path))

    assert vue_pendant_git["phase"] == launch_phase.PROVISIONING_WORKTREE
    assert vue_pendant_git["phase_label"] == "création du worktree"
    assert vue_pendant_git["phase_detail"] == "depuis develop"
    assert vue_pendant_git["phase_at"]  # horodatée : « depuis 4 s » vs « depuis 4 min »


def test_un_essai_de_worktree_rate_est_dit_pendant_que_le_suivant_tourne(ticket, monkeypatch,
                                                                        tmp_path):
    """Un `git worktree add` qui dépasse son délai est rejoué : le ticket annonce l'essai
    raté au lieu de rester muet pendant deux minutes et demie."""
    def _provision_qui_echoue_une_fois(root, ticket_id, **kwargs):
        kwargs["on_attempt"](1, 3, "n'a pas rendu la main en 120 s")
        return {"ok": True, "state": "provisioned", "repo_root": root,
                "worktree": str(tmp_path), "branch": "agent/x", "base": "develop"}

    monkeypatch.setattr(dispatch.repos, "repo_root", lambda path: str(tmp_path))
    monkeypatch.setattr(provisioning.worktrees, "current_branch", lambda root: "develop")
    monkeypatch.setattr(provisioning.worktrees, "provision", _provision_qui_echoue_une_fois)

    dispatch._provision_worktree(SLUG, ticket, str(tmp_path))

    detail = _phase_of(ticket["id"])["phase_detail"]
    assert "essai 1/3 échoué" in detail
    assert "nouvelle tentative" in detail


def test_l_installation_de_l_environnement_uv_est_annoncee(ticket, monkeypatch, tmp_path):
    """`uv sync --all-extras` tourne en fond jusqu'à 600 s : la phase le dit."""
    monkeypatch.setattr(dispatch.repos, "repo_root", lambda path: str(tmp_path))
    monkeypatch.setattr(provisioning.worktrees, "current_branch", lambda root: "develop")
    monkeypatch.setattr(provisioning.worktrees, "provision",
                        lambda root, tid, **kw: {"ok": True, "state": "provisioned",
                                                 "repo_root": root, "worktree": str(tmp_path),
                                                 "branch": "agent/x", "base": "develop"})
    monkeypatch.setattr(provisioning.worktrees, "setup_venv_async",
                        lambda wt, root="", on_result=None: None)  # jamais de vrai uv en test

    dispatch._provision_worktree(SLUG, ticket, str(tmp_path), isolation="worktree+venv")

    assert _phase_of(ticket["id"])["phase"] == launch_phase.SYNCING_VENV
    assert _phase_of(ticket["id"])["phase_label"] == "installation de l'environnement uv"


def test_un_environnement_uv_en_echec_est_dit_sur_le_ticket(ticket):
    """L'échec d'un `uv sync` de fond était PERDU (« best-effort, sans suivi de résultat »),
    alors qu'il laisse l'agent sans ses dépendances. Il devient un commentaire du ticket."""
    dispatch._report_venv_issue(SLUG, ticket, provisioning.worktrees.VENV_FAILED)

    commentaires = tickets.get_ticket(SLUG, ticket["id"])["comments"]
    assert any("uv sync" in c["text"] for c in commentaires)


def test_un_projet_sans_python_ne_declenche_aucune_alerte(ticket):
    """Pas de pyproject.toml n'est pas un échec : rien à signaler, aucun commentaire."""
    dispatch._report_venv_issue(SLUG, ticket, provisioning.worktrees.VENV_SKIPPED)

    assert tickets.get_ticket(SLUG, ticket["id"])["comments"] == []


def test_le_demarrage_de_l_agent_efface_la_phase_de_preparation(ticket):
    """Dès qu'un run existe, la phase disparaît : afficher « démarrage de l'agent » sur un
    agent démarré serait un mensonge."""
    launch_phase.set_phase(SLUG, ticket, launch_phase.SPAWNING)
    assert _phase_of(ticket["id"])["phase"] == launch_phase.SPAWNING

    tickets.add_run(SLUG, ticket, "abc123", "work", "claude-sonnet")

    assert _phase_of(ticket["id"]) == {}


def test_un_lancement_echoue_efface_la_phase_de_preparation(ticket):
    """Même règle quand rien ne viendra : on n'affiche pas une préparation en cours sur un
    ticket dont le lancement a échoué."""
    launch_phase.set_phase(SLUG, ticket, launch_phase.PROVISIONING_WORKTREE)

    dispatch.record_launch_failure(SLUG, ticket, "git indisponible")

    frais = tickets.get_ticket(SLUG, ticket["id"])
    assert launch_phase.phase_view(frais) == {}
    assert frais[dispatch.LAUNCH_FAILED_KEY]["error"] == "git indisponible"
