"""`--profile X` AUGMENTE le calque partagé, il ne le REMPLACE plus.

Avant : un agent lancé `--profile coder` ne recevait QUE coder.yaml, donc il perdait
en silence l'échelle de découverte de code et les consignes de batching (`depends_on`)
qui ne vivent que dans `.bouzecode/profiles/default.yaml`.
Maintenant la prose se compose : `default` → profil nommé → fragments builtin.
Les ALLOWLISTS D'OUTILS, elles, ne se composent JAMAIS : un profil restrictif
(`manager`, read-only) ne peut pas se voir re-accorder Edit/Write/Bash.

Aucun unittest.mock : vrais fichiers YAML, vraie fonction publique, vrai registre d'outils.
"""
from pathlib import Path

import pytest

from bouzecode.backend.core import context, profile_extra
from bouzecode.backend.core import tool_registry
from bouzecode.backend.core.tool_registry import is_enabled
from bouzecode.backend.profiles import resolve_agent_profile
from bouzecode.ui.cli import apply_profile_tools

REPO_ROOT = Path(__file__).resolve().parents[3]

# Marqueurs stables du calque `default` du dépôt (.bouzecode/profiles/default.yaml).
DISCOVERY_LADDER = "Découverte de code"
BATCHING_RULE = "depends_on"


def _extra_in(monkeypatch, cwd, profile_name):
    """Prose composée telle que l'agent de profondeur 0 la reçoit depuis `cwd`."""
    monkeypatch.chdir(cwd)
    profile_extra._DEFAULT_PROFILE_EXTRA_CACHE.clear()
    return context.get_agent_profile_extra(profile_name)


@pytest.fixture
def restore_tool_state():
    """Le registre d'outils est global : on restaure l'ensemble des outils désactivés
    pour qu'un test de whitelist ne fuite pas sur le reste de la suite."""
    saved = set(tool_registry._disabled)
    yield
    tool_registry._disabled.clear()
    tool_registry._disabled.update(saved)


# ---------------------------------------------------------------------------
# 1) La prose se compose
# ---------------------------------------------------------------------------

def test_profile_coder_garde_l_echelle_de_decouverte_du_calque_default(monkeypatch):
    """Un agent `--profile coder` reçoit SA prose ET celle du calque `default`."""
    extra = _extra_in(monkeypatch, REPO_ROOT, "coder")
    assert "AGENT CODEUR PYTHON" in extra          # calque coder préservé
    assert DISCOVERY_LADDER in extra               # échelle de découverte retrouvée
    assert BATCHING_RULE in extra                  # consigne de batching retrouvée


def test_le_calque_default_passe_avant_le_profil_nomme(monkeypatch):
    """Ordre = général puis spécialisé : sur une consigne contradictoire, c'est le
    profil nommé que le modèle lit en dernier."""
    extra = _extra_in(monkeypatch, REPO_ROOT, "coder")
    assert extra.index(DISCOVERY_LADDER) < extra.index("AGENT CODEUR PYTHON")


def test_le_calque_default_n_est_pas_injecte_deux_fois(monkeypatch):
    """`--profile default` (ou aucun profil) ne duplique pas le calque partagé."""
    extra = _extra_in(monkeypatch, REPO_ROOT, "default")
    assert extra.count(DISCOVERY_LADDER) == 1


def test_profil_de_projet_compose_avec_le_default_du_projet(monkeypatch, tmp_path):
    """La règle vaut pour n'importe quel projet, pas seulement le dépôt bouzecode."""
    pdir = tmp_path / ".bouzecode" / "profiles"
    pdir.mkdir(parents=True)
    (pdir / "default.yaml").write_text(
        "name: default\nsystem_prompt_extra: |\n  CALQUE_PARTAGE\n", encoding="utf-8")
    (pdir / "specialiste.yaml").write_text(
        "name: specialiste\nsystem_prompt_extra: |\n  PROSE_SPECIALISTE\n", encoding="utf-8")

    extra = _extra_in(monkeypatch, tmp_path, "specialiste")
    assert "CALQUE_PARTAGE" in extra and "PROSE_SPECIALISTE" in extra


def test_profil_peut_refuser_le_calque_partage(monkeypatch, tmp_path):
    """`inherit_default: false` = opt-out explicite, pour un rôle qui le contredit."""
    pdir = tmp_path / ".bouzecode" / "profiles"
    pdir.mkdir(parents=True)
    (pdir / "default.yaml").write_text(
        "name: default\nsystem_prompt_extra: |\n  CALQUE_PARTAGE\n", encoding="utf-8")
    (pdir / "routeur.yaml").write_text(
        "name: routeur\ninherit_default: false\n"
        "system_prompt_extra: |\n  PROSE_ROUTEUR\n", encoding="utf-8")

    extra = _extra_in(monkeypatch, tmp_path, "routeur")
    assert "PROSE_ROUTEUR" in extra
    assert "CALQUE_PARTAGE" not in extra


def test_manager_reste_sans_consignes_de_code(monkeypatch):
    """Le manager n'a ni Edit ni Write ni Bash : lui injecter le calque code (TDD,
    échelle de découverte) le pousserait à coder — c'est justement sa dérive interdite."""
    extra = _extra_in(monkeypatch, REPO_ROOT, "manager")
    assert "Manager" in extra
    assert DISCOVERY_LADDER not in extra


# ---------------------------------------------------------------------------
# 2) Les allowlists d'outils, elles, ne se composent JAMAIS
# ---------------------------------------------------------------------------

def test_manager_n_obtient_pas_edit_write_bash_apres_composition(
        monkeypatch, restore_tool_state):
    """LA régression qui compterait : composer la prose ne doit pas re-accorder les
    outils qu'un profil restrictif retire volontairement."""
    _extra_in(monkeypatch, REPO_ROOT, "manager")  # la composition a bien eu lieu
    apply_profile_tools("manager")

    for interdit in ("Edit", "Write", "Bash"):
        assert not is_enabled(interdit), f"{interdit} doit rester coupé pour le manager"
    for declare in ("Read", "Agent", "ListAgentTypes"):
        assert is_enabled(declare), f"{declare} est déclaré par le manager"


def test_l_allowlist_du_manager_ne_gagne_rien_du_profil_default():
    """Le profil résolu par nom reste CELUI du YAML : aucune union avec `default`."""
    manager = resolve_agent_profile("manager")
    assert "Edit" not in manager.tools
    assert "Write" not in manager.tools
    assert "Bash" not in manager.tools
    assert manager.inherit_default is False


def test_frontend_garde_son_allowlist_vide():
    """`frontend` laisse `tools` vide EXPRÈS (les outils MCP ne sont pas nommables) :
    la composition ne doit pas lui fabriquer une allowlist."""
    frontend = resolve_agent_profile("frontend")
    assert frontend.tools == []
    assert frontend.inherit_default is True
