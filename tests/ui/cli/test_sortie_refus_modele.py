# [desc] `bouzecode -p` face à un refus du modèle : code de sortie 3 et fiche `<result-file>.cloture.json` (content_refusal), sans relance ; table des codes de sortie par raison de clôture. [/desc]
"""Le VRAI CLI, lancé en sous-process contre un faux LLM local (vrai socket) qui refuse tout.
Avant : sortie 0, rien sur disque — un refus passait pour un succès (Rundeck, exécution 257426)."""
import json
import subprocess

import pytest

from bouzecode.remote.vm.vm_runner import FICHE_CLOTURE
from bouzecode.ui import cloture_cli
from bouzecode.web_v2.tests.faux_llm_refus import FauxLlmRefus, commande_cli, environnement_cli


def test_un_refus_du_modele_sort_en_code_3_avec_sa_raison_sur_disque(tmp_path):
    reponse = tmp_path / "reponse.md"
    with FauxLlmRefus() as llm:
        sortie = subprocess.run(commande_cli(str(reponse), "--cwd", str(tmp_path)),
                                env=environnement_cli(llm, tmp_path / "home"), capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=100)
        requetes = len(llm.requetes)

    assert sortie.returncode == cloture_cli.EXIT_REFUS_MODELE == 3, sortie.stderr[-2000:]
    assert requetes == 1  # la boucle ne relance pas un refus : elle coupe (sortie 3)
    assert "content filter blocked this turn" in sortie.stderr
    fiche = json.loads((tmp_path / FICHE_CLOTURE).read_text(encoding="utf-8"))
    assert fiche["close_reason"] == "content_refusal" and fiche["final_answer"] is False
    assert fiche["code_sortie"] == 3 and "filtre de contenu" in fiche["close_detail"]


@pytest.mark.parametrize("close_reason, code", [
    ("final_answer", 0), ("ends_turn_tool", 0), ("final_answer_over_failed_tool", 0),
    ("content_refusal", 3),
    ("text_no_tools", 4), ("max_turns_exceeded", 4), ("empty_completion", 4),
    ("final_answer_never_called", 4),
    ("stream_stalled", 5), ("cancelled", 5), ("raison_inconnue", 5), ("", 5),
])
def test_code_de_sortie_par_raison_de_cloture(close_reason, code):
    """0 = FinalAnswer et rien d'autre : une réponse en prose est une fin sans livraison (4)."""
    assert cloture_cli.code_de_sortie(close_reason) == code


def test_la_fiche_du_cli_est_celle_que_lit_la_vm():
    """`lancement.commande_agent` passe `--result-file "$BZ_RESULTAT/reponse.md"`."""
    assert cloture_cli.chemin_fiche("/x/reponse.md").name == FICHE_CLOTURE
