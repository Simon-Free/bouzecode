# [desc] Catalog-backed helpers for /agent: list installed/available profiles and install one (write YAML + plugins). [/desc]
"""Catalog-backed helpers for the `/agent` command (kept out of agent_switch.py
to honour the <200-lines-per-file charter)."""
from __future__ import annotations

from bouzecode.ui.ansi import info, ok, warn
from bouzecode.ui.messages import msg


def _catalog_split() -> tuple[dict, dict]:
    """(installed, available) from the shared catalog. Tolerant of network failures."""
    from bouzecode.backend.profiles import catalog, load_user_profiles
    try:
        return catalog.installed_and_available()
    except Exception as exc:  # noqa: BLE001 — network/git can fail; never crash the listing
        warn(msg("agent.catalog_unavailable", error=exc))
        return load_user_profiles(), {}


def _install(name: str, config: dict) -> None:
    """Install a catalog profile locally: write its YAML + ensure its plugins."""
    import yaml

    from bouzecode.backend.core import config as core_config
    from bouzecode.backend.multi_agent import plugin_resolver
    from bouzecode.backend.profiles import catalog
    from bouzecode.web_v2.services.profile_io import serialize

    if not name:
        warn(msg("agent.install_usage"))
        return

    profiles = catalog.list_catalog_profiles()
    profile = profiles.get(name)
    if profile is None:
        warn(msg("agent.unknown_in_catalog", name=name))
        if profiles:
            info(msg("agent.available_label") + ", ".join(sorted(profiles)))
        return

    dest_dir = core_config.CONFIG_DIR / "profiles"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{name}.yaml"
    dest.write_text(yaml.safe_dump(serialize(profile), sort_keys=False, allow_unicode=True),
                    encoding="utf-8")
    ok(msg("agent.profile_written", name=name, destination=dest))

    requires = list(getattr(profile, "requires_plugins", []))
    if requires:
        _, errors = plugin_resolver.ensure_plugins(requires)
        if errors:
            warn(msg("agent.plugin_install_errors"))
            for err in errors:
                warn(f"   - {err}")
        else:
            ok(msg("agent.plugins_ready", count=len(requires)))
    info(msg("agent.switch_to", name=name))
