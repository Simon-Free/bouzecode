# [desc] Entrée puis sortie de worktree sur des appels réels (faux serveur Anthropic) : chaque note « [harnais] » est empilée une fois dans la partie cachée (<working_notes>), le préfixe jusqu'à elle est identique d'un appel à l'autre, et elle ne repart jamais en <harness_notes>. [/desc]
"""Notes de contexte empilées en cache (2026-10-08).

Avant : chaque note de changement de contexte (contexte_fige.py, memoire_figee.py) repartait
à CHAQUE appel dans <harness_notes>, après le dernier point de cache — 145 appels sur 219 en
fresh tokens, la même note 28 fois dans la session f8894fc5. Désormais elle est empilée une fois
à la fin de la note Methodology (append-only) : écrite en cache à l'appel qui la voit naître,
relue en cache ensuite. On le vérifie sur les corps de requête que le vrai pipeline
(dispatch → client Anthropic) envoie à un faux serveur local.
"""
from __future__ import annotations

import json
import subprocess

import pytest

from bouzecode.backend.agent.providers.backends import dispatch
from bouzecode.backend.agent.state import AgentState
from bouzecode.backend.context_manager.methodology import append_user_msg_to_methodology
from bouzecode.backend.context_manager.state import (ContextState, restaurer_le_contexte,
                                               state_du_contexte)
from bouzecode.backend.core.dossier_agent import aller, poser_racine
from bouzecode.backend.tools.environment import adopt_cwd
from tests import cache_conversation_helpers
from tests.mock_anthropic_server import start_mock_anthropic

DEMANDE = {"role": "user", "content": "Corrige l'import pptx.", "_demande_utilisateur": True}
OUTILS = [{"name": "Bash", "description": "d", "input_schema": {}}]


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def serveur_et_worktree(tmp_path, monkeypatch):
    """Un dépôt sur `develop`, un worktree `agent/solo-3`, et un faux serveur Anthropic local."""
    depot, worktree = tmp_path / "demo_application", tmp_path / "worktrees" / "solo-3"
    depot.mkdir()
    _git(depot, "init", "-b", "develop")
    _git(depot, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "--allow-empty", "-m", "x")
    _git(depot, "worktree", "add", "-b", "agent/solo-3", str(worktree))
    monkeypatch.chdir(depot)
    monkeypatch.setenv("BOUZECODE_WORKTREE_ROOT", "")  # restaurée en fin de test
    monkeypatch.delenv("BOUZECODE_WORKTREE_ROOT")
    url, serveur = start_mock_anthropic(["ok"] * 4)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", url)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(cache_conversation_helpers, "LIVE_API_ALLOWED", True)  # localhost
    return depot, worktree, serveur


def _appel(state: AgentState, serveur) -> dict:
    """Un appel complet (le flux est consommé : la note envoyée devient le préfixe caché du
    suivant, comme dans la boucle) ; renvoie le corps de requête reçu par le serveur."""
    config = {"model": "claude-opus-5", "_context_state": state.context_state}
    list(dispatch.stream(config["model"], "Noyau stable.", [
        DEMANDE, {"role": "assistant", "content": ".", "tool_calls": [
            {"id": "t1", "name": "Bash", "input": {"command": "x"}}]},
        {"role": "tool", "tool_call_id": "t1", "name": "Bash", "content": "ok"}], OUTILS, config))
    return serveur.recorded_calls[-1]


def _segments(requete: dict) -> list[tuple[str, bool]]:
    """Le flux dans l'ordre de lecture du modèle : (texte, porte un point de cache)."""
    segments = [(json.dumps(o, sort_keys=True), bool(o.get("cache_control")))
                for o in requete.get("tools") or []]
    segments += [(b["text"], bool(b.get("cache_control"))) for b in requete["system"]]
    for message in requete["messages"]:
        contenu = message["content"]
        blocs = contenu if isinstance(contenu, list) else [{"type": "text", "text": contenu}]
        segments += [(b["text"] if b.get("type") == "text" else json.dumps(b, sort_keys=True),
                      bool(b.get("cache_control"))) for b in blocs]
    return segments


