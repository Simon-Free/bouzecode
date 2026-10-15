# [desc] Changer de projet (autre .bouzecode/memory) ou modifier un fichier mémoire en cours de session ne change plus un octet du system envoyé : la mémoire reste celle du premier appel, chaque changement est empilé une fois dans la note (<working_notes>), une reprise la renvoie, /clear la refige. [/desc]
"""Mémoire du projet figée (suite du contexte de session figé, 2026-10-07).

La section « # Memory » est dans la moitié stable du system, relue à chaque message : un `cd`
vers un projet qui a une autre mémoire, ou un fichier mémoire écrit pendant la session, faisait
sortir du cache tout ce qui la suit. On rejoue la séquence comme le REPL : le system stable est
construit avec l'état de la session, puis `dispatch` l'envoie.
"""
from __future__ import annotations

import json

import pytest

from bouzecode.backend.agent.providers.backends import dispatch
from bouzecode.backend.agent.state import AgentState
from bouzecode.backend.commands.core.basic import cmd_clear
# La sérialisation de session elle-même (save_progressive écrirait aussi sous ~/.bouzecode).
from bouzecode.backend.commands.session.session import _build_session_data
from bouzecode.backend.commands.session.session_pick import restore_state
from bouzecode.backend.core.context import build_stable_system_prompt
from bouzecode.backend.tools.environment import adopt_cwd

DEMANDE = {"role": "user", "content": "Corrige l'import pptx.", "_demande_utilisateur": True}
TETE = "[harnais] La mémoire du projet a changé."


def _memoire(projet, fichier, nom, description):
    dossier = projet / ".bouzecode" / "memory"
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / fichier).write_text(
        f"---\nname: {nom}\ndescription: {description}\n---\nCorps.\n", encoding="utf-8")


@pytest.fixture
def deux_projets(tmp_path, monkeypatch):
    """Projet A (deux souvenirs) et projet B (cinq autres) ; un HOME sans mémoire ; l'agent part de A."""
    for variable in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(variable, str(tmp_path / "home"))
    projet_a, projet_b = tmp_path / "projet_a", tmp_path / "projet_b"
    _memoire(projet_a, "proxy.md", "Proxy NTLM", "passer par le proxy")
    _memoire(projet_a, "tests.md", "Tests ciblés", "jamais -n auto")
    _memoire(projet_b, "deploy.md", "Déploiement", "src-only")
    for numero in range(1, 5):
        _memoire(projet_b, f"piege_{numero}.md", f"Piège {numero}", "payé une fois en production")
    monkeypatch.chdir(projet_a)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    return projet_a, projet_b


def _envoi(state: AgentState, messages: list):
    """Ce que le REPL puis dispatch envoient pour ce tour (system, fil) — rien ne part sur le
    réseau : le SystemPayload est produit avant toute requête."""
    config = {"model": "claude-opus-5"}
    system = build_stable_system_prompt({**config, "_context_state": state.context_state})
    flux = dispatch.stream(config["model"], system, messages,
                           [{"name": "Bash", "description": "d", "input_schema": {}}],
                           {**config, "_context_state": state.context_state})
    payload = next(flux)
    flux.close()
    return json.dumps(payload.system_blocks, ensure_ascii=False, sort_keys=True), payload.messages


def _apres_bash() -> list:
    return [DEMANDE,
            {"role": "assistant", "content": ".", "tool_calls": [
                {"id": "t1", "name": "Bash", "input": {"command": "x"}}]},
            {"role": "tool", "tool_call_id": "t1", "name": "Bash", "content": "ok"}]


def _notes(messages: list) -> str:
    """La note envoyée (<working_notes>), où les notes de contexte sont empilées ; aucune ne
    repart en <harness_notes>."""
    assert not any(TETE in m["content"] for m in messages if m.get("_notes_du_harnais"))
    contenu = messages[0]["content"]
    texte = contenu if isinstance(contenu, str) else "".join(b.get("text", "") for b in contenu)
    return texte[:texte.index("</working_notes>")] if "</working_notes>" in texte else ""


def _notes_memoire(state: AgentState) -> list[str]:
    return [n for n in state.context_state.notes_de_contexte if n.startswith(TETE)]


