"""Force `pip install --upgrade` of the plugins required by one or all agent profiles."""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from bouzecode.ui.ansi import err, info, ok
from bouzecode.ui.messages import msg
from ..multi_agent.plugin_resolver import _normalize
from ..plugin import install_plugin, register_plugin_tools
from ..plugin.types import PluginScope
from ..profiles.discovery import load_user_profiles


def _plugins_to_upgrade(profiles: dict, agent_name: str | None) -> tuple[list[dict], str | None]:
    """Collect & dedupe (by package) the requires_plugins of one agent or all.

    Returns (entries, error). entries = [{"package", "source"}]. On unknown
    agent_name, returns ([], "<message listing available names>").
    """
    if agent_name and agent_name not in profiles:
        available = ", ".join(sorted(profiles)) or msg("upgrade.no_profile")
        return [], msg("upgrade.unknown_agent", name=agent_name, available=available)

    if agent_name:
        targets = [profiles[agent_name]]
    else:
        targets = list(profiles.values())

    seen: dict[str, dict] = {}
    for profile in targets:
        for requirement in getattr(profile, "requires_plugins", None) or []:
            package, source = _normalize(requirement)
            if not package or package in seen:
                continue
            seen[package] = {"package": package, "source": source}
    return list(seen.values()), None


def _pkg_version(package: str) -> str | None:
    """Best-effort installed version, or None if the package is absent."""
    try:
        return version(package)
    except PackageNotFoundError:
        return None


def cmd_agent_upgrade(arg: str, state, config):
    """/agent-upgrade [name] -- upgrade plugins required by all agents or one."""
    agent_name = arg.strip() or None
    profiles = load_user_profiles()
    entries, error = _plugins_to_upgrade(profiles, agent_name)
    if error:
        err(error)
        return True

    if not entries:
        scope = (msg("upgrade.scope_one_agent", name=agent_name) if agent_name
                 else msg("upgrade.scope_all_profiles"))
        info(msg("upgrade.nothing_required", scope=scope))
        return True

    target = (msg("upgrade.target_one_agent", name=agent_name) if agent_name
              else msg("upgrade.target_all_profiles"))
    info(msg("upgrade.updating", count=len(entries), target=target))
    for entry in entries:
        package = entry["package"]
        source = entry["source"]
        v_before = _pkg_version(package)
        installed, message = install_plugin(package, scope=PluginScope.USER, source=source)
        v_after = _pkg_version(package)
        if installed:
            transition = f"v{v_before or '?'}->v{v_after or '?'}"
            ok(f"  {package}: OK {transition}")
        else:
            err(msg("upgrade.package_failed", package=package, message=message))

    register_plugin_tools()
    info(msg("upgrade.tools_registered"))
    return True
