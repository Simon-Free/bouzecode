# [desc] Catalog-backed helpers for /agent: list installed/available profiles and install one (write YAML + plugins). [/desc]
"""Catalog-backed helpers for the `/agent` command (kept out of agent_switch.py
to honour the <200-lines-per-file charter)."""
from __future__ import annotations

from bouzecode.ui.ansi import info, ok, warn


def _catalog_split() -> tuple[dict, dict]:
    """(installed, available) from the shared catalog. Tolerant of network failures."""
    from bouzecode.backend.profiles import catalog, load_user_profiles
    try:
        return catalog.installed_and_available()
    except Exception as exc:  # noqa: BLE001 — network/git can fail; never crash the listing
        warn(f"Catalogue d'agents partagés indisponible : {exc}")
        return load_user_profiles(), {}


def _install(name: str, config: dict) -> None:
    """Install a catalog profile locally: write its YAML + ensure its plugins."""
    import yaml

    from bouzecode.backend.core import config as core_config
    from bouzecode.backend.multi_agent import plugin_resolver
    from bouzecode.backend.profiles import catalog
    from bouzecode.web_v2.services.profile_io import serialize

    if not name:
        warn("Usage : /agent install <nom>. Tape /agent pour la liste.")
        return

    profiles = catalog.list_catalog_profiles()
    profile = profiles.get(name)
    if profile is None:
        warn(f"Agent inconnu dans le catalogue : {name}.")
        if profiles:
            info("  Disponibles : " + ", ".join(sorted(profiles)))
        return

    dest_dir = core_config.CONFIG_DIR / "profiles"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{name}.yaml"
    dest.write_text(yaml.safe_dump(serialize(profile), sort_keys=False, allow_unicode=True),
                    encoding="utf-8")
    ok(f"Profil « {name} » écrit dans {dest}.")

    requires = list(getattr(profile, "requires_plugins", []))
    if requires:
        _, errors = plugin_resolver.ensure_plugins(requires)
        if errors:
            warn("Erreurs lors de l'installation des plugins :")
            for err in errors:
                warn(f"   - {err}")
        else:
            ok(f"Plugins requis prêts ({len(requires)}).")
    info(f"Bascule : /agent {name}")
