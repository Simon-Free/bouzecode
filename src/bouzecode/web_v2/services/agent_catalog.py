# [desc] Web UI service bridging the catalog layer to the Agents tab (catalog view, install, refresh). [/desc]
"""Bridge between the web UI 'Agents' tab and the backend catalog layer.

Reuses ``backend.profiles.catalog`` (installed_and_available / list_catalog_profiles
/ refresh_catalog), ``profile_io.serialize`` to dump a profile to YAML, and
``plugin_resolver.ensure_plugins`` to materialize a profile's required plugins.
No logic is duplicated here — only adapted to the JSON shape the UI consumes.
"""
from __future__ import annotations

from bouzecode.backend.profiles import catalog
from bouzecode.backend.multi_agent import plugin_resolver

from . import profiles as profiles_svc
from .profile_io import first_line, serialize


def _summary(profile) -> str:
    """Best-effort one-line description for a catalog profile."""
    desc = getattr(profile, "description", "") or ""
    if not desc:
        desc = getattr(profile, "system_prompt_extra", "") or ""
    return first_line(desc)


def _view(profile) -> dict:
    return {
        "name": profile.name,
        "description": _summary(profile),
        "tools": list(profile.tools),
        "requires_plugins": list(getattr(profile, "requires_plugins", [])),
    }


def catalog_view() -> dict:
    """{installed: [...], available: [...]} for the UI 'Agents' tab.

    'installed' = catalog profiles whose plugins are all present + local user
    profiles. 'available' = catalog profiles not yet installed.
    """
    installed, available = catalog.installed_and_available()
    return {
        "installed": sorted((_view(p) for p in installed.values()), key=lambda a: a["name"]),
        "available": sorted((_view(p) for p in available.values()), key=lambda a: a["name"]),
    }


def install(name: str) -> dict:
    """Install a catalog profile locally: write its YAML + ensure its plugins.

    Returns {ok, errors}. Errors are surfaced, never swallowed.
    """
    name = (name or "").strip()
    if not name:
        return {"ok": False, "errors": ["nom d'agent manquant"]}

    profiles = catalog.list_catalog_profiles()
    profile = profiles.get(name)
    if profile is None:
        avail = ", ".join(sorted(profiles)) or "(aucun)"
        return {"ok": False, "errors": [f"agent inconnu dans le catalogue : {name}. Disponibles : {avail}"]}

    # Reuse the same YAML writer the builder uses (~/.bouzecode/profiles/<name>.yaml).
    saved = profiles_svc.save_profile(serialize(profile))
    if isinstance(saved, str):
        return {"ok": False, "errors": [saved]}

    errors: list[str] = []
    requires = list(getattr(profile, "requires_plugins", []))
    if requires:
        try:
            _tools, errors = plugin_resolver.ensure_plugins(requires)
        except Exception as exc:  # noqa: BLE001 — surface, never crash the route
            errors = [f"échec installation plugins: {exc}"]

    return {"ok": not errors, "errors": errors, "name": name}


def refresh() -> dict:
    """Force a refresh of the remote catalog, then return the fresh view."""
    catalog.refresh_catalog(force=True)
    return catalog_view()
