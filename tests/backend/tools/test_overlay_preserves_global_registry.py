# [desc] Un overlay thread-local ne doit jamais priver le registre GLOBAL des outils du noyau. [/desc]
"""`register_tool()` route vers `_local.registry` dès qu'un overlay est actif.

Si `push_local_overlay()` est actif au moment du PREMIER import de `registration`, ses 35
enregistrements par effet de bord tombent dans l'overlay — et `pop_local_overlay()` les JETTE.
Le module restant dans `sys.modules`, plus aucun ré-import ne repeuple le global : il garde
définitivement les seuls outils enregistrés hors overlay (les 7 de `multi_agent.tools`), pour
toute la vie du processus. `get_tool("Read")` rend alors `None`, et `scope_guard/readonly.py`
dénonce `Read, Glob, Grep` comme outils d'écriture.

Mesuré le 2026-07-29 ; le diagnostic initial (« cycle d'imports ») était faux — les deux
ordres d'import donnent 42 outils sur 42.

Le test tourne en SOUS-PROCESSUS : dans le worker pytest, `registration` est déjà importé,
donc l'ordre fautif y est inatteignable. C'est précisément pourquoi aucun test unitaire
n'avait attrapé ce bug.
"""
import json
import subprocess
import sys
from pathlib import Path

SONDE = '''
import json, sys
from bouzecode.backend.core import tool_registry as tr
tr.push_local_overlay()
import bouzecode.backend.tools.registration  # noqa: F401
tr.pop_local_overlay()
print(json.dumps({
    "global": sorted(tr._registry),
    "read": tr.get_tool("Read") is not None,
    "write": tr.get_tool("Write") is not None,
}))
'''

OUTILS_DE_FLOTTE = {"Agent", "CheckAgentResult", "Fleet", "ListAgentTasks",
                    "ListAgentTypes", "MessageAgent", "SendMessage"}


def _sonde(tmp_path: Path) -> dict:
    script = tmp_path / "sonde_overlay.py"
    script.write_text(SONDE, encoding="utf-8")
    run = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert run.returncode == 0, f"la sonde a échoué : {run.stderr[-2000:]}"
    return json.loads(run.stdout.strip().splitlines()[-1])


def test_overlay_actif_au_premier_import_ne_vide_pas_le_registre_global(tmp_path):
    """Après pop, le registre global DOIT porter les outils du noyau, pas seulement les 7
    outils de flotte enregistrés hors overlay."""
    mesure = _sonde(tmp_path)
    assert mesure["read"], (
        f"get_tool('Read') est None après un overlay poussé avant le premier import de "
        f"registration — registre global réduit à {mesure['global']}"
    )
    assert mesure["write"], "get_tool('Write') est None : le registre global a été vidé"
    assert set(mesure["global"]) - OUTILS_DE_FLOTTE, (
        "le registre global ne contient QUE les outils de flotte : les 35 enregistrements "
        "par effet de bord de registration ont été jetés avec l'overlay"
    )


def test_le_registre_global_porte_bien_tous_les_builtins(tmp_path):
    """Contrôle de cadrage : la sonde mesure un registre COMPLET, pas juste non vide."""
    mesure = _sonde(tmp_path)
    assert len(mesure["global"]) >= 40, (
        f"seulement {len(mesure['global'])} outils dans le registre global : {mesure['global']}"
    )
