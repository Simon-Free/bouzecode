# [desc] Tests the default tool whitelist: only _DEFAULT_ENABLED schemas reach the model. [/desc]
"""Only the _DEFAULT_ENABLED whitelist is sent to the model; every other
registered tool is disabled at import time (token-budget choice) and answers
with a 'currently disabled' error if invoked anyway."""
import bouzecode.backend.tools  # noqa: F401 — triggers builtin registration + whitelist


def _schema_names():
    from bouzecode.backend.core.tool_registry import get_tool_schemas
    return {s["name"] for s in get_tool_schemas()}


def _expected_names(web: bool) -> set:
    """Les deux sources qui allument un outil, moins les outils `web_seulement` hors web."""
    from bouzecode.backend.core.tool_registry import get_tool
    from bouzecode.backend.tools.registration import _DEFAULT_ENABLED
    from bouzecode.backend.chrome_devtools.launcher import BOOTSTRAP_TOOL_NAMES

    expected = set(_DEFAULT_ENABLED) | set(BOOTSTRAP_TOOL_NAMES)
    if web:
        return expected
    return {name for name in expected if not get_tool(name).web_seulement}


def test_whitelisted_tools_exactly_match_schemas(monkeypatch, tmp_path):
    """What reaches the model is EXACTLY what the two enabling sources declare.

    There are two, not one: the `_DEFAULT_ENABLED` whitelist, and the chrome-devtools
    bootstrap pair, which `register_bootstrap_tools()` deliberately registers AFTER the
    whitelist pass and re-enables by hand so it survives the global disable. Asserting
    against the union keeps the drift check exact — a tool appearing in the schemas
    without belonging to either source still fails here.

    Les outils `web_seulement` (Fleet, MessageAgent — commit 1ec95a00) restent dans la
    whitelist mais ne sont proposés que sous bouzeui web (`BOUZECODE_WEB_IPC_DIR`) :
    le contrôle est fait dans les DEUX modes.
    """
    for web in (False, True):
        if web:
            monkeypatch.setenv("BOUZECODE_WEB_IPC_DIR", str(tmp_path))
        else:
            monkeypatch.delenv("BOUZECODE_WEB_IPC_DIR", raising=False)
        expected, names = _expected_names(web), _schema_names()
        assert names == expected, (
            f"schemas/whitelist drift (web={web}): extra={names - expected}, "
            f"missing={expected - names}"
        )


def test_non_whitelisted_tool_absent_and_errors_when_called():
    from bouzecode.backend.core.tool_registry import execute_tool

    assert "EnterPlanMode" not in _schema_names()
    result = execute_tool("EnterPlanMode", {}, {})
    assert "n'est pas disponible pour cet agent" in result
    assert "/tools enable" not in result   # une commande REPL que l'agent ne peut pas émettre
