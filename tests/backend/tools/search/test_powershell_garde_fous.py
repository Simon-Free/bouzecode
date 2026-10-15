"""Garde-fous PowerShell du Bash sous Windows, sur des commandes relevées dans les sessions réelles.

Relevés (70 sessions du poste Windows, PowerShell 5.1) :
  - heredoc bash envoyé tel quel : `git commit -F - <<'MSG'` → « L'opérateur « < » est réservé
    à une utilisation future », rien n'est exécuté (le script entier ne se parse pas) ;
  - `git commit -m "... $batch ..."` : PowerShell remplace `$batch` par une chaîne vide, et
    `` `teams` `` en Markdown devient TABULATION + « eams » — le message committé est faux ;
  - `pytest ... -m ""` : PS 5.1 supprime l'argument vide, `-m` avale l'argument suivant ;
  - « Au caract�re Ligne:7 » : la sortie de PowerShell est en page de code OEM, décodée en UTF-8 ;
  - barres de progression (Invoke-WebRequest) qui ralentissent et polluent la sortie.
"""
import base64
import sys

import pytest

from bouzecode.backend.tools.ops import shell_search
from bouzecode.backend.tools.ops.powershell_guard import (
    PREAMBULE_POWERSHELL, avec_preambule, decoder_sortie, diagnostic_powershell,
)

_HEREDOC = """$py = "C:\\Users\\user01\\PycharmProjects\\demo\\bouzecode\\.venv\\Scripts\\python.exe"
& $py -m pytest tests/backend/compaction -q
if ($LASTEXITCODE -eq 0) {
  git add src/bouzecode/backend/context_manager/compact_prose.py
  git commit -F - <<'MSG'
fix(compaction): prose
MSG
}"""


def test_un_heredoc_bash_est_refuse_avec_la_recette_powershell():
    refus, _ = diagnostic_powershell(_HEREDOC)
    assert "heredoc" in refus
    assert "git commit -F" in refus and "@'" in refus


@pytest.mark.parametrize("commande,indice", [
    ('git commit -q -m "Traiter le lot $batch puis $top"', "$batch"),
    ("git commit -m \"L'outil bureau `teams` mettait 14 s\"", "`t"),
    ('cd C:\\x ; git add a.py ; git commit -m "perf: $n appels"', "$n"),
])
def test_un_message_de_commit_interpole_par_powershell_est_refuse(commande, indice):
    refus, _ = diagnostic_powershell(commande)
    assert indice in refus
    assert "-F" in refus


@pytest.mark.parametrize("commande", [
    "git commit -m 'Traiter le lot $batch'",           # guillemets simples : littéral
    '$m = "fix: x" ; git commit -m "$m"',               # variable définie dans la commande
    'git commit -m "fix(bureau): plus de doublon"',     # rien à interpoler
    "git commit -F C:\\Temp\\msg.txt",
    'Write-Output "total: $($files.Count)"',            # hors message de commit
])
def test_les_commandes_saines_passent(commande):
    assert diagnostic_powershell(commande) == ("", "")


def test_un_argument_vide_vers_un_programme_externe_est_signale():
    refus, note = diagnostic_powershell(
        'python.exe -m pytest tests/a.py -m "" -p no:cacheprovider -q')
    assert not refus
    assert '-m ""' in note and "5.1" in note


def test_decodage_page_de_code_oem_quand_ce_nest_pas_de_lutf8():
    assert decoder_sortie("Au caractère Ligne:7".encode("cp850")) == "Au caractère Ligne:7"
    assert decoder_sortie("déjà UTF-8 ✓".encode("utf-8")) == "déjà UTF-8 ✓"
    assert decoder_sortie(b"") == ""


def test_le_preambule_force_utf8_et_coupe_la_progression(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(shell_search, "_powershell_exe", lambda: "powershell.exe")
    argv, shell, temp = shell_search._build_popen_command("git log -1")
    corps = base64.b64decode(argv[-1]).decode("utf-16-le")
    assert corps.startswith(PREAMBULE_POWERSHELL)
    assert corps.endswith("git log -1")
    for attendu in ("[Console]::OutputEncoding", "$ProgressPreference", "Get-Content:Encoding"):
        assert attendu in PREAMBULE_POWERSHELL


def test_bash_refuse_le_heredoc_sous_windows_sans_rien_lancer(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")

    def _jamais(*a, **k):
        raise AssertionError("rien ne doit être lancé")

    monkeypatch.setattr(shell_search.subprocess, "Popen", _jamais)
    out = shell_search._bash(_HEREDOC)
    assert "heredoc" in out


@pytest.mark.parametrize("tete", ["using namespace System.Text\n", "param($x)\n",
                                  "#Requires -Version 5\n"])
def test_rien_ne_precede_ce_qui_doit_ouvrir_le_script(tete):
    assert avec_preambule(tete + "Write-Output 1") == tete + "Write-Output 1"
