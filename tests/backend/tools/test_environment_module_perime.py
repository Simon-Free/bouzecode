"""`Environment(action='venv')` ne meurt plus sur un module périmé.

Constat du 2026-09-21 (poste Windows) : « Error executing Environment: module
'bouzecode.web_v2.runtime.venv_env' has no attribute 'pinned_python_spec' », alors que la
fonction existait sur disque depuis le 2026-09-09. Le process de l'agent avait chargé
`venv_env` AVANT la mise à jour, puis `worktrees` (import paresseux) APRÈS : un mélange de
versions. L'agent a conclu « action venv cassée sur ce parc » et ne l'a plus jamais rappelée.
"""
import sys

from bouzecode.backend.tools import environment
from bouzecode.web_v2.runtime import venv_env
from bouzecode.web_v2.services.work import worktrees


def test_la_version_a_epingler_survit_a_un_venv_env_perime(monkeypatch):
    monkeypatch.delattr(venv_env, "pinned_python_spec")
    assert worktrees._python_spec() == "%d.%d.%d" % sys.version_info[:3]


def test_une_erreur_de_module_perime_dit_quoi_faire(monkeypatch):
    def _casse(config):
        raise AttributeError("module 'bouzecode.web_v2.runtime.venv_env' has no attribute 'x'")

    monkeypatch.setitem(environment._HANDLERS, "status", _casse)
    out = environment._environment({"action": "status"}, {})
    assert "has no attribute 'x'" in out
    assert "redémarre" in out.lower()
