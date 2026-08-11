# [desc] Conformity: no text injected into an agent's prompt may name a tool that agent cannot call. [/desc]
"""Le harnais ne doit jamais prescrire ce qu'il refuse.

Un outil nommé dans le prompt d'un agent — noyau, exemples de tour, prose de profil,
bloc plan mode, schémas des outils, ou message de garde renvoyé par un outil — doit
être appelable par cet agent. Sinon le modèle obéit à la consigne et se fait refuser :
ce n'est pas une désobéissance du modèle, c'est une contradiction interne du harnais
(mesuré : `RunPythonTest` nommé dans 277/944 system prompts pour un outil désactivé).
"""
import functools
import json

import pytest

import bouzecode.backend.tools  # noqa: F401 — peuple le registre + la whitelist
from bouzecode.backend.core import context
from bouzecode.backend.core._embedded_data import (
    PLAN_MODE_TEMPLATE, SYSTEM_PROMPT_TEMPLATE, TOOL_EXAMPLES_XML,
)
from bouzecode.backend.core.profile_extra import get_agent_profile_extra
from bouzecode.backend.core.tool_mentions import tool_names_cited
from bouzecode.backend.core.tool_registry import get_tool
from bouzecode.backend.tools.registration import enabled_tools_for_profile

SHIPPED_PROFILES = [
    "default", "coder", "general-purpose", "manager", "meta-agent", "frontend",
]

# Exemptions EXPLICITES et DATÉES (2026-07-27). Une exemption dit « ce texte nomme un
# outil absent MAIS ne le prescrit pas » — ou porte une dette identifiée, jamais un
# oubli silencieux.
EXEMPTIONS = {
    # « Tu n'as PAS d'outil d'édition (ni `Edit`, ni `Write`, ni `Bash` d'écriture) :
    #   c'est VOULU. » — mention PROSCRIPTIVE : elle enlève, elle ne prescrit pas.
    ("manager", "prose de profil"): {"Edit", "Write", "Bash"},
    # Dette connue : le gabarit de tour partagé illustre un batch Edit→Bash et cite
    # `Write(temp=True)`. Le manager est read-only et reçoit quand même l'exemple.
    # Corriger demande des exemples PAR profil (surface partagée par tous les agents) —
    # décision hors périmètre de ce ticket, tracée ici plutôt que silencieuse.
    ("manager", "noyau + exemples de tour"): {"Edit", "Write", "Bash"},
}


def prompt_surfaces(profile_name: str, available: set) -> dict:
    """Tous les textes que l'agent `profile_name` reçoit dans son prompt."""
    surfaces = {
        "noyau + exemples de tour": SYSTEM_PROMPT_TEMPLATE.replace(
            "{tool_examples}", TOOL_EXAMPLES_XML),
        # Ni « AGENTS.md » ni « README.md » : la section ne cite aucun fichier de
        # cartographie, elle oriente vers les outils AgentsMap() / SymbolMap().
        "navigation du code (AgentsMap/SymbolMap)": context.get_readme_navigation_section(),
        "prose de profil": get_agent_profile_extra(profile_name),
        "bloc plan mode": PLAN_MODE_TEMPLATE,
    }
    for name in sorted(available):
        surfaces[f"schéma de {name}"] = json.dumps(get_tool(name).schema, ensure_ascii=False)
    return surfaces


def violations(surfaces: dict, available: set, profile_name: str = "") -> dict:
    """{nom de surface: outils nommés que cet agent ne peut pas appeler}."""
    known = _all_tool_names()
    found = {}
    for surface_name, text in surfaces.items():
        exempt = EXEMPTIONS.get((profile_name, surface_name), set())
        missing = sorted(tool_names_cited(text, known) - available - exempt)
        if missing:
            found[surface_name] = missing
    return found


def _all_tool_names() -> set:
    from bouzecode.backend.core.tool_registry import get_all_tools
    return {t.name for t in get_all_tools()}


@pytest.mark.parametrize("profile_name", SHIPPED_PROFILES)
def test_no_prompt_surface_names_a_tool_the_agent_cannot_call(profile_name):
    """Chaque profil livré : rien dans son prompt ne nomme un outil hors de son registre."""
    available = enabled_tools_for_profile(profile_name)
    found = violations(prompt_surfaces(profile_name, available), available, profile_name)
    assert not found, (
        f"Le prompt de `{profile_name}` prescrit des outils qu'il n'a pas : {found}. "
        "Soit l'outil doit être activé pour ce profil, soit la mention doit disparaître."
    )


