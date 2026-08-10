# [desc] La phase de démarrage dit ce qui se passe pendant les secondes où « en cours » ne dit rien. [/desc]
"""Entre le clic et le premier mot du modèle, il s'écoule ~10 s : ~4 s de démarrage du
process, puis ~6 s d'attente du modèle sur le PREMIER tour (il écrit son cache au lieu de le
lire). L'écran n'affichait rien pendant ce temps — l'utilisateur croit que ça a planté.

`store.demarrage_phase` DÉRIVE la phase de ce qui existe déjà sur disque, sans que la boucle
d'agent ne stampe quoi que ce soit : rien à synchroniser, donc rien à faire diverger. Et la
REPRISE est couverte sans un mot de plus — un tour 12 qui attend son modèle présente
exactement les mêmes preuves qu'un tour 1.
"""
import json
from pathlib import Path

import pytest

from bouzecode.web_v2.services.sessions import store


class _FauxAgent:
    """Mêmes champs que `runner.Agent` que la phase consulte."""

    def __init__(self, session_path: str, agent_id: str = "phase00000001"):
        self.agent_id = agent_id
        self.session_path = session_path
        self.returncode = None
        self.pid = 0
        self.ipc_dir = ""


def _session(tmp_path: Path, nom: str = "a.session.json") -> Path:
    chemin = tmp_path / nom
    chemin.write_text(json.dumps({"messages": []}), encoding="utf-8")
    return chemin


def test_process_lance_mais_session_absente_est_un_demarrage(tmp_path):
    """Le process vit, aucune session : il charge le harnais et lit le projet."""
    agent = _FauxAgent(str(tmp_path / "jamais_ecrite.session.json"))
    assert store.demarrage_phase(agent, "starting", {}) == "demarrage"


def test_session_ecrite_sans_sortie_partielle_est_une_attente_du_modele(tmp_path):
    """La requête est partie, rien n'est revenu : c'est le modèle qu'on attend, pas l'agent."""
    agent = _FauxAgent(str(_session(tmp_path)))
    assert store.demarrage_phase(agent, "running", {}) == "attente_modele"


def test_des_que_le_modele_repond_la_phase_s_efface(tmp_path):
    """Le streaming existant prend le relais : la phase ne doit pas rester collée."""
    session = _session(tmp_path)
    partiel = session.with_name(session.name.replace(".json", ".partial.json"))
    partiel.write_text(json.dumps({"text": "Voici ma pro"}), encoding="utf-8")
    agent = _FauxAgent(str(session))
    assert store.demarrage_phase(agent, "running", {}) == ""


def test_la_reprise_est_couverte_par_la_meme_regle(tmp_path):
    """Une session DÉJÀ REMPLIE (reprise, tour N) qui attend son modèle affiche la même
    chose qu'un tour 1 : c'est tout l'intérêt de dériver au lieu de stamper."""
    session = tmp_path / "reprise.session.json"
    session.write_text(json.dumps({"messages": [{"role": "user", "content": "1er tour"},
                                                {"role": "assistant", "content": "fait"}]}),
                       encoding="utf-8")
    agent = _FauxAgent(str(session))
    assert store.demarrage_phase(agent, "running", {}) == "attente_modele"


@pytest.mark.parametrize("etat", ["finished", "awaiting_input", "crashed", "idle"])
def test_aucune_phase_quand_un_etat_ordinaire_suffit(tmp_path, etat):
    """La phase raffine l'ATTENTE, elle n'ajoute pas un état de plus : « terminé »,
    « à répondre » et « planté » se suffisent et doivent garder leur couleur."""
    agent = _FauxAgent(str(_session(tmp_path)))
    assert store.demarrage_phase(agent, etat, {}) == ""


def test_un_outil_en_cours_n_est_pas_une_attente_du_modele(tmp_path):
    """Pendant qu'un outil tourne, l'agent TRAVAILLE : annoncer « le modèle lit votre
    demande » serait faux, et l'affichage d'outil existant est plus précis."""
    agent = _FauxAgent(str(_session(tmp_path)))
    assert store.demarrage_phase(agent, "running", {"tool": "Read"}) == ""
