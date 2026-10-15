# [desc] Entrer dans un worktree puis en sortir en cours de session ne change plus un octet du system envoyé : le contexte de session reste celui du premier appel, chaque changement est empilé une fois dans la note (<working_notes>, jamais en <harness_notes>), une reprise renvoie le même bloc, et /clear le refige. [/desc]
"""Contexte de session figé (session c4fe6829 du 2026-10-07).

Le bloc « # Contexte de session » est dans le system, AVANT la note et l'historique. Recalculé
à chaque appel, il passait de 288 à 846 caractères à `Environment(action='worktree')` puis
revenait à 288 au nettoyage : deux fois tout ce qui le suit sortait du cache (2 809 puis 3 544
tokens réécrits). On rejoue la séquence avec les vrais gestes de l'outil — `adopt_cwd` pour
l'entrée, `aller` + `poser_racine("")` pour la sortie — et on lit ce que `dispatch` envoie.
"""
from __future__ import annotations

import json
import subprocess

import pytest

from bouzecode.backend.agent.providers.backends import dispatch
from bouzecode.backend.agent.state import AgentState
# La sérialisation de session elle-même (save_progressive écrirait aussi sous ~/.bouzecode).
from bouzecode.backend.commands.session.session import _build_session_data
from bouzecode.backend.commands.core.basic import cmd_clear
from bouzecode.backend.commands.session.session_pick import restore_state
from bouzecode.backend.core.dossier_agent import aller, poser_racine
from bouzecode.backend.tools.environment import adopt_cwd

DEMANDE = {"role": "user", "content": "Corrige l'import pptx.", "_demande_utilisateur": True}


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def depot_et_worktree(tmp_path, monkeypatch):
    """Un dépôt sur `develop` et un worktree d'agent sur `agent/solo-3` ; l'agent part du dépôt."""
    depot, worktree = tmp_path / "demo_application", tmp_path / "worktrees" / "solo-3"
    depot.mkdir()
    _git(depot, "init", "-b", "develop")
    _git(depot, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "--allow-empty", "-m", "x")
    _git(depot, "worktree", "add", "-b", "agent/solo-3", str(worktree))
    monkeypatch.chdir(depot)
    monkeypatch.setenv("BOUZECODE_WORKTREE_ROOT", "")  # restaurée en fin de test
    monkeypatch.delenv("BOUZECODE_WORKTREE_ROOT")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    return depot, worktree


def _envoi(state: AgentState, messages: list):
    """Ce que dispatch envoie pour ce tour d'agent (system, fil) — rien ne part sur le réseau :
    le SystemPayload est produit avant toute requête."""
    config = {"model": "claude-opus-5", "_context_state": state.context_state}
    flux = dispatch.stream(config["model"], "Noyau stable.", messages,
                           [{"name": "Bash", "description": "d", "input_schema": {}}], config)
    payload = next(flux)
    flux.close()
    # Le system tel que sérialisé sur le fil : deux envois égaux sont identiques à l'octet.
    return json.dumps(payload.system_blocks, ensure_ascii=False, sort_keys=True), payload.messages


def _apres(outil: str, resultat: str) -> list:
    return [DEMANDE,
            {"role": "assistant", "content": ".", "tool_calls": [
                {"id": "t1", "name": outil, "input": {"action": outil}}]},
            {"role": "tool", "tool_call_id": "t1", "name": outil, "content": resultat}]


def _harness_notes(messages: list) -> str:
    return "\n".join(m["content"] for m in messages if m.get("_notes_du_harnais"))


def _notes(messages: list) -> str:
    """La note envoyée (<working_notes> en tête du premier message), où les notes de contexte
    sont empilées ; vérifie au passage qu'aucune ne repart en <harness_notes>."""
    assert "[harnais]" not in _harness_notes(messages)
    contenu = messages[0]["content"]
    texte = contenu if isinstance(contenu, str) else "".join(b.get("text", "") for b in contenu)
    return texte[:texte.index("</working_notes>")] if "</working_notes>" in texte else ""


def _bloc(note: str, debut: str) -> str:
    """Le bloc « ## Harnais » de la note qui commence par `debut`."""
    bloc = note[note.index(debut):]
    return bloc.split("\n\n## ")[0].strip()


