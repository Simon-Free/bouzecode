# [desc] Audit du prompt appliqué (2026-09-24) : tampon de tour et alerte de redite de Methodology, outils Graph réservés au Bureau, contexte de session après le préfixe stable. [/desc]
"""Comportements introduits par l'application de l'audit du system prompt.

On vérifie ce que le harnais FAIT (note produite, outils exposés, blocs envoyés au
fournisseur), pas le libellé des consignes.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

import bouzecode.backend.tools  # noqa: F401 — peuple le registre + la whitelist
from bouzecode.backend.agent.dag import _build_dag_levels
from bouzecode.backend.agent.providers.backends.dispatch import stream
from bouzecode.backend.context_manager.methodology import (
    methodology_tool,
    reconstruct_methodology_from_timeline,
)
from bouzecode.backend.context_manager.state import METHODOLOGY_NOTE, ContextState
from bouzecode.backend.core import profile_extra
from bouzecode.backend.core.context import build_stable_system_prompt
from bouzecode.backend.core.profile_extra import filter_platform_blocks, get_agent_profile_extra
from bouzecode.backend.core.tool_registry import get_tool, get_tool_schemas
from bouzecode.backend.profiles import load_system_profiles
from bouzecode.backend.tools import registration
from bouzecode.backend.tools.registration import enabled_tools_for_profile
from bouzecode.backend.tools.schemas import TOOL_SCHEMAS

OUTILS_GRAPH = ("Mails", "Teams", "Canaux", "Brouillon", "Creneau", "Reunion")
MODELE_NATIF = "deepseek-v4-flash"


# ---------------------------------------------------------------------------
# Methodology : tampon « ### T<n> » posé par le harnais
# ---------------------------------------------------------------------------

def _config_methodology(tour: int) -> dict:
    return {"_context_state": ContextState(),
            "_state": SimpleNamespace(turn_count=tour, notes_timeline=[])}


def _note(cfg: dict) -> str:
    return cfg["_context_state"].notes[METHODOLOGY_NOTE]


def test_chaque_ajout_methodology_porte_le_numero_de_tour_reel():
    cfg = _config_methodology(7)
    methodology_tool({"content": "## Mission\nDécision : garder le cache par répertoire"}, cfg)
    cfg["_state"].turn_count = 8
    #  Un numéro écrit par le modèle ne fait pas foi : seul celui du harnais reste.
    methodology_tool({"content": "### T99\n[x] garder le cache"}, cfg)

    note = _note(cfg)
    assert note.startswith("### T7\n")
    assert "### T8\n" in note
    assert "T99" not in note


def test_le_tampon_garde_la_timeline_en_pur_ajout():
    """Le tampon ouvre un bloc : chaque tour reste un ajout (pas une recopie de la note)
    et la note se reconstruit à l'identique depuis la timeline."""
    cfg = _config_methodology(1)
    for tour, contenu in ((1, "## But\nlivrer"), (2, "sans titre : fait mesuré"), (2, "## Suite\nici")):
        cfg["_state"].turn_count = tour
        methodology_tool({"content": contenu}, cfg)

    timeline = cfg["_state"].notes_timeline
    assert all(not entree["delta"]["removed"] for entree in timeline)
    assert reconstruct_methodology_from_timeline(timeline) == _note(cfg)


# ---------------------------------------------------------------------------
# Methodology : alerte de redite (jamais un refus)
# ---------------------------------------------------------------------------

def test_une_redite_est_signalee_mais_l_ajout_est_garde():
    cfg = _config_methodology(1)
    methodology_tool({"content": (
        "## Mission : corriger load_config\n"
        "- [ ] lire config.py et trouver la cause\n"
        "- [ ] écrire le test de non-régression")}, cfg)
    cfg["_state"].turn_count = 2

    resultat = methodology_tool({"content": (
        "## Mission : corriger load_config\n"
        "- [ ] lire config.py et trouver la cause\n"
        "Cause : value=None ligne 42 de config.py")}, cfg)

    assert "67 % de ton ajout est déjà dans la note : n'écris que le nouveau" in resultat
    assert "Cause : value=None ligne 42 de config.py" in _note(cfg)


def test_un_ajout_neuf_ou_une_case_cochee_ne_sont_pas_signales():
    cfg = _config_methodology(3)
    methodology_tool({"content": "- [ ] lire config.py et trouver la cause"}, cfg)
    cocher = methodology_tool({"content": "[x] lire config.py et trouver la cause"}, cfg)
    neuf = methodology_tool({"content": "Prochaine étape : intégrer la branche après les tests"}, cfg)
    assert "déjà dans la note" not in cocher
    assert "déjà dans la note" not in neuf


# ---------------------------------------------------------------------------
# Outils Microsoft Graph : réservés à l'assistant du Bureau
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nom", OUTILS_GRAPH)
def test_outil_graph_absent_du_profil_de_code_present_pour_le_bureau(nom):
    assert nom not in enabled_tools_for_profile("default")
    assert nom not in registration._DEFAULT_ENABLED
    assert nom in enabled_tools_for_profile("bureau-assistant")


# ---------------------------------------------------------------------------
# Contexte de session : APRÈS le préfixe stable
# ---------------------------------------------------------------------------

