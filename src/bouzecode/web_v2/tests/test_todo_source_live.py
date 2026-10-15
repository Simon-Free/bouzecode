"""Le chemin RÉEL de lecture d'une session, celui qui tourne sur le serveur.

Les autres tests de la boucle TODO injectent une source écrite à la main : rapides,
mais ils ne chargent JAMAIS les vrais modules `runner`/`store`, donc un import faux
dans `LiveSource._session` passait vert trois livraisons de suite. Ici on exerce
`todo.LiveSource` elle-même : vrai import, vrai `runner.load_agent`, vrai
`store.load_session_json(Path)`, sur une vraie fiche d'agent et une vraie session
JSON écrites dans un répertoire temporaire. Un import cassé ⇒ ModuleNotFoundError.

Aucun mock : on redirige seulement le registre d'agents (`runner.AGENTS_DIR`) vers
le tmp_path du test, pour ne pas écrire dans le parc de l'utilisateur.
"""

import json
from datetime import datetime

from bouzecode.web_v2.runtime.runner import agent_fiche
from bouzecode.web_v2.services.work import todo_source as todo


def _parc_reel(tmp_path, monkeypatch, agent_id, session_contenu,
               prompt="corriger les doublons OD"):
    """Écrit une fiche d'agent + sa session comme le fait le harnais, et branche
    le registre dessus. Rend l'agent_id prêt à être lu par LiveSource."""
    agents_dir = tmp_path / "web_agents"
    agents_dir.mkdir()
    session_path = tmp_path / "sessions" / f"{agent_id}.json"
    session_path.parent.mkdir(parents=True)
    session_path.write_text(json.dumps(session_contenu), encoding="utf-8")

    fiche = {"agent_id": agent_id, "prompt": prompt,
             "model": "sonnet", "cwd": str(tmp_path), "pid": 0,
             "started_at": datetime.now().isoformat(),
             "finished_at": datetime.now().isoformat(), "returncode": 0,
             "session_path": str(session_path)}
    (agents_dir / f"{agent_id}.json").write_text(json.dumps(fiche),
                                                 encoding="utf-8")
    monkeypatch.setattr(agent_fiche, "AGENTS_DIR", agents_dir)
    return agent_id


def test_la_vraie_lecture_reconnait_une_conversation_de_test(tmp_path, monkeypatch):
    """Chemin RÉEL, sans mock : une fiche d'agent d'essai est écrite sur disque et
    `LiveSource` doit la classer test — sinon elle gonfle la liste des décisions.

    Le critère est celui de la sonnette (`sessions.purge.is_test_agent`) : le titre ou
    la première ligne du prompt commence par « test »."""
    bidon = _parc_reel(tmp_path, monkeypatch, "ag-ping", {"recap": {}},
                       prompt="test PING/PONG : reponds PONG et arrete-toi")
    assert todo.LiveSource().is_test(bidon) is True


def test_la_vraie_lecture_garde_une_conversation_de_travail(tmp_path, monkeypatch):
    """Le filtre ne doit pas manger le vrai travail : un ticket normal reste dedans."""
    vrai = _parc_reel(tmp_path, monkeypatch, "ag-vrai", {"recap": {}})
    assert todo.LiveSource().is_test(vrai) is False


def test_le_recap_vient_de_la_vraie_session_sur_disque(tmp_path, monkeypatch):
    points = [{"texte": "faut-il garder les OD annulees dans le rapprochement ?"}]
    agent_id = _parc_reel(tmp_path, monkeypatch, "ag-live-1", {
        "messages": [], "recap": {"explanation": "doublons dedupliques",
                                  "points_ouverts": points}})

    recap = todo.LiveSource().recap(agent_id)

    assert recap is not None, "le recap de la vraie session n'a pas été lu"
    assert recap["points_ouverts"] == points


def test_un_agent_absent_du_registre_ne_donne_pas_de_recap(tmp_path, monkeypatch):
    agents_dir = tmp_path / "web_agents"
    agents_dir.mkdir()
    monkeypatch.setattr(agent_fiche, "AGENTS_DIR", agents_dir)

    assert todo.LiveSource().recap("ag-jamais-vu") is None


def test_une_session_illisible_ne_donne_pas_de_recap(tmp_path, monkeypatch):
    agent_id = _parc_reel(tmp_path, monkeypatch, "ag-live-2", {"recap": {}})
    session = tmp_path / "sessions" / f"{agent_id}.json"
    session.write_text("{ ceci n'est pas du JSON", encoding="utf-8")

    assert todo.LiveSource().recap(agent_id) is None