def _cache(requete: dict) -> tuple[str, str]:
    """(flux entier, partie cachée = jusqu'au dernier point de cache)."""
    flux, fin = "", 0
    for texte, en_cache in _segments(requete):
        flux += texte
        fin = len(flux) if en_cache else fin
    return flux, flux[:fin]


def _hors_note(requete: dict) -> str:
    """Tout ce qui suit le premier message (le fil, dont <harness_notes>)."""
    return json.dumps(requete["messages"][1:], ensure_ascii=False)


def test_entree_puis_sortie_de_worktree_empilees_une_fois_en_cache(serveur_et_worktree):
    depot, worktree, serveur = serveur_et_worktree
    state = AgentState()
    append_user_msg_to_methodology(state.context_state, DEMANDE["content"])

    depart = _appel(state, serveur)
    adopt_cwd(str(worktree), {}, worktree=True)  # Environment(action='worktree')
    entree = _appel(state, serveur)
    aller(str(depot))  # Environment(action='cleanup') : retour au dépôt
    poser_racine("")
    sortie = _appel(state, serveur)
    suivant = _appel(state, serveur)

    note_entree = f"[harnais] Tu travailles désormais dans le worktree {worktree}"
    note_sortie = f"[harnais] Tu n'es plus dans le worktree {worktree}"
    requetes = [depart, entree, sortie, suivant]
    caches = [_cache(r)[1] for r in requetes]
    # (1) chaque note est dans la partie cachée dès l'appel qui la voit naître, et y reste.
    assert note_entree not in _cache(depart)[0]
    assert all(note_entree in cache for cache in caches[1:])
    assert all(note_sortie in cache for cache in caches[2:])
    # (2) le préfixe caché d'un appel est repris à l'octet par le suivant (append-only) : la
    # note née à l'appel N est relue en cache à l'appel N+1, seule la nouvelle est écrite.
    for precedent, courant in zip(requetes, requetes[1:]):
        assert _cache(courant)[0].startswith(_cache(precedent)[1])
    assert caches[2].index(note_entree) < len(caches[1])
    # (3) jamais renvoyée en <harness_notes> (ni ailleurs dans le fil), une seule copie.
    for requete in requetes:
        assert "[harnais]" not in _hors_note(requete)
        assert _cache(requete)[0].count("[harnais]") == _cache(requete)[1].count("[harnais]")
        assert sum(en_cache for _, en_cache in _segments(requete)) <= 4
    # (4) entrée puis sortie : deux blocs empilés dans l'ordre, une fois chacun.
    assert caches[3].count(note_entree) == 1 and caches[3].count(note_sortie) == 1
    assert caches[3].index(note_entree) < caches[3].index(note_sortie)
    assert caches[3].count("## Harnais @") == 2


def test_reprise_d_une_session_d_avant_l_empilement():
    """Session sauvegardée quand les notes partaient en <harness_notes> : à la reprise elles
    sont empilées une fois dans la note ; une session déjà au nouveau format ne double rien."""
    ancienne = {"notes": {"methodology": "## User @x\nCorrige."},
                "notes_de_contexte": ["[harnais] Entrée.", "[harnais] Sortie."]}
    reprise = restaurer_le_contexte(ContextState(), ancienne)
    note = reprise.notes["methodology"]
    assert note.startswith("## User @x\nCorrige.\n\n## Harnais @")
    assert note.index("[harnais] Entrée.") < note.index("[harnais] Sortie.")
    assert reprise.notes_de_contexte == ancienne["notes_de_contexte"]

    nouvelle = restaurer_le_contexte(ContextState(), state_du_contexte(reprise))
    assert nouvelle.notes["methodology"] == note
