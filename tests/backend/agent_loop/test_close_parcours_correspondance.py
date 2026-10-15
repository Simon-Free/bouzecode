# [desc] Unit tests of how the « parcours vérifiés » gate matches a written proof to the real tool calls: shell forms, prose, output excerpts, and the Windows/PowerShell spellings. [/desc]
"""La preuve écrite par le modèle doit retrouver l'appel qui l'a RÉELLEMENT produite.

Essai du 2026-09-25 : 9 refus sur 10 étaient des faux positifs de correspondance
(guillemets du heredoc, variables `$B`, prose « curl … sur http://… », curl lancé dans un
`$(…)`, extrait de sortie recopié). Et la porte tourne désormais aussi sur le poste Windows
(PowerShell, `C:\\…`, `npx.cmd`, `python.exe`, `$env:X=…; cmd`).
"""
from __future__ import annotations

import pytest

from bouzecode.backend.agent import close_parcours as cp


def _session(*appels: tuple[str, dict, str | None]) -> list[dict]:
    """Un journal : (outil, entrée, résultat) → messages assistant/tool."""
    messages = [{"role": "user", "content": "Corrige le scraper."}]
    for i, (nom, entree, resultat) in enumerate(appels):
        messages.append({"role": "assistant",
                         "tool_calls": [{"id": f"c{i}", "name": nom, "input": entree}]})
        if resultat is not None:
            messages.append({"role": "tool", "tool_call_id": f"c{i}", "content": resultat})
    return messages


def _bash(commande: str, sortie: str = "ok", **extra) -> tuple[str, dict, str]:
    return "Bash", {"command": commande, **extra}, sortie


def _probleme(preuve: str, *appels, exigence: str = "le scraper produit les énigmes") -> str:
    item = {"exigence": exigence, "parcours": "lancer puis relire", "preuve": preuve}
    probleme, _ = cp._verifier(0, item, cp.journal(_session(*appels)))
    return probleme


# ── Formes shell (Linux) ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("preuve, commande", [
    # Guillemets du heredoc : `<<'EOF'` ≡ `<<EOF` (625883f1 t79).
    ("python3 - <<EOF → 312 énigmes", "python3 - <<'EOF'\nimport json\nprint(312)\nEOF"),
    # Variables d'environnement en tête, des deux côtés.
    ("HOME=/home/x BASE=http://127.0.0.1:8795 node /tmp/pe-pw/figures.js → 7/7 OK",
     "cd /tmp/pe-pw && BASE=http://127.0.0.1:8795 node figures.js"),
    # Exécutable + premier script : les arguments ont changé, le script est le même.
    ("python3 scraper/kangourou.py --years 2025 2024 --out /tmp/verif.json → 310 énigmes",
     "cd /home/x/portail && python3 scraper/kangourou.py --years 2025 --out data/e.json"),
    # Sous-shell et mise en fond.
    ("python3 server.py --port 8798 --state /tmp/s.json &",
     "cd /p && (python3 server.py --port 8798 --state /tmp/s.json > /tmp/l 2>&1 &) && sleep 1"),
    # Prose au milieu + curl lancé dans une substitution `$(…)` avec une variable (6bafe9cd t136).
    ("curl -s -o /dev/null -w '%{http_code}' sur /, /index.html, /.git/config → 200 200 404",
     "for u in / /index.html /.git/config; do printf '%s %s\\n' \"$u\" "
     "\"$(curl -s -o /dev/null -w '%{http_code}' \"http://127.0.0.1:8798$u\")\"; done"),
    # Jetons avec `$` ignorés (6bafe9cd t128).
    ("curl -s -o /dev/null -w '%{http_code}' sur http://127.0.0.1:8795/ (200)",
     "B=http://127.0.0.1:8795 && curl -s -o /dev/null -w \"%{http_code}\\n\" $B/index.html"),
])
def test_une_commande_reellement_lancee_est_reconnue_sous_ses_variantes(preuve, commande):
    assert _probleme(preuve, _bash(commande)) == ""


def test_une_preuve_qui_recopie_la_sortie_designe_l_appel():
    """625883f1 t81 : pas de commande citée, mais la sortie recopiée mot pour mot."""
    sortie = "OK 312\n2024-e-24: answer_text=None conf=0.0 needs_review=False\n"
    preuve = "script d'intégrité : 2024-e-24: answer_text=None conf=0.0 needs_review=False"
    assert _probleme(preuve, _bash("python3 /tmp/integrite.py", sortie)) == ""


def test_une_citation_vague_designe_l_execution_dont_elle_recopie_la_sortie():
    """Deux heredocs : le dernier a échoué, mais la preuve recopie la sortie du premier."""
    assert _probleme(
        "python3 - <<EOF → « 12 sujets × 26 questions, numéros 1..26 »",
        _bash("python3 - <<'EOF'\nprint('x')\nEOF", "12 sujets × 26 questions, numéros 1..26"),
        _bash("python3 - <<'EOF'\nraise SystemExit(1)\nEOF", "Traceback\n[exited code=1]"),
    ) == ""


