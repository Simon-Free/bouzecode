# [desc] Ce qu'un sous-agent TUI en process ecrit sur stdout/stderr (avertissements de skills, print de la boucle) va dans SON journal, jamais dans le terminal du principal. [/desc]
"""Symptome d'origine : au demarrage des sous-agents, le terminal de main se remplissait de
« [skill] 'x' (...) masquée par (...) » emis par les enfants en chargeant leurs skills.

La boucle LLM est remplacee par un faux `_agent_run` (meme seam que les autres tests en
process) ; le chargement des skills, lui, est le vrai."""
from __future__ import annotations

import sys
import time

import pytest

from bouzecode.backend.agent.state import AgentState, TurnDone
from bouzecode.backend.core import config as module_config
from bouzecode.backend.core.dossier_agent import Atelier
from bouzecode.backend.core.sortie_agent import FluxRoutant, routage
from bouzecode.backend.multi_agent.en_process import execution
from bouzecode.backend.multi_agent.en_process.fiche import FINI
from bouzecode.backend.multi_agent.en_process.registre import RegistreAgents
from bouzecode.backend.tools.skill import load_skills


def _skill(dossier, nom: str, corps: str) -> None:
    cible = dossier / ".bouzecode" / "skills" / nom
    cible.mkdir(parents=True, exist_ok=True)
    (cible / "skill.md").write_text(f"---\nname: {nom}\ndescription: {corps}\n---\n\n{corps}\n",
                                    encoding="utf-8")


def _enfant_bavard(prompt, state, config, system_prompt, depth=0, cancel_check=None):
    """Charge ses skills HORS de tout outil (comme le prompt systeme) et avertit."""
    state.messages.append({"role": "user", "content": prompt})
    yield TurnDone(10, 1)
    noms = sorted(s.name for s in load_skills(include_builtins=False))
    print("[enfant] avertissement de la boucle", file=sys.stderr)
    print("[enfant] trace sur stdout")
    state.final_answer = ",".join(noms)


@pytest.fixture
def enfant_dans_un_projet_ombre(tmp_path, monkeypatch, capsys):
    """Un dossier d'enfant ou `ombre-sortie` existe deux fois (projet externe + interne),
    journaux sous tmp_path."""
    externe = tmp_path / "externe"
    interne = externe / "interne"
    interne.mkdir(parents=True)
    _skill(externe, "ombre-sortie", "version externe")
    _skill(interne, "ombre-sortie", "version interne")
    monkeypatch.setattr(module_config, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr("bouzecode.backend.multi_agent.task._agent_run", _enfant_bavard)
    monkeypatch.setattr(execution, "_sauver", lambda fiche: None)
    monkeypatch.chdir(tmp_path)  # le principal est AILLEURS que l'enfant
    return interne


def _router_comme_le_tui(monkeypatch) -> None:
    """Dans le CORPS du test : pytest repose ses propres flux de capture entre la mise en
    place des fixtures et l'appel du test."""
    monkeypatch.setattr(sys, "stdout", FluxRoutant(sys.stdout))
    monkeypatch.setattr(sys, "stderr", FluxRoutant(sys.stderr))


def _attendre_la_fin(fiche):
    for _ in range(200):
        if fiche.etat == FINI:
            return
        time.sleep(0.02)
    raise AssertionError(f"sous-agent pas fini : {fiche.etat} {fiche.resultat}")


def test_la_sortie_d_un_sous_agent_va_dans_son_journal_pas_chez_main(
        enfant_dans_un_projet_ombre, capsys, monkeypatch):
    _router_comme_le_tui(monkeypatch)
    registre = RegistreAgents()
    registre.declarer_principal(AgentState(), "claude-opus-5")
    config = {"_tui_agents": registre, "model": "claude-opus-5", "_depth": 0}

    fiche = execution.lancer(registre, {"prompt": "charge tes skills"}, config,
                             Atelier(dossier=str(enfant_dans_un_projet_ombre)))
    _attendre_la_fin(fiche)

    terminal_de_main = capsys.readouterr()
    assert "masquée par" not in terminal_de_main.err
    assert "[enfant]" not in terminal_de_main.err + terminal_de_main.out
    journal = fiche.journal.chemin.read_text(encoding="utf-8")
    assert "'ombre-sortie'" in journal and "masquée par" in journal
    assert "[enfant] avertissement de la boucle" in journal
    assert "[enfant] trace sur stdout" in journal
    assert "[enfant] trace sur stdout" in fiche.journal.dernieres
    # Les skills sont celles du dossier de l'ENFANT, meme hors appel d'outil.
    assert "ombre-sortie" in fiche.resultat.split(",")


def test_le_principal_ecrit_toujours_dans_son_terminal(capsys, monkeypatch):
    _router_comme_le_tui(monkeypatch)
    print("[main] visible")
    assert "[main] visible" in capsys.readouterr().out


def test_routage_se_pose_par_dessus_un_flux_tiers_puis_le_rend(monkeypatch):
    """Le patch_stdout de prompt_toolkit remplace sys.stdout pendant la saisie."""
    class FluxTiers:
        def write(self, texte):
            return len(texte)

        def flush(self):
            return None

    tiers = FluxTiers()
    monkeypatch.setattr("bouzecode.backend.core.sortie_agent._installe", False)
    monkeypatch.setattr(sys, "stdout", tiers)
    monkeypatch.setattr(sys, "stderr", tiers)
    with routage():
        assert isinstance(sys.stdout, FluxRoutant) and isinstance(sys.stderr, FluxRoutant)
    assert sys.stdout is tiers and sys.stderr is tiers