def test_worktree_puis_sortie_le_system_ne_bouge_pas_et_chaque_changement_est_note_une_fois(
        depot_et_worktree):
    """L'agent entre dans son worktree puis en ressort : le system envoyé reste identique à
    l'octet ; la note d'entrée (avec le contrat de worktree) puis celle de sortie s'ajoutent."""
    depot, worktree = depot_et_worktree
    state = AgentState()

    system_depart, _ = _envoi(state, [DEMANDE])
    assert f"Répertoire : {depot} — branche develop" in "".join(
        bloc["text"] for bloc in json.loads(system_depart))

    adopt_cwd(str(worktree), {}, worktree=True)  # Environment(action='worktree')
    system_worktree, fil_worktree = _envoi(state, _apres("Environment", "Worktree adopté."))
    aller(str(depot))  # Environment(action='cleanup') : retour au dépôt, contrat retiré
    poser_racine("")
    system_sortie, fil_sortie = _envoi(state, _apres("Bash", "ok"))
    _, fil_suivant = _envoi(state, _apres("Bash", "ok"))

    assert system_worktree == system_depart and system_sortie == system_depart
    # Chaque note est un bloc « ## Harnais @… » empilé à la fin de la note.
    entree = _bloc(_notes(fil_worktree), "[harnais] Tu travailles désormais")
    assert entree.startswith(
        f"[harnais] Tu travailles désormais dans le worktree {worktree}, branche agent/solo-3.")
    assert f"Tu travailles dans un worktree isolé : {worktree}." in entree
    assert "Ta branche de travail est `agent/solo-3`." in entree
    sortie = (f"[harnais] Tu n'es plus dans le worktree {worktree} : retour à {depot}, "
              "branche develop.")
    assert entree in _notes(fil_sortie) and sortie in _notes(fil_sortie)
    assert _notes(fil_sortie).count("[harnais]") == 2, "une note par changement, pas une par tour"
    assert _notes(fil_suivant).count("[harnais]") == 2
    assert _notes(fil_suivant).index(entree) < _notes(fil_suivant).index(sortie)


def test_une_reprise_renvoie_le_bloc_fige_et_garde_les_notes(depot_et_worktree):
    """Session sauvegardée dans son worktree puis reprise : le system envoyé est celui du
    premier appel de la session, et la note d'entrée dans le worktree est toujours là."""
    depot, worktree = depot_et_worktree
    state = AgentState()
    system_depart, _ = _envoi(state, [DEMANDE])
    adopt_cwd(str(worktree), {}, worktree=True)
    _envoi(state, _apres("Environment", "Worktree adopté."))

    reprise = AgentState()
    restore_state(reprise, json.loads(json.dumps(_build_session_data(state), ensure_ascii=False)))
    system_reprise, fil_reprise = _envoi(reprise, _apres("Bash", "ok"))

    assert system_reprise == system_depart
    assert _notes(fil_reprise).count("[harnais] Tu travailles désormais dans le worktree") == 1


def test_sans_resultat_d_outil_la_note_est_empilee_dans_la_note(depot_et_worktree):
    """Nouveau message de l'utilisateur après un changement de répertoire (fil sans résultat
    d'outil) : la note est empilée dans <working_notes>, ni dans le system ni après la demande."""
    _, worktree = depot_et_worktree
    state = AgentState()
    system_depart, _ = _envoi(state, [DEMANDE])
    adopt_cwd(str(worktree), {})  # LoadProjectConfig(cd=true) : déplacé, pas isolé

    system_apres, fil = _envoi(state, [DEMANDE])

    assert system_apres == system_depart
    dernier = fil[-1]["content"]
    texte = dernier if isinstance(dernier, str) else "".join(b.get("text", "") for b in dernier)
    assert texte.rstrip().endswith("Corrige l'import pptx.")
    assert "<harness_notes>" not in texte
    note = _bloc(_notes(fil), "[harnais]")
    assert note.startswith(f"[harnais] Ton répertoire de travail est désormais {worktree}, "
                           "branche agent/solo-3.")
    assert "worktree isolé" not in note, "LoadProjectConfig(cd=true) déplace sans isoler"


def test_apres_clear_le_contexte_se_refige_et_les_anciennes_notes_ne_partent_plus(
        depot_et_worktree):
    """`/clear` ouvre une nouvelle conversation : son system décrit la situation du moment
    (ici le worktree), et aucune note « [harnais] » de la conversation close n'est renvoyée."""
    _, worktree = depot_et_worktree
    state = AgentState()
    system_depart, _ = _envoi(state, [DEMANDE])
    adopt_cwd(str(worktree), {}, worktree=True)
    _, fil_avant = _envoi(state, _apres("Environment", "Worktree adopté."))
    assert "[harnais]" in _notes(fil_avant)

    cmd_clear("", state, {"model": "test"})
    system_neuf, fil_neuf = _envoi(state, _apres("Bash", "ok"))

    texte_neuf = "".join(bloc["text"] for bloc in json.loads(system_neuf))
    assert system_neuf != system_depart
    assert f"Tu travailles dans un worktree isolé : {worktree}." in texte_neuf
    assert "[harnais]" not in json.dumps(fil_neuf, ensure_ascii=False)
    assert state.context_state.notes_de_contexte == []
