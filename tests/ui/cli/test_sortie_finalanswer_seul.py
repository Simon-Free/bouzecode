# [desc] `bouzecode -p` exige FinalAnswer comme le web : une réponse en prose relance le modèle ; FinalAnswer → code 0 et `--result-file` ; prose obstinée → relances plafonnées, `final_answer_never_called`, code 4, aucune réponse écrite. [/desc]
"""Le VRAI CLI en sous-process contre un faux LLM local (vrai socket) qui joue un script.
Avant : `-p` clôturait sur la première prose (`text_no_tools`), sortait en 0 et écrivait cette
prose dans `--result-file` — une réponse sans FinalAnswer passait pour une livraison."""
import json
import subprocess

from bouzecode.remote.vm.vm_runner import FICHE_CLOTURE
from bouzecode.ui import cloture_cli
from bouzecode.web_v2.tests.faux_llm_refus import commande_cli, environnement_cli
from bouzecode.web_v2.tests.faux_llm_scripte import FauxLlmScripte, final_answer

PROSE = "Voila, b.txt est ajoute."
RELANCE = "tu DOIS appeler FinalAnswer"
#: `loop_turn.handle_no_tools` : 10 relances, la 11e prose clôt (même plafond que le web).
RELANCES_MAX = 10


def _lancer(llm, dossier):
    return subprocess.run(commande_cli(str(dossier / "reponse.md"), "--cwd", str(dossier)),
                          env=environnement_cli(llm, dossier / "home"), capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=110)


def _relances(requetes: list[dict]) -> int:
    """Requêtes qui portent, en dernier message, la consigne de clore par FinalAnswer."""
    return sum(RELANCE in json.dumps(r["messages"][-1], ensure_ascii=False) for r in requetes)


def test_une_prose_relance_le_modele_puis_finalanswer_livre_en_code_0(tmp_path):
    with FauxLlmScripte([PROSE, final_answer("b.txt ajoute, 1 test vert.")]) as llm:
        sortie = _lancer(llm, tmp_path)
        requetes = list(llm.requetes)

    assert sortie.returncode == cloture_cli.EXIT_LIVRE == 0, sortie.stderr[-2000:]
    assert len(requetes) == 2 and _relances(requetes) == 1  # la prose a été relancée, une fois
    assert (tmp_path / "reponse.md").read_text(encoding="utf-8") == "b.txt ajoute, 1 test vert."
    fiche = json.loads((tmp_path / FICHE_CLOTURE).read_text(encoding="utf-8"))
    assert fiche == {"close_reason": "final_answer", "close_detail": "", "final_answer": True,
                     "code_sortie": 0}


def test_une_prose_obstinee_finit_sans_livraison_en_code_4(tmp_path):
    with FauxLlmScripte([PROSE]) as llm:
        sortie = _lancer(llm, tmp_path)
        requetes = list(llm.requetes)

    assert sortie.returncode == cloture_cli.EXIT_FIN_FORCEE == 4, sortie.stderr[-2000:]
    assert len(requetes) == RELANCES_MAX + 1 and _relances(requetes) == RELANCES_MAX
    assert not (tmp_path / "reponse.md").exists()  # la prose n'est JAMAIS une réponse
    fiche = json.loads((tmp_path / FICHE_CLOTURE).read_text(encoding="utf-8"))
    assert fiche["close_reason"] == "final_answer_never_called"
    assert fiche["final_answer"] is False and fiche["code_sortie"] == 4
