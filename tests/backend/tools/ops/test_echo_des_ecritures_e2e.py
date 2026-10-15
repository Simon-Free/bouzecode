# [desc] Conversation tests: after Write/Edit the model sees what it wrote (real line numbers) and can Snippet it without a Read. [/desc]
"""L'agent ne voyait pas ce qu'il venait d'écrire.

Au tour suivant, le fil ne gardait d'un `Write` que « Created X (N lines) » et un rappel
de l'appel coupé à 200 caractères AU MILIEU du contenu : sur une vraie session DeepSeek,
l'agent a relu ou ré-exécuté ses propres fichiers plus de dix fois (« le retour du Write
est tronqué »). Désormais l'écho porte un aperçu numéroté avec les lignes RÉELLES du
fichier, et ce qui vient d'être écrit s'épingle directement avec Snippet, sans Read.
"""
from __future__ import annotations

from bouzecode.backend.context_manager.state import METHODOLOGY_NOTE
from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m{n}"><param name="content">ok {n}</param></tool_use>'


def _meth(n: int) -> str:
    return METH.format(n=n)


def _write(path, contenu: str, tid: str = "w1", temp: bool = False) -> str:
    extra = '<param name="temp">true</param>' if temp else ""
    return (f'<tool_use name="Write" id="{tid}"><param name="file_path">{path}</param>'
            f'<param name="content">{contenu}</param>{extra}</tool_use>')


def _edit(path, old: str, new: str) -> str:
    return (f'<tool_use name="Edit" id="e1"><param name="file_path">{path}</param>'
            f'<param name="old_string">{old}</param><param name="new_string">{new}</param>'
            f'</tool_use>')


def _snippet(path, a: int, b: int) -> str:
    return (f'<tool_use name="Snippet" id="s1"><param name="file_path">{path}</param>'
            f'<param name="ranges">[[{a}, {b}]]</param></tool_use>')


def _texte_envoye(mock: MockLLM, appel: int) -> str:
    return "\n".join(str(m.get("content", "")) for m in mock.get_messages(appel))


def _programme(n: int) -> str:
    return "\n".join(f"def fonction_{i}():\n    return {i}" for i in range(1, n + 1)) + "\n"


def test_apres_un_write_le_modele_voit_un_apercu_numerote_et_pas_un_contenu_coupe(tmp_path):
    """Le tour suivant montre les lignes réelles du fichier écrit, ses symboles, et un rappel sans contenu tronqué."""
    cible = tmp_path / "module.py"
    mock = MockLLM([f"{_meth(1)}\n{_write(cible, _programme(40))}", "Écrit."])
    bouzecode(["écris le module"], mock_llm=mock)

    vu = _texte_envoye(mock, 1)
    assert f"[↩ Write: {cible} (80 lignes écrites)]" in vu
    assert '"content": "def fonction' not in vu        # plus de JSON coupé au milieu
    assert "     1\tdef fonction_1():" in vu           # tête, numéros réels
    assert "    80\t    return 40" in vu               # queue, numéros réels
    assert "lignes non affichées (présentes sur disque)" in vu
    assert "Fichier complet sur disque : 80 lignes" in vu
    assert "fonction_1 L1" in vu and "Symboles :" in vu


def test_ce_qui_vient_d_etre_ecrit_s_epingle_sans_read(tmp_path):
    """Write puis, au tour suivant, Snippet d'une plage du fichier écrit : accepté, contenu exact, aucun Read."""
    cible = tmp_path / "module.py"
    mock = MockLLM([
        f"{_meth(1)}\n{_write(cible, _programme(30))}",
        f"{_meth(2)}\n{_snippet(cible, 41, 44)}",
        "Épinglé.",
    ])
    result = bouzecode(["écris puis garde les fonctions 21 et 22"], mock_llm=mock)

    note = result.state.context_state.notes.get(METHODOLOGY_NOTE, "")
    assert f"## snippet: {cible} L41-44" in note
    assert "def fonction_21():" in note and "return 22" in note
    appels = [tc["name"] for m in result.messages for tc in (m.get("tool_calls") or [])]
    assert "Read" not in appels


def test_apres_un_edit_la_zone_modifiee_est_nommee_et_le_snippet_est_a_jour(tmp_path):
    """Edit : la zone modifiée est donnée en lignes réelles, et un Snippet de cette zone rend le contenu à jour."""
    cible = tmp_path / "module.py"
    mock = MockLLM([
        f"{_meth(1)}\n{_write(cible, _programme(10))}",
        f"{_meth(2)}\n{_edit(cible, '    return 5', '    return 500')}",
        f"{_meth(3)}\n{_snippet(cible, 9, 10)}",
        "Corrigé.",
    ])
    result = bouzecode(["écris, corrige la fonction 5, garde-la"], mock_llm=mock)

    vu = _texte_envoye(mock, 2)
    assert "Zone modifiée : lignes 10–10 (fichier : 20 lignes)" in vu
    note = result.state.context_state.notes.get(METHODOLOGY_NOTE, "")
    assert "return 500" in note and "return 5\n" not in note


def test_un_fichier_temporaire_s_epingle_par_son_chemin_logique(tmp_path):
    """Write(temp=True) vit dans le scratch : son chemin logique reste une source valide pour Snippet."""
    logique = "/tmp/sonde_echo_test.py"
    mock = MockLLM([
        f"{_meth(1)}\n{_write(logique, _programme(5), temp=True)}",
        f"{_meth(2)}\n{_snippet(logique, 1, 2)}",
        "Épinglé.",
    ])
    result = bouzecode(["écris une sonde jetable"], mock_llm=mock)

    note = result.state.context_state.notes.get(METHODOLOGY_NOTE, "")
    assert "def fonction_1():" in note
    assert "snippet ERROR" not in note


def test_la_zone_modifiee_d_un_edit_est_celle_du_remplacement(tmp_path):
    """new_string présent plus haut dans le fichier : la zone annoncée reste celle de l'Edit."""
    from bouzecode.backend.tools.ops.file_ops import _edit

    cible = tmp_path / "m.py"
    cible.write_text("x = 1\n" + "pass\n" * 10 + "y = 2\n", encoding="utf-8")

    resultat = _edit(str(cible), "y = 2", "x = 1")

    assert "Zone modifiée : lignes 12–12" in resultat
