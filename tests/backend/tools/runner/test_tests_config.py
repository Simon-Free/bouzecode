# [desc] `.bouzecode/tests.yaml` (clé `impacted`) : lecture des deux vrais fichiers demo_application et demoapp_clone, globs `**` dans paths, tests et always, clés inconnues ignorées. [/desc]
"""Les deux fichiers de `fixtures_tests_yaml/` sont des copies des vrais `.bouzecode/tests.yaml`
écrits le 2026-10-14 pour demo_application et demoapp_clone (branche claude/tests-config) :
ce que le chargeur doit accepter tel quel, clés `browser` et `app_server` comprises."""
from __future__ import annotations

from pathlib import Path

import pytest

from bouzecode.backend.tools.ops.tests_config import (
    ConfigTests, correspond, etendre, lire_config_tests,
)

FIXTURES = Path(__file__).parent / "fixtures_tests_yaml"


def _projet_avec(tmp_path: Path, nom_fixture: str) -> Path:
    (tmp_path / ".bouzecode").mkdir()
    (tmp_path / ".bouzecode" / "tests.yaml").write_bytes((FIXTURES / nom_fixture).read_bytes())
    return tmp_path


def test_demo_application_se_lit_cles_inconnues_ignorees(tmp_path):
    config = lire_config_tests(_projet_avec(tmp_path, "demo_application.yaml"))
    assert "tests/test_shared_settings.py" in config.always
    assert len(config.always) == 12
    assert "tests/focus/test_pptx_integration.py" in config.slow
    vendor = [r for r in config.map if "src/portal/static/vendor/**" in r.paths][0]
    assert "tests/test_vendor_references.py" in vendor.tests


def test_demoapp_clone_mappe_un_template_d_ecran_vers_ses_tests(tmp_path):
    config = lire_config_tests(_projet_avec(tmp_path, "demoapp_clone.yaml"))
    tests = config.tests_pour("src/demoapp/ui/templates/demoapp_events_forms.html")
    assert "tests/test_demoapp_events.py" in tests and "tests/test_demoapp_events_forms.py" in tests
    assert config.tests_pour("oracle/business-rules/x/y.json") == config.tests_pour(
        "oracle/rules/z.json")
    assert "tests/test_interaction_fields.py" in config.slow


def test_projet_sans_fichier_donne_une_config_vide(tmp_path):
    assert lire_config_tests(tmp_path) == ConfigTests()


def test_cle_impacted_mal_formee_est_une_erreur_lisible(tmp_path):
    (tmp_path / ".bouzecode").mkdir()
    (tmp_path / ".bouzecode" / "tests.yaml").write_text("impacted:\n  always: tests/x.py\n")
    with pytest.raises(ValueError, match="always"):
        lire_config_tests(tmp_path)


@pytest.mark.parametrize("motif, chemin, attendu", [
    ("src/vendor/**", "src/vendor/a/b.js", True),
    ("src/vendor/**", "src/vendorx/a.js", False),
    ("src/apps/*/static/js/vendor/**", "src/apps/focus/static/js/vendor/m.js", True),
    ("src/apps/*/static/js/vendor/**", "src/apps/a/b/static/js/vendor/m.js", False),
    ("src/**/*.html", "src/a.html", True),
    ("src/**/*.html", "src/x/y/a.html", True),
    ("tests/test_x.py", "tests/test_x.py", True),
    ("src/demoapp/ui/static/screens/route_panel.*", "src/demoapp/ui/static/screens/route_panel.js", True),
])
def test_globs(motif, chemin, attendu):
    assert correspond(motif, chemin) is attendu


def test_globs_acceptes_dans_tests_et_always(tmp_path):
    for nom in ("test_demoapp_events.py", "test_demoapp_events_forms.py", "test_autre.py"):
        (tmp_path / "tests").mkdir(exist_ok=True)
        (tmp_path / "tests" / nom).write_text("")
    (tmp_path / "tests" / "security").mkdir()
    assert etendre(tmp_path, "tests/test_demoapp_events*.py") == [
        "tests/test_demoapp_events.py", "tests/test_demoapp_events_forms.py"]
    assert etendre(tmp_path, "tests/security") == ["tests/security"]
    assert etendre(tmp_path, "tests/absent.py") == []
