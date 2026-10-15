# [desc] L'export /export porte un en-tête de version bouzecode (version, commits, provenance, modèle, session, bascules) ; historique versions_successives sauvé/restauré ; ancienne session sans le champ tolérée. [/desc]
"""Régression du 2026-10-06 : un export « malgré un pull » ne disait pas quel code avait tourné
(session à 3.5.102 sur un commit d7b16027 de fusion locale). Pas de mock : vrais fichiers,
vrai git dans un dépôt temporaire."""
from __future__ import annotations

import subprocess
from datetime import datetime

from bouzecode.backend.agent.state import AgentState
from bouzecode.backend.commands.misc import cmd_export
from bouzecode.backend.commands.session.session import _build_session_data
from bouzecode.backend.commands.session.session_pick import restore_state
from bouzecode.backend.core.version_entete import entete_markdown, provenance_du_code
from bouzecode.backend.core.version_session import noter_version

SHA_A = "a" * 40
SHA_B = "d7b16027" + "0" * 32
CONFIG = {"model": "claude-opus-5", "_session_id": "abcd1234"}


def _etat_avec_messages() -> AgentState:
    state = AgentState()
    state.messages = [{"role": "user", "content": "bonjour"},
                      {"role": "assistant", "content": "salut"}]
    return state


def _exporter(state, tmp_path) -> str:
    sortie = tmp_path / "conversation.md"
    cmd_export(str(sortie), state, CONFIG)
    return sortie.read_text(encoding="utf-8")


def test_export_commence_par_l_entete_de_version(tmp_path):
    state = _etat_avec_messages()
    noter_version(state, version="3.5.102", commit="d7b16027", boot_commit=SHA_B)

    md = _exporter(state, tmp_path)

    assert md.startswith("# Export de conversation bouzecode")
    assert "**bouzecode** 3.5.102" in md
    assert "`d7b16027`" in md and f"`{SHA_B}`" in md
    assert "Provenance :" in md
    assert "`claude-opus-5`" in md and "`abcd1234`" in md
    assert "exporté le " in md
    assert md.index("Export de conversation") < md.index("## User")


def test_session_reprise_sur_une_autre_version_liste_les_deux(tmp_path):
    premiere = _etat_avec_messages()
    noter_version(premiere, version="3.5.100", commit="aaaaaaaa", boot_commit=SHA_A)
    premiere.turn_count = 11
    noter_version(premiere, version="3.5.100", commit="aaaaaaaa", boot_commit=SHA_A)
    assert len(premiere.versions_successives) == 1  # même code : pas de nouvelle ligne

    reprise = AgentState()
    restore_state(reprise, _build_session_data(premiere, session_id="abcd1234"))
    noter_version(reprise, version="3.5.102", commit="d7b16027", boot_commit=SHA_B)

    md = _exporter(reprise, tmp_path)
    lignes = [l for l in md.splitlines() if "à partir du tour" in l]
    assert len(lignes) == 2
    assert "tour 1 : **3.5.100**" in lignes[0]
    assert "tour 12 : **3.5.102**" in lignes[1] and "`d7b16027`" in lignes[1]
    assert "2 version(s) successive(s)" in md


def test_ancienne_session_sans_le_champ(tmp_path):
    vide = AgentState()
    restore_state(vide, {"messages": [{"role": "user", "content": "x"}]})
    assert vide.versions_successives == []
    assert "**bouzecode** ?" in _exporter(vide, tmp_path)

    ancienne = AgentState()
    restore_state(ancienne, {"messages": [{"role": "user", "content": "x"}],
                             "bouzecode_version": "3.5.90", "bouzecode_commit": "1234abcd"})
    md = _exporter(ancienne, tmp_path)
    assert "tour inconnu (session antérieure) : **3.5.90**" in md


def test_entete_sans_historique_reprend_les_champs_de_l_etat():
    state = AgentState()
    state.bouzecode_version, state.bouzecode_boot_commit = "3.5.101", SHA_A
    entete = entete_markdown(state, {}, maintenant=datetime(2026, 10, 6, 9, 0, 0))
    assert "**bouzecode** 3.5.101" in entete and "2026-10-06 09:00:00" in entete


def _git(depot, *args) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          cwd=depot, capture_output=True, text=True, check=True).stdout


def test_provenance_hors_depot_et_fusion_locale(tmp_path):
    assert "Artifactory" in provenance_du_code("", SHA_A)

    _git(tmp_path, "init", "-q")
    (tmp_path / "f.txt").write_text("1", encoding="utf-8")
    _git(tmp_path, "add", "f.txt")
    _git(tmp_path, "commit", "-q", "-m", "local")
    sha = _git(tmp_path, "rev-parse", "HEAD").strip()
    (tmp_path / "f.txt").write_text("2", encoding="utf-8")

    constat = provenance_du_code(str(tmp_path), sha)
    assert "arbre local modifié" in constat
    assert f"commit {sha[:8]} absent des branches origin" in constat