def test_un_curl_jamais_lance_reste_refuse():
    """6bafe9cd t39 : l'API n'avait jamais été interrogée."""
    probleme = _probleme(
        "python3 scraper/kangourou.py --out data/e.json → 310 ; curl http://localhost:8765/api/enigmes",
        _bash("python3 scraper/kangourou.py --out data/e.json", "310 énigmes"),
        _bash("curl -sL https://www.mathkang.org/", "<html>"))
    assert "curl http://localhost:8765/api/enigmes" in probleme and "JAMAIS" in probleme


def test_un_autre_script_du_meme_executable_ne_prouve_pas():
    probleme = _probleme("node /tmp/pe-pw/smoke.js → 20/20 OK", _bash("node /tmp/pe-pw/diag.js"))
    assert "JAMAIS" in probleme


# ── Windows / PowerShell ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("preuve, commande", [
    ("$env:BASE='http://127.0.0.1:8795'; node C:\\pe\\smoke.js → 20/20 OK",
     "$env:BASE='http://127.0.0.1:8795'; node C:\\pe\\smoke.js"),
    ("node smoke.js → 20/20 OK",
     "Set-Location C:\\pe ; $env:BASE = 'http://127.0.0.1:8795' ; node .\\smoke.js"),
    ("npx playwright test tests/e2e/tinder.spec.ts → 5 passed",
     "& \"C:\\Program Files\\nodejs\\npx.cmd\" playwright test tests\\e2e\\tinder.spec.ts"),
    ("npx.cmd playwright test tests\\e2e\\tinder.spec.ts",
     "npx playwright test tests/e2e/tinder.spec.ts --reporter=line"),
    ("python scraper/kangourou.py --years 2025 → 310 énigmes",
     "C:\\Users\\me\\AppData\\Local\\Programs\\Python\\Python312\\python.exe "
     "scraper\\kangourou.py --years 2025"),
    ("python3 scraper/kangourou.py", "py -3 C:\\proj\\scraper\\kangourou.py --out data\\e.json"),
    ("curl -s http://127.0.0.1:8795/api/config", "curl.exe -s http://127.0.0.1:8795/api/config"),
    ("PS C:\\proj> python.exe server.py --port 8798", "Start-Process python.exe; python server.py --port 8798"),
])
def test_les_formes_windows_sont_reconnues(preuve, commande):
    assert _probleme(preuve, _bash(commande)) == ""


def test_windows_un_script_jamais_lance_reste_refuse():
    probleme = _probleme("node C:\\pe\\smoke.js → 20/20 OK",
                         _bash("$env:BASE='http://127.0.0.1:8795'; node C:\\pe\\diag.js"))
    assert "JAMAIS" in probleme


# ── Compléments relevés au rejeu des sessions réelles ─────────────────────────────────────

def test_la_prose_coupe_la_citation_avant_un_faux_script():
    """6bafe9cd t136 : « curl … sur /, …, /../server.py » — `/../server.py` n'est pas un script
    lancé par curl, c'est la liste des URL testées."""
    assert _probleme(
        "curl -s -o /dev/null -w '%{http_code}' sur /, /.git/config, /server.py, /../server.py",
        _bash("for u in / /server.py; do printf '%s\\n' "
              "\"$(curl -s -o /dev/null -w '%{http_code}' \"http://127.0.0.1:8798$u\")\"; done")) == ""


def test_le_nom_de_l_outil_bash_n_est_pas_une_commande():
    """625883f1 t79 : « … + Bash hauteur (1240, 340) » jugé « commande jamais exécutée »."""
    assert cp._commandes_citees("ImageQuestion sur q7.png → OUI + Bash hauteur (1240, 340)") == []
    assert cp._commandes_citees("Bash python3 x.py --out d.json") == ["python3 x.py --out d.json"]


@pytest.mark.parametrize("commande", [
    "cd {d} && HOME=/home/x BASE=http://127.0.0.1:8793 node smoke.js 2>&1 | tail -28",
    "Set-Location {d} ; $env:BASE='http://127.0.0.1:8793' ; node .\\smoke.js",
])
def test_un_script_relatif_se_lit_dans_le_repertoire_du_cd(tmp_path, commande):
    """6bafe9cd t114 : `cd /tmp/pe-pw && node smoke.js` — smoke.js pilote Playwright, mais la
    porte le cherchait dans son propre répertoire : « aucun parcours navigateur »."""
    (tmp_path / "smoke.js").write_text('const { chromium } = require("playwright");\n')
    appel = cp.journal(_session(_bash(commande.format(d=tmp_path), "20/20 OK")))[0]
    assert appel.navigateur()