def test_the_check_catches_a_reintroduced_violation():
    """Preuve que le test mord : on réinjecte la prescription supprimée (l'échelle de
    découverte qui pointait sur GetFolderDescription) et elle doit être détectée."""
    available = enabled_tools_for_profile("coder")
    assert "GetFolderDescription" not in available
    regression = {"prose de profil": "2. **GetFolderDescription** — structure + outlines."}

    assert violations(regression, available, "coder") == {
        "prose de profil": ["GetFolderDescription"]
    }


def test_a_profile_shipping_a_phantom_prescription_fails_the_check(tmp_path):
    """Preuve de bout en bout : un profil livré AVEC une prescription fantôme (ici la
    même que celle qu'on vient de retirer) est détecté par le chemin réel — chargement
    du profil, composition de la prose, extraction des noms d'outils."""
    from bouzecode.backend.core.paths import add_extra_dir

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "phantom-probe.yaml").write_text(
        "name: phantom-probe\ntools: []\nskills: []\nhooks: []\nmodel: ''\n"
        "system_prompt_extra: |\n"
        "  Pour explorer un dossier, utilise **GetFolderDescription** avant tout Read.\n",
        encoding="utf-8",
    )
    add_extra_dir(profiles_dir.parent)

    available = enabled_tools_for_profile("phantom-probe")
    found = violations(prompt_surfaces("phantom-probe", available), available, "phantom-probe")

    assert found.get("prose de profil") == ["GetFolderDescription"]


def test_a_single_word_tool_name_only_counts_when_marked_up_as_a_tool():
    """« Agent de développement » n'est pas un appel d'outil ; `Agent(...)` en est un."""
    known = _all_tool_names()
    assert tool_names_cited("Profil — Agent de développement", known) == set()
    assert "Agent" in tool_names_cited("dispatche via `Agent`", known)
    assert "Agent" in tool_names_cited("appelle Agent(prompt=...)", known)


@functools.lru_cache(maxsize=1)
def _guard_messages() -> tuple:
    """Les messages de garde RÉELS (exécutés, pas recopiés) que renvoient les outils.

    Exécutés une seule fois pour toute la classe de tests : le timeout Bash coûte une
    seconde de mur."""
    import sys

    from bouzecode.backend.tools.ops.read_params import normalize_read_params
    from bouzecode.backend.tools.ops.shell_search import _bash

    recursive_error, _ = normalize_read_params({"file_path": "x.py", "recursive": True})
    long_command = "ping -n 20 127.0.0.1" if sys.platform == "win32" else "sleep 20"
    return (
        ("garde Read(recursive=)", recursive_error),
        ("garde timeout Bash", _bash(long_command, timeout=1)),
        ("garde sortie vide Bash", _bash("cd .")),
    )


@pytest.mark.parametrize("profile_name", SHIPPED_PROFILES)
def test_guard_messages_only_name_tools_the_agent_can_call(profile_name):
    """Un refus/avertissement d'outil ne doit jamais aiguiller vers un outil absent :
    c'est exactement le tour perdu qu'on veut supprimer."""
    available = enabled_tools_for_profile(profile_name)
    if "Bash" not in available:
        pytest.skip(f"{profile_name} n'a pas Bash — ces gardes ne lui parviennent jamais")
    assert not violations(dict(_guard_messages()), available, profile_name)


# Ce que chaque profil pouvait appeler AVANT ce ticket. La conformité se répare en
# activant l'outil OU en retirant la mention — jamais en RETIRANT un outil déjà offert.
BASELINE_2026_07_27 = {
    "default": {"Read", "Write", "Edit", "Bash", "Glob", "Grep", "BashOutput",
                "AddProject", "WebFetch", "WebSearch"},
    "coder": {"Read", "Write", "Edit", "Bash", "Glob", "Grep", "RunPythonTest"},
    "manager": {"Read", "Glob", "Grep", "Agent", "MessageAgent", "ListAgentTypes", "Fleet"},
    "meta-agent": {"Read", "Write", "Edit", "Bash", "Glob", "Grep", "Agent", "ListAgentTypes"},
}


@pytest.mark.parametrize("profile_name", sorted(BASELINE_2026_07_27))
def test_no_profile_lost_a_tool_it_already_had(profile_name):
    """Aucun outil déjà disponible n'a été retiré au passage — la régression serait pire
    que le bug."""
    from bouzecode.backend.core.tool_registry import FRAMEWORK_ALWAYS_ON

    expected = BASELINE_2026_07_27[profile_name] | set(FRAMEWORK_ALWAYS_ON)
    lost = expected - enabled_tools_for_profile(profile_name)
    assert not lost, f"`{profile_name}` a PERDU : {sorted(lost)}"
