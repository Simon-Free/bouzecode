# [desc] Conversation tests: a too-wide Grep listing files answers short, with paths relative to the agent's folder and a per-folder rollup. [/desc]
"""Un Grep trop large répond court au lieu de répondre énorme — et ne refuse jamais.

Session d407d73d (2026-10-07) : `Grep(output_mode="files_with_matches")` sans `path`
depuis la racine du monorepo a rendu 149 chemins absolus, 18 895 caractères, 12 261
tokens. Désormais : chemins relatifs au dossier de l'agent, au plus `GREP_FILES_CAP`
fichiers répartis entre les dossiers, le total réel et le décompte par dossier.
"""
from __future__ import annotations

import re

from bouzecode.backend.tools.ops.grep_cap import GREP_FILES_CAP
from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
CLOSE = "C'est fait."
NEEDLE = "AiguilleGrepCap7f3e"
_BANNIERE = re.compile(r"\[Grep : (\d+) fichiers correspondent, (\d+) affichés")


def _arbre(racine, par_dossier, dossiers=("alpha", "beta", "gamma")):
    """`par_dossier` fichiers contenant NEEDLE dans chacun des `dossiers`."""
    for dossier in dossiers:
        (racine / dossier).mkdir(parents=True, exist_ok=True)
        for i in range(par_dossier):
            (racine / dossier / f"mod_{i:03d}.py").write_text(f"x = '{NEEDLE}'\n", encoding="utf-8")


def _grep(output_mode, path=None):
    """L'agent lance un Grep ; on rend le résultat d'outil tel que le modèle l'a reçu."""
    param_path = f'<param name="path">{path.as_posix()}</param>' if path else ""
    mock = MockLLM([
        f'{METH}\n<tool_use name="Grep" id="g1"><param name="pattern">{NEEDLE}</param>'
        f'<param name="output_mode">{output_mode}</param>{param_path}</tool_use>',
        CLOSE,
    ])
    result = bouzecode(["où est l'aiguille ?"], mock_llm=mock)
    sorties = [m["content"] for m in result.messages
               if m.get("role") == "tool" and m.get("name") == "Grep"]
    assert sorties, "aucun résultat Grep dans la conversation"
    return sorties[0]


def _chemins(sortie):
    return [l for l in sortie.splitlines() if l.split(":")[0].endswith(".py")]


def test_un_grep_trop_large_affiche_le_plafond_et_le_vrai_total(tmp_path, monkeypatch):
    """90 fichiers trouvés depuis le dossier de l'agent : 30 chemins relatifs, répartis
    à parts égales entre les dossiers, le total réel et le décompte par dossier."""
    monkeypatch.chdir(tmp_path)
    _arbre(tmp_path, par_dossier=30)
    sortie = _grep("files_with_matches")

    banniere = _BANNIERE.search(sortie)
    assert banniere, sortie[-500:]
    assert (int(banniere.group(1)), int(banniere.group(2))) == (90, GREP_FILES_CAP)
    chemins = _chemins(sortie)
    assert len(chemins) == GREP_FILES_CAP
    assert str(tmp_path) not in sortie                      # aucun préfixe absolu répété
    assert all((tmp_path / c).is_file() for c in chemins)   # relisibles tels quels
    for dossier in ("alpha", "beta", "gamma"):
        assert sum(c.startswith(dossier) for c in chemins) == GREP_FILES_CAP // 3
        assert f"  {dossier}  (30)" in sortie
    assert "restreins avec path=" in sortie


def test_le_mode_count_est_plafonne_de_la_meme_facon(tmp_path, monkeypatch):
    """`output_mode=count` sur 90 fichiers : même plafond, chaque ligne garde son compte."""
    monkeypatch.chdir(tmp_path)
    _arbre(tmp_path, par_dossier=30)
    sortie = _grep("count")

    assert _BANNIERE.search(sortie)
    chemins = _chemins(sortie)
    assert len(chemins) == GREP_FILES_CAP
    assert all(c.endswith(":1") for c in chemins)


def test_un_grep_sous_le_plafond_rend_toute_la_liste_en_relatif(tmp_path, monkeypatch):
    """Une recherche bien ciblée n'est pas taxée : liste complète, sans bannière."""
    monkeypatch.chdir(tmp_path)
    _arbre(tmp_path, par_dossier=4)
    sortie = _grep("files_with_matches")

    assert _BANNIERE.search(sortie) is None
    attendus = {f"{d}/mod_{i:03d}.py" for d in ("alpha", "beta", "gamma") for i in range(4)}
    assert {c.replace("\\", "/") for c in _chemins(sortie)} == attendus


def test_un_path_hors_du_dossier_de_l_agent_garde_les_chemins_absolus(tmp_path, monkeypatch):
    """Cherché ailleurs que dans son dossier, l'agent reçoit des chemins absolus, et le
    décompte se fait par sous-dossier du `path` demandé (directement réutilisable)."""
    (tmp_path / "ailleurs").mkdir()
    monkeypatch.chdir(tmp_path / "ailleurs")
    _arbre(tmp_path / "code", par_dossier=30)
    sortie = _grep("files_with_matches", path=tmp_path / "code")

    assert _BANNIERE.search(sortie)
    assert all(c.startswith(str(tmp_path / "code")) for c in _chemins(sortie))
    assert f"  {tmp_path / 'code' / 'alpha'}  (30)" in sortie
