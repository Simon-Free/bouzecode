# [desc] Un agent réveillé (reprise froide) repart dans le même mode de réflexion qu'à son lancement : même prompt système, donc cache préservé. [/desc]
"""Essai DeepSeek du 2026-09-24, racine 6bafe9cd5ee7 : au réveil (tour 45), `prefixe_change=system`
et 1 152 tokens lus en cache sur 29 345. Le premier lancement passait `--loud`, qui ajoutait alors
le prompt « réflexion à voix haute » (2 419 caractères, supprimé depuis) au préfixe stable ; la
reprise ne le passait pas. Lancement et réveil doivent garder exactement les mêmes options."""
import subprocess
import sys

from bouzecode.web_v2.runtime.runner import agent_creation, agent_reprise, agent_respawn


_POPEN = subprocess.Popen

#  Options du CLI qui façonnent le prompt système ou le raisonnement du modèle.
_OPTIONS_DE_MODE = {"--loud", "--thinking", "--accept-all", "-p"}


class _Capture:
    """Popen de substitution : un vrai process qui se termine aussitôt, dont on garde l'argv."""

    def __init__(self):
        self.commandes = []

    def __call__(self, cmd, cwd=None, env=None, **kwargs):
        self.commandes.append(list(cmd))
        return _POPEN([sys.executable, "-c", "pass"], **kwargs)


def _mode(cmd):
    return {arg for arg in cmd if arg in _OPTIONS_DE_MODE}


def test_un_agent_reveille_garde_le_mode_de_reflexion_de_son_lancement(tmp_path, monkeypatch):
    """Lancé puis réveillé à froid, l'agent reçoit les mêmes options de mode : `--loud` compris."""
    capture = _Capture()
    monkeypatch.setattr(agent_respawn.subprocess, "Popen", capture)

    # L'utilisateur lance une tâche : l'agent démarre, joue un tour, puis son process s'arrête.
    agent = agent_creation.create_agent("Construire la vue Tinder", model="", cwd=str(tmp_path))
    agent_respawn.Path(agent.session_path).write_text(
        '{"messages": [{"role": "user", "content": "Construire la vue Tinder"}, '
        '{"role": "assistant", "content": "ok"}], "turn_count": 1}', encoding="utf-8")
    agent.finished_at, agent.returncode = "2026-09-24T21:40:00Z", 0

    # Son enfant a fini : le serveur le réveille (reprise froide, même session).
    assert agent_reprise.continue_agent(agent, "Ton enfant ui-tinder a fini.") is not None

    lancement, reveil = capture.commandes
    assert "--loud" in lancement
    assert _mode(reveil) == _mode(lancement)


def test_une_reprise_dans_une_nouvelle_session_garde_aussi_le_mode(tmp_path, monkeypatch):
    """La reprise « nouvelle session » (resume_agent) repart elle aussi en `--loud`."""
    capture = _Capture()
    monkeypatch.setattr(agent_respawn.subprocess, "Popen", capture)
    agent = agent_creation.create_agent("Construire la vue Tinder", model="", cwd=str(tmp_path))

    agent_creation.resume_agent(agent, "Reprends.")

    lancement, reprise = capture.commandes
    assert _mode(reprise) == _mode(lancement)
