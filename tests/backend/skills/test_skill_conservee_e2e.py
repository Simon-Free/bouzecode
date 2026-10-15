# [desc] Conversation tests: une skill chargée reste dans la note de travail — ni jetée après lecture, ni rechargée. [/desc]
"""Session c4fe6829 (2026-10-07) : `Skill(azure-deployment)` chargée, résumée en deux lignes,
jetée (`Snippet(discard=true)`), puis rechargée en entier quand le déploiement a échoué.

Le harnais fige désormais la skill dans la note de travail dès son chargement : pas de
Snippet exigé, pas d'entrée « à jeter » dans l'inventaire, et un second `Skill` du même
nom renvoie vers la note au lieu de recharger le texte.
"""
from __future__ import annotations

import pytest

from bouzecode.backend.agent import enforcement_call
from bouzecode.backend.context_manager import METHODOLOGY_NOTE, build_verbatim_audit_note
from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
CLOSE = "Déployé."
ETAPE_UNIQUE = "Étape 7 : relancer deploy.py --push --src-only"


def _skill(ident: str) -> str:
    return f'<tool_use name="Skill" id="{ident}"><param name="name">azure-deployment</param></tool_use>'


@pytest.fixture()
def projet_avec_skill_longue(tmp_path, monkeypatch):
    """Un projet qui range une skill de déploiement de 80 lignes (au-delà du seuil de snippet)."""
    dossier = tmp_path / "demo_application" / ".bouzecode" / "skills" / "azure-deployment"
    dossier.mkdir(parents=True)
    lignes = [f"Consigne de déploiement n°{i}" for i in range(1, 80)] + [ETAPE_UNIQUE]
    (dossier / "skill.md").write_text(
        "---\nname: azure-deployment\ndescription: déployer sur Azure\n---\n\n"
        + "\n".join(lignes) + "\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path / "demo_application")


def _resultats_skill(result) -> list[str]:
    return [str(m.get("content", "")) for m in result.messages
            if m.get("role") == "tool" and m.get("name") == "Skill"]


def test_une_skill_chargee_reste_dans_la_note_sans_snippet_exige(projet_avec_skill_longue,
                                                                  monkeypatch):
    """Le modèle charge la skill puis travaille : aucun Snippet ne lui est réclamé."""
    reclamations = []
    original = enforcement_call.recover_snippets
    monkeypatch.setattr(enforcement_call, "recover_snippets",
                        lambda resultats, *a, **kw: reclamations.append(resultats)
                        or original(resultats, *a, **kw))
    bash = '<tool_use name="Bash" id="b1"><param name="command">echo deploy</param></tool_use>'
    mock = MockLLM([f"{METH}\n{_skill('sk1')}", f"{METH}\n{bash}", CLOSE])

    result = bouzecode(["déploie"], mock_llm=mock, config_overrides={"recover_memory": True})

    note = result.state.context_state.notes[METHODOLOGY_NOTE]
    assert note.count(ETAPE_UNIQUE) == 1, "la skill est figée UNE fois dans la note"
    assert "Conservée dans ta note de travail" in _resultats_skill(result)[0]
    assert all(r == [] for r in reclamations), "aucun Snippet réclamé pour la skill"
    assert not [m for m in result.messages if m.get("role") == "enforcement"]
    assert "sk1 (Skill" not in build_verbatim_audit_note(result.messages), (
        "la skill conservée n'est pas listée parmi les résultats « à jeter »")


def test_rappeler_une_skill_deja_conservee_ne_la_recharge_pas(projet_avec_skill_longue):
    """Le déploiement échoue, le modèle rappelle la skill : renvoi vers la note, pas de texte."""
    mock = MockLLM([f"{METH}\n{_skill('sk1')}", f"{METH}\n{_skill('sk2')}", CLOSE])

    result = bouzecode(["déploie"], mock_llm=mock)

    premier, second = _resultats_skill(result)
    assert ETAPE_UNIQUE in premier
    assert ETAPE_UNIQUE not in second, "le texte de la skill n'est pas renvoyé une 2e fois"
    assert "DÉJÀ dans ta note de travail" in second
    note = result.state.context_state.notes[METHODOLOGY_NOTE]
    assert note.count(ETAPE_UNIQUE) == 1, "jamais conservée deux fois"
