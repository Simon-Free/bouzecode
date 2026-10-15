# [desc] Branche les outils des plugins rangés dans le .bouzecode/ d'un projet. [/desc]
"""Les plugins d'un projet, enfin atteignables.

`demo_application/.bouzecode/plugins/conversation-download/` existait, était
testé, était même affiché dans la carte du dépôt — et restait inatteignable : le
branchement avait été retiré de `LoadProjectConfig`, et le recensement global
(`~/.bouzecode/plugins.json`) ne connaît que les paquets pip.

Deux exigences apprises de l'ancien mécanisme :

- **Panne isolée** : un plugin qui refuse de se charger est signalé et les autres
  se chargent quand même. Une seule dépendance cassée ne doit pas priver l'agent
  de tout un projet.
- **Allumage explicite** : la liste blanche d'import éteint tout ce qui n'y figure
  pas. Enregistrer un outil sans l'allumer, c'est le laisser invisible — c'est
  exactement ce qui avait éteint les outils SQL dans la session analysée.
"""
from __future__ import annotations

from bouzecode.paths import project_dir as bouzecode_project_dir
import importlib
import json
import sys
from pathlib import Path


def _load_module(plugin_dir: Path, module_name: str):
    """Importe `<plugin_dir>/<module_name>.py` sans polluer les imports du projet."""
    if str(plugin_dir) not in sys.path:
        sys.path.insert(0, str(plugin_dir))
    return importlib.import_module(module_name)


def _tool_defs(module) -> list:
    """Construit les ToolDef de bouzecode à partir des dicts purs du plugin.

    Le plugin ne connaît que des dictionnaires : c'est ce qui l'empêche de
    photocopier un type de l'hôte et de diverger silencieusement.
    """
    from ....core.tool_registry import ToolDef

    specs = getattr(module, "TOOLS", None)
    if specs is None:
        return []
    return [
        ToolDef(
            name=spec["name"],
            schema={"name": spec["name"],
                    "description": spec["description"],
                    "input_schema": spec["input_schema"]},
            func=spec["func"],
            read_only=spec.get("read_only", False),
            concurrent_safe=spec.get("concurrent_safe", False),
            ends_turn=spec.get("ends_turn", False),
            snippetable=spec.get("snippetable", False),
            snippet_key=spec.get("snippet_key"),
        )
        for spec in specs
    ]


def _wire_one(plugin_dir: Path) -> tuple[list[str], str]:
    """(noms d'outils branchés, message d'erreur) pour un plugin."""
    from ....core.tool_registry import enable_tool, register_tool

    manifest = json.loads((plugin_dir / "plugin.json").read_text(encoding="utf-8"))
    wired: list[str] = []
    for module_name in manifest.get("tools", []):
        try:
            module = _load_module(plugin_dir, module_name)
        except Exception as error:  # noqa: BLE001 — un plugin cassé ne doit pas priver des autres
            return wired, f"{plugin_dir.name}: {type(error).__name__}: {error}"
        defs = _tool_defs(module)
        if not defs:
            return wired, (f"{plugin_dir.name}: le module {module_name} n'exporte pas TOOLS "
                           "(liste de dicts). Format hérité TOOL_DEFS non supporté.")
        for tool in defs:
            register_tool(tool)
            enable_tool(tool.name)  # sinon la liste blanche d'import le laisse éteint
            wired.append(tool.name)
    return wired, ""


def wire(root: Path) -> tuple[list[str], list[str]]:
    """Branche tous les plugins du projet. Retourne (outils branchés, échecs)."""
    plugins_dir = bouzecode_project_dir(root) / "plugins"
    if not plugins_dir.is_dir():
        return [], []
    wired: list[str] = []
    failures: list[str] = []
    for child in sorted(plugins_dir.iterdir()):
        if not (child / "plugin.json").is_file():
            continue
        names, error = _wire_one(child)
        wired.extend(names)
        if error:
            failures.append(error)
    return wired, failures