def test_cd_puis_memoire_modifiee_le_system_ne_bouge_pas_et_chaque_changement_est_note(
        deux_projets):
    """L'agent part du projet A, entre dans B, puis un souvenir de B est réécrit, un autre
    ajouté, un troisième supprimé : le system reste identique à l'octet (mémoire de A), deux
    notes « mémoire » arrivent — B en entier, puis seulement ce qui a changé."""
    projet_a, projet_b = deux_projets
    state = AgentState()

    system_depart, _ = _envoi(state, [DEMANDE])
    texte_depart = "".join(b["text"] for b in json.loads(system_depart))
    assert "- [Proxy NTLM](proxy.md) — passer par le proxy" in texte_depart

    adopt_cwd(str(projet_b), {})  # LoadProjectConfig(cd=true)
    system_b, fil_b = _envoi(state, _apres_bash())
    _memoire(projet_b, "deploy.md", "Déploiement", "src-only, jamais deploy_build/")
    _memoire(projet_b, "proxy.md", "Proxy", "par le .pth")
    (projet_b / ".bouzecode" / "memory" / "piege_4.md").unlink()
    system_modifie, fil_modifie = _envoi(state, _apres_bash())
    _, fil_suivant = _envoi(state, _apres_bash())

    assert system_b == system_depart and system_modifie == system_depart
    note_cd, note_modif = _notes_memoire(state)
    assert note_cd == (f"{TETE} Elle remplace la section « # Memory » du system prompt, qui est "
                       "celle du début de la session. Nouvelle mémoire :\n"
                       "- [Déploiement](deploy.md) — src-only\n"
                       + "\n".join(f"- [Piège {n}](piege_{n}.md) — payé une fois en production"
                                   for n in range(1, 5)))
    assert note_modif == (f"{TETE} Ces changements s'appliquent à la section « # Memory » du "
                          "system prompt, qui est celle du début de la session, et la remplacent "
                          "pour ces entrées :\nAjoutées ou modifiées :\n"
                          "- [Déploiement](deploy.md) — src-only, jamais deploy_build/\n"
                          "- [Proxy](proxy.md) — par le .pth\n"
                          "Retirées : piege_4.md")
    assert note_cd in _notes(fil_b)
    assert _notes(fil_suivant).count(TETE) == 2, "une note par changement, pas une par tour"


def test_fichier_reecrit_a_l_identique_ne_produit_pas_de_note(deux_projets):
    """Un souvenir réécrit sans changer de contenu (seule sa date bouge) : aucune note."""
    projet_a, _ = deux_projets
    state = AgentState()
    _envoi(state, [DEMANDE])
    _memoire(projet_a, "tests.md", "Tests ciblés", "jamais -n auto")
    _envoi(state, _apres_bash())
    assert _notes_memoire(state) == []


def test_memoire_courte_videe_la_note_le_dit(deux_projets):
    """Les souvenirs du projet A sont tous supprimés : la note annonce une mémoire vide."""
    projet_a, _ = deux_projets
    state = AgentState()
    _envoi(state, [DEMANDE])
    for fichier in ("proxy.md", "tests.md"):
        (projet_a / ".bouzecode" / "memory" / fichier).unlink()
    _envoi(state, _apres_bash())
    assert _notes_memoire(state) == [f"{TETE} Elle remplace la section « # Memory » du system "
                                     "prompt, qui est celle du début de la session. "
                                     "Nouvelle mémoire :\n(vide)"]


def test_une_reprise_renvoie_la_memoire_figee(deux_projets):
    """Session sauvegardée après l'entrée dans B puis reprise : le system garde la mémoire de A."""
    _, projet_b = deux_projets
    state = AgentState()
    system_depart, _ = _envoi(state, [DEMANDE])
    adopt_cwd(str(projet_b), {})
    _envoi(state, _apres_bash())

    reprise = AgentState()
    restore_state(reprise, json.loads(json.dumps(_build_session_data(state), ensure_ascii=False)))
    system_reprise, fil_reprise = _envoi(reprise, _apres_bash())

    assert system_reprise == system_depart
    assert _notes(fil_reprise).count(TETE) == 1


def test_apres_clear_la_memoire_se_refige(deux_projets):
    """`/clear` : le system de la nouvelle conversation porte la mémoire du moment (B), sans note."""
    _, projet_b = deux_projets
    state = AgentState()
    _envoi(state, [DEMANDE])
    adopt_cwd(str(projet_b), {})
    _envoi(state, _apres_bash())

    cmd_clear("", state, {"model": "test"})
    system_neuf, fil_neuf = _envoi(state, _apres_bash())

    texte_neuf = "".join(b["text"] for b in json.loads(system_neuf))
    assert "- [Déploiement](deploy.md) — src-only\n- [Piège 1]" in texte_neuf
    assert "Proxy NTLM" not in system_neuf
    assert TETE not in json.dumps(fil_neuf, ensure_ascii=False)


def test_sans_etat_de_session_la_memoire_est_celle_de_l_instant(deux_projets):
    """Aperçu, appel annexe, agent hôte : pas d'état de session, la mémoire est relue comme avant."""
    _, projet_b = deux_projets
    adopt_cwd(str(projet_b), {})
    assert "- [Déploiement](deploy.md) — src-only" in build_stable_system_prompt({"model": "x"})
