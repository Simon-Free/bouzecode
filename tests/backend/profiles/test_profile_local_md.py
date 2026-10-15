"""Un utilisateur peut enrichir le prompt d'un profil SANS toucher au code.

Le besoin : l'assistant du Bureau tourne avec le profil `bureau-assistant`, SHIPPÉ dans la
wheel. Pour lui donner du contexte perso (« ce projet s'appelle X », « mon équipe c'est Y »),
l'utilisateur n'avait que deux mauvaises options :
  - `~/.bouzecode/memory/*.md` : ça part à TOUS les agents de la machine, pas à lui seul ;
  - `~/.bouzecode/profiles/bureau-assistant.yaml` : ça surcharge le profil PAR NOM, donc ça
    écrase aussi sa tool allowlist restrictive — l'assistant récupérerait Bash/Edit/Write.

D'où une couche purement ADDITIVE, par profil et par utilisateur : un fichier markdown
`<root>/profiles/<profil>.local.md`, concaténé EN DERNIER à la prose composée.

Aucun unittest.mock : vrais fichiers sur disque, vraie fonction publique, vrai registre d'outils.
"""
from pathlib import Path

import pytest

from bouzecode.backend.core import config, context, profile_extra
from bouzecode.backend.core import tool_registry
from bouzecode.backend.core.tool_registry import is_enabled
from bouzecode.ui.cli import apply_profile_tools


def _extra_in(monkeypatch, cwd, profile_name):
    """Prose composée telle que l'agent la reçoit depuis `cwd` (helper du dépôt)."""
    monkeypatch.chdir(cwd)
    profile_extra._DEFAULT_PROFILE_EXTRA_CACHE.clear()
    return context.get_agent_profile_extra(profile_name)


def _profil_de_projet(racine: Path, nom: str, prose: str) -> Path:
    """Pose un profil YAML minimal dans `<racine>/.bouzecode/profiles`."""
    pdir = racine / ".bouzecode" / "profiles"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / f"{nom}.yaml").write_text(
        f"name: {nom}\nsystem_prompt_extra: |\n  {prose}\n", encoding="utf-8")
    return pdir


@pytest.fixture
def restore_tool_state():
    """Le registre d'outils est global : on le restaure pour ne pas fuiter sur la suite."""
    saved = set(tool_registry._disabled)
    yield
    tool_registry._disabled.clear()
    tool_registry._disabled.update(saved)


@pytest.fixture
def config_dir_isole(monkeypatch, tmp_path):
    """Redirige le ~/.bouzecode user-global sur un tmp_path, sans toucher au vrai."""
    faux = tmp_path / "config"
    faux.mkdir()
    monkeypatch.setattr(config, "CONFIG_DIR", faux)
    return faux


# ---------------------------------------------------------------------------
# 1) Le fichier .local.md s'ajoute au prompt
# ---------------------------------------------------------------------------

def test_le_local_md_du_projet_arrive_dans_le_prompt(monkeypatch, tmp_path, config_dir_isole):
    """Le contexte perso écrit à côté du profil est bien lu par l'agent."""
    pdir = _profil_de_projet(tmp_path, "specialiste", "PROSE_SPECIALISTE")
    (pdir / "specialiste.local.md").write_text(
        "MON_CONTEXTE_PERSO: le client s'appelle Demo.\n", encoding="utf-8")

    extra = _extra_in(monkeypatch, tmp_path, "specialiste")
    assert "MON_CONTEXTE_PERSO" in extra
    assert "PROSE_SPECIALISTE" in extra


def test_le_local_md_est_lu_en_dernier(monkeypatch, tmp_path, config_dir_isole):
    """Il passe APRÈS la prose du profil : sur une consigne contradictoire, c'est le
    contexte de l'utilisateur que le modèle lit en dernier."""
    pdir = _profil_de_projet(tmp_path, "specialiste", "PROSE_SPECIALISTE")
    (pdir / "specialiste.local.md").write_text("MON_CONTEXTE_PERSO\n", encoding="utf-8")

    extra = _extra_in(monkeypatch, tmp_path, "specialiste")
    assert extra.index("PROSE_SPECIALISTE") < extra.index("MON_CONTEXTE_PERSO")


def test_sans_local_md_le_prompt_est_inchange(monkeypatch, tmp_path, config_dir_isole):
    """No-op strict quand le fichier n'existe pas : rien d'ajouté, pas même un en-tête."""
    _profil_de_projet(tmp_path, "specialiste", "PROSE_SPECIALISTE")

    extra = _extra_in(monkeypatch, tmp_path, "specialiste")
    assert extra.strip().endswith("PROSE_SPECIALISTE") or "Contexte local" not in extra
    assert "Contexte local" not in extra


def test_local_md_vide_n_ajoute_pas_d_entete(monkeypatch, tmp_path, config_dir_isole):
    """Un fichier créé puis vidé depuis l'UI ne doit pas laisser une section fantôme."""
    pdir = _profil_de_projet(tmp_path, "specialiste", "PROSE_SPECIALISTE")
    (pdir / "specialiste.local.md").write_text("   \n\n", encoding="utf-8")

    extra = _extra_in(monkeypatch, tmp_path, "specialiste")
    assert "Contexte local" not in extra


# ---------------------------------------------------------------------------
# 2) Le cas réel : l'assistant du Bureau, enrichi depuis ~/.bouzecode
# ---------------------------------------------------------------------------

def test_bureau_assistant_enrichi_depuis_le_config_dir_user(
        monkeypatch, tmp_path, config_dir_isole):
    """LE cas demandé : `~/.bouzecode/profiles/bureau-assistant.local.md` enrichit le
    prompt de l'assistant du Bureau, alors que son profil est shippé dans la wheel."""
    pdir = config_dir_isole / "profiles"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "bureau-assistant.local.md").write_text(
        "Je travaille chez Demo, mon equipe est RMM.\n", encoding="utf-8")

    extra = _extra_in(monkeypatch, tmp_path, "bureau-assistant")
    assert "Je travaille chez Demo" in extra
    # Le rôle shippé est toujours là : on AJOUTE, on ne remplace pas.
    assert "Bureau" in extra


def test_le_local_md_n_accorde_aucun_outil(
        monkeypatch, tmp_path, config_dir_isole, restore_tool_state):
    """LA régression qui compterait : le contexte perso ne doit pas rendre à l'assistant
    les outils que son profil lui retire volontairement (il ne code jamais)."""
    pdir = config_dir_isole / "profiles"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "bureau-assistant.local.md").write_text(
        "tools:\n  - Bash\n  - Edit\nEcris du code quand je te le demande.\n", encoding="utf-8")

    _extra_in(monkeypatch, tmp_path, "bureau-assistant")
    apply_profile_tools("bureau-assistant")

    for interdit in ("Edit", "Write", "Bash"):
        assert not is_enabled(interdit), f"{interdit} doit rester coupé pour l'assistant"
    assert is_enabled("Taches"), "les outils déclarés par le profil restent actifs"