def _blocs_systeme(monkeypatch, system: str, tool_schemas=TOOL_SCHEMAS) -> list[str]:
    monkeypatch.setenv("OPENROUTER_KEY", "sk-or-fake")
    gen = stream(model=MODELE_NATIF, system=system,
                 messages=[{"role": "user", "content": "bonjour"}],
                 tool_schemas=tool_schemas, config={})
    try:
        return [bloc["text"] for bloc in next(gen).system_blocks]
    finally:
        gen.close()


@pytest.mark.parametrize("chemin", ["prompt fourni (repl, runner web)", "prompt construit"])
def test_le_contexte_de_session_suit_le_prefixe_stable(monkeypatch, chemin):
    system = build_stable_system_prompt({"model": MODELE_NATIF}) if chemin.startswith("prompt fourni") else ""
    blocs = _blocs_systeme(monkeypatch, system)

    prefixe = blocs[0]
    assert "# Profil — Agent de développement" in prefixe      # le profil est DANS le préfixe
    assert "# Contexte de session" not in prefixe
    assert str(Path.cwd()) not in prefixe
    position = [i for i, texte in enumerate(blocs) if "# Contexte de session" in texte]
    # En dernier. La règle finale qui le suivait n'est plus envoyée sur OpenRouter (A/B du
    # 24/09, docs/reduction_tokens/correctifs.md §3) : seul le rappel frais, en fin de payload.
    assert position == [len(blocs) - 1]
    assert str(Path.cwd()) in blocs[position[0]]
    assert not any(b.startswith("RAPPEL : chaque lot") for b in blocs)


def test_deux_agents_de_dossiers_differents_partagent_le_meme_prefixe(monkeypatch, tmp_path):
    prefixes = []
    for dossier in ("agent_a", "agent_b"):
        (tmp_path / dossier).mkdir()
        monkeypatch.chdir(tmp_path / dossier)
        profile_extra._DEFAULT_PROFILE_EXTRA_CACHE.clear()
        prefixes.append(_blocs_systeme(monkeypatch, "")[0])
    assert prefixes[0] == prefixes[1]


def test_un_appel_annexe_ne_recoit_pas_de_contexte_de_session(monkeypatch):
    blocs = _blocs_systeme(monkeypatch, "You are a concise summarizer.", tool_schemas=[])
    assert not any("# Contexte de session" in texte for texte in blocs)


def test_le_contexte_de_session_est_court():
    """Ni `git status` ni les derniers commits : ils changent sans cesse (`git log` suffit)."""
    from bouzecode.backend.core.context import build_session_context
    contexte = build_session_context({})
    assert "Recent commits" not in contexte and "Git status" not in contexte
    assert "Plateforme :" in contexte


# ---------------------------------------------------------------------------
# Règles d'ordonnancement : décrites une fois, acceptées partout
# ---------------------------------------------------------------------------

def test_depends_on_et_alias_restent_acceptes_sur_tous_les_outils():
    for schema in get_tool_schemas():
        props = schema.get("input_schema", {}).get("properties")
        if props is None:
            continue
        assert props["depends_on"] == {"type": "array", "items": {"type": "string"}}, schema["name"]
        assert props["tool_call_alias"] == {"type": "string"}, schema["name"]

    appels = [
        {"id": "a", "name": "Write", "input": {"file_path": "x.py", "content": "y", "tool_call_alias": "w1"}},
        {"id": "b", "name": "Bash", "input": {"command": "python x.py", "depends_on": ["w1"]}},
    ]
    _, deps = _build_dag_levels(appels)
    assert deps["b"] == {"a"}


# ---------------------------------------------------------------------------
# Contradictions et consignes propres à une plateforme
# ---------------------------------------------------------------------------

def test_la_prose_ne_prescrit_que_des_isolations_que_l_outil_accepte():
    """`isolation` est revenu dans `Agent` le 2026-10-05 (choix du parent sur le besoin réel) :
    toute prose qui le prescrit doit nommer une valeur de son enum."""
    import re
    valeurs = get_tool("Agent").schema["input_schema"]["properties"]["isolation"]["enum"]
    assert valeurs == ["shared", "worktree", "worktree_venv"]
    profile_extra._DEFAULT_PROFILE_EXTRA_CACHE.clear()
    for profil in ("default", "coder", "frontend", "manager", "meta-agent", "general-purpose"):
        for valeur in re.findall(r"isolation=['\"]?([\w+]+)", get_agent_profile_extra(profil)):
            assert valeur in valeurs, (profil, valeur)
    assert all(v in get_agent_profile_extra("manager") for v in valeurs)


def test_les_consignes_windows_ne_partent_que_sous_windows():
    brut = load_system_profiles()["default"].system_prompt_extra
    assert "install-chromium-proxy.ps1" in brut
    assert "install-chromium-proxy.ps1" not in filter_platform_blocks(brut, "Linux")
    sous_windows = filter_platform_blocks(brut, "Windows")
    assert "install-chromium-proxy.ps1" in sous_windows
    assert "<!-- si:" not in sous_windows and "<!-- /si -->" not in sous_windows
