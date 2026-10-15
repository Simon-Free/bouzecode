# [desc] chrome-devtools-mcp lancé par npx en version épinglée (plus @latest), repli BOUZECODE_CHROME_DEVTOOLS_MCP_VERSION validé. [/desc]
"""`npx chrome-devtools-mcp@latest` avec `npm_config_yes=true` exécutait la dernière version
publiée sur npm, sans revue, à chaque démarrage d'un agent. La version est désormais épinglée."""
import re

import pytest

from bouzecode.backend.chrome_devtools import launcher


@pytest.fixture(autouse=True)
def _sans_surcharge(monkeypatch):
    monkeypatch.delenv(launcher.MCP_VERSION_ENV, raising=False)


def test_version_epinglee_par_defaut():
    args = launcher.build_server_args()
    assert args[0] == launcher.MCP_PACKAGE
    assert "@latest" not in args[0]
    assert re.fullmatch(r"chrome-devtools-mcp@\d+\.\d+\.\d+", args[0])


def test_surcharge_explicite(monkeypatch):
    monkeypatch.setenv(launcher.MCP_VERSION_ENV, "1.11.0")
    assert launcher.build_server_args()[0] == "chrome-devtools-mcp@1.11.0"


@pytest.mark.parametrize("valeur", ["1.0 --evil", "--registry=http://x", "@scope/x", "../x"])
def test_surcharge_invalide_refusee_avec_message(monkeypatch, valeur):
    monkeypatch.setenv(launcher.MCP_VERSION_ENV, valeur)
    with pytest.raises(ValueError, match=launcher.MCP_VERSION_ENV):
        launcher.build_server_args()
