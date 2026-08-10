# [desc] Tests for explicit agent profile resolution (--profile flag path): custom names resolve from .bouzecode/profiles, fallbacks map to default. [/desc]
import textwrap

from bouzecode.backend.core.context import get_agent_profile_extra


def _write_profile(root, name, extra):
    pdir = root / ".bouzecode" / "profiles"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / f"{name}.yaml").write_text(
        textwrap.dedent(f"""\
        name: {name}
        system_prompt_extra: |
          {extra}
        """),
        encoding="utf-8",
    )


def test_custom_profile_name_resolves(tmp_path, monkeypatch):
    _write_profile(tmp_path, "parity_reviewer", "Tu es le reviewer.")
    monkeypatch.chdir(tmp_path)
    assert "Tu es le reviewer." in get_agent_profile_extra("parity_reviewer")


def test_unknown_profile_yields_only_builtin_capabilities(tmp_path, monkeypatch):
    """Profil inconnu -> aucune couche typologie, mais les capabilities always-on
    (deferred) restent composees. Pas de texte de profil typologie."""
    monkeypatch.chdir(tmp_path)
    extra = get_agent_profile_extra("does_not_exist")
    assert "deferred=True" in extra      # capability packagee toujours presente
    assert "Tu es le reviewer." not in extra  # aucune fuite de profil typologie


def test_autre_and_empty_map_to_default(tmp_path, monkeypatch):
    _write_profile(tmp_path, "default", "Couche code-agent.")
    monkeypatch.chdir(tmp_path)
    assert "Couche code-agent." in get_agent_profile_extra("autre")
    assert "Couche code-agent." in get_agent_profile_extra("")
