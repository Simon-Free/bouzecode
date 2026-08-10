"""L'arbre des conversations (/api/agents/tree) : pagination par racines, nature
de chaque conversation, cache aligné sur la cadence de poll, et absence d'effet
de bord destructeur sur une simple lecture.

Aucun mock : on écrit de VRAIS artefacts d'agent et on joue la route HTTP réelle
via le test_client Flask. Les rares seams (process warm, recalcul de l'arbre) sont
espionnées par monkeypatch qui délègue à la vraie implémentation."""
import json
import threading
import time

import pytest


def _write_agent(agents_dir, agent_id, prompt, *, parent=""):
    """Écrit un vrai {id}.json + sidecars. `parent` vide = racine, sinon sous-agent."""
    data = {
        "agent_id": agent_id,
        "prompt": prompt,
        "model": "claude-sonnet",
        "cwd": "",
        "pid": 999_999_999,
        "started_at": f"2026-06-01T10:00:{int(agent_id[-2:]):02d}Z",
        "returncode": 0,
        "session_path": str(agents_dir / f"{agent_id}.session.json"),
        "stdout_path": str(agents_dir / f"{agent_id}.out.log"),
        "ipc_dir": "",
        "parent": parent,
    }
    (agents_dir / f"{agent_id}.json").write_text(json.dumps(data), encoding="utf-8")
    (agents_dir / f"{agent_id}.session.json").write_text(
        json.dumps({"messages": []}), encoding="utf-8"
    )
    (agents_dir / f"{agent_id}.out.log").write_text("log", encoding="utf-8")


@pytest.fixture()
def agents_dir(tmp_path, monkeypatch):
    """Deux conversations racines : « alpha » avec un sous-agent et un petit-fils,
    « bravo » avec un sous-agent. Soit 5 agents pour 2 racines."""
    from bouzecode.web_v2.runtime import runner
    from bouzecode.web_v2.services.sessions import purge
    from bouzecode.web_v2.services.work import fleet, warm_pool

    d = tmp_path / "web_agents"
    d.mkdir()
    monkeypatch.setattr(runner, "AGENTS_DIR", d)
    monkeypatch.setattr(purge, "TRASH_DIR", d / "_trash")
    monkeypatch.setattr(purge, "DELETED_PATH", d / "deleted_sessions.json")
    # Le cache d'arbre est un global de module : on repart d'une ardoise propre.
    fleet.clear_tree_cache()

    _write_agent(d, "alpha01", "Refondre la page conversations")
    _write_agent(d, "alpha02", "Implémente le backend", parent="alpha01")
    _write_agent(d, "alpha03", "Écris les tests", parent="alpha02")
    _write_agent(d, "bravo01", "Nettoyer les worktrees orphelins",
                 parent="dispatcher:manual")
    _write_agent(d, "bravo02", "Recense les worktrees", parent="bravo01")
    runner._list_agents_cache.clear()
    yield d
    fleet.clear_tree_cache()


@pytest.fixture()
def client(agents_dir):
    from bouzecode.web_v2.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _tree(client, query=""):
    return client.get(f"/api/agents/tree{query}").get_json()


def _keys(payload):
    return {n["key"] for n in payload["nodes"]}


ROOT_KEYS = {"agent/alpha01", "agent/bravo01"}
ALPHA_SUBTREE = {"agent/alpha01", "agent/alpha02", "agent/alpha03"}
BRAVO_SUBTREE = {"agent/bravo01", "agent/bravo02"}


def test_sans_parametres_l_arbre_reste_complet(client):
    """Un appelant qui ne pagine pas reçoit toujours toutes les conversations."""
    payload = _tree(client)
    assert _keys(payload) == ALPHA_SUBTREE | BRAVO_SUBTREE
    assert payload["total_roots"] == 2


def test_total_roots_compte_les_racines_pas_les_sous_agents(client):
    """`total_roots` annonce le nombre de managers, pas le nombre d'agents."""
    assert _tree(client)["total_roots"] == 2


def test_une_page_sert_une_racine_avec_tous_ses_sous_agents(client):
    """`limit=1` sert UN manager, mais entier : ses sous-agents viennent avec lui."""
    served = _keys(_tree(client, "?offset=0&limit=1"))
    assert served in (ALPHA_SUBTREE, BRAVO_SUBTREE)


def test_la_page_suivante_sert_l_autre_racine(client):
    """`offset` fait avancer d'un manager : la 2e page sert l'autre conversation."""
    first = _keys(_tree(client, "?offset=0&limit=1"))
    second = _keys(_tree(client, "?offset=1&limit=1"))
    assert first != second
    assert first | second == ALPHA_SUBTREE | BRAVO_SUBTREE


def test_une_page_assez_large_sert_tout(client):
    """Demander plus de racines qu'il n'en existe sert simplement tout l'arbre."""
    payload = _tree(client, "?offset=0&limit=50")
    assert _keys(payload) == ALPHA_SUBTREE | BRAVO_SUBTREE
    assert payload["total_roots"] == 2


def test_un_offset_au_dela_du_dernier_manager_ne_sert_rien(client):
    """Passé la dernière racine, la page est vide — le scroll infini s'arrête."""
    payload = _tree(client, "?offset=9&limit=12")
    assert payload["nodes"] == []
    assert payload["total_roots"] == 2


def test_chaque_conversation_porte_sa_nature(client):
    """Chaque node annonce sa catégorie : conversation user, méta-agent, sous-agent."""
    categories = {n["key"]: n["category"] for n in _tree(client)["nodes"]}
    assert categories["agent/alpha01"] == "user"
    assert categories["agent/bravo01"] == "meta"
    assert categories["agent/alpha02"] == "subagent"


def test_deux_polls_rapproches_ne_recalculent_l_arbre_qu_une_fois(client, monkeypatch):
    """Le cache tient plus longtemps que la cadence de poll de la page : deux
    lectures rapprochées ne repaient pas le calcul complet de l'arbre."""
    from bouzecode.web_v2.services.work import fleet, warm_pool

    recomputes = []
    vraie_construction = fleet._agent_tree_uncached

    def _compte_et_delegue(*args, **kwargs):
        recomputes.append(args)
        return vraie_construction(*args, **kwargs)

    monkeypatch.setattr(fleet, "_agent_tree_uncached", _compte_et_delegue)

    premier = _tree(client, "?offset=0&limit=12")
    second = _tree(client, "?offset=0&limit=12")

    assert len(recomputes) == 1
    assert _keys(premier) == _keys(second)


def test_un_arbre_perime_est_servi_sans_attendre_son_recalcul(client, monkeypatch):
    """Passé le délai de fraîcheur, la page reçoit AUSSITÔT la dernière version connue :
    le recalcul (2,2 s à 9,45 s sur le parc réel) se fait en fond, jamais dans l'attente
    de l'utilisateur."""
    from bouzecode.web_v2.services.work import fleet, fleet_cache, warm_pool

    # Fraîcheur déjà expirée au moment où la 1re version est mémorisée : la 2e lecture
    # tombera donc sur une entrée périmée, la situation qu'on veut observer.
    monkeypatch.setattr(fleet_cache, "TTL_SECONDS", -1)
    premier = _tree(client, "?offset=0&limit=12")

    recalcul_demarre = threading.Event()
    laisser_finir = threading.Event()

    def _recalcul_qui_traine(*args, **kwargs):
        recalcul_demarre.set()
        laisser_finir.wait(timeout=5)
        return {"nodes": [], "total_roots": 0}

    monkeypatch.setattr(fleet, "_agent_tree_uncached", _recalcul_qui_traine)

    debut = time.monotonic()
    perime = _tree(client, "?offset=0&limit=12")
    attente = time.monotonic() - debut

    assert _keys(perime) == _keys(premier)  # la version connue, pas une page vide
    assert attente < 1.0  # servie sans attendre le recalcul qui traîne
    assert recalcul_demarre.wait(timeout=5)  # le recalcul a bien été lancé, en fond
    laisser_finir.set()


def test_lire_l_arbre_ne_tue_aucun_process(client, monkeypatch):
    """Consulter la liste des conversations n'évince rien : une lecture HTTP ne
    doit jamais tuer un agent, même quand le warm-pool déborde."""
    from bouzecode.web_v2.runtime import runner
    from bouzecode.web_v2.services.work import fleet, warm_pool

    tues = []
    monkeypatch.setattr(runner, "is_warm", lambda agent: True)
    monkeypatch.setattr(runner, "kill_agent", lambda agent: tues.append(agent.agent_id))
    monkeypatch.setattr(warm_pool, "WARM_POOL_MAX", 1)  # 5 agents warm → le pool déborde

    _tree(client)

    assert tues == []


def test_le_menage_du_warm_pool_reste_disponible_a_la_demande(agents_dir, monkeypatch):
    """Sorti de la lecture, le ménage du warm-pool s'appelle explicitement et
    évince bien les process idle en trop."""
    from bouzecode.web_v2.runtime import runner
    from bouzecode.web_v2.services.work import fleet, warm_pool
    from bouzecode.web_v2.tests.production_isolation import autoriser_la_destruction

    tues = []
    autoriser_la_destruction(monkeypatch)  # le balayage est inerte sous pytest
    monkeypatch.setattr(runner, "is_warm", lambda agent: True)
    monkeypatch.setattr(runner, "kill_agent", lambda agent: tues.append(agent.agent_id))
    monkeypatch.setattr(warm_pool, "WARM_POOL_MAX", 1)

    evinces = fleet.sweep_warm_pool()

    assert tues  # les agents terminés en trop sont libérés
    assert set(evinces) == set(tues)


def test_un_echec_d_eviction_n_empeche_pas_les_autres(agents_dir, monkeypatch):
    """Un process impossible à tuer est tracé, pas avalé, et les autres évictions
    ont quand même lieu.

    Le refus RÉELLEMENT observé en production est `psutil.AccessDenied`, qui dérive de
    `psutil.Error(Exception)` et NON d'`OSError` : attrapé par le mauvais type, il
    remontait et avortait la boucle ENTIÈRE — une seule éviction refusée et plus aucun
    agent en trop n'était évincé. C'est pourquoi le refus est ici jeté sur le PREMIER
    agent balayé, et qu'on vérifie que TOUS les suivants ont bien été tentés."""
    import psutil

    from bouzecode.web_v2.runtime import runner
    from bouzecode.web_v2.services.work import fleet, warm_pool
    from bouzecode.web_v2.tests.production_isolation import autoriser_la_destruction

    tentatives, tues = [], []

    def _kill(agent):
        tentatives.append(agent.agent_id)
        if len(tentatives) == 1:
            raise psutil.AccessDenied(pid=agent.pid)
        tues.append(agent.agent_id)

    autoriser_la_destruction(monkeypatch)  # le balayage est inerte sous pytest
    monkeypatch.setattr(runner, "is_warm", lambda agent: True)
    monkeypatch.setattr(runner, "kill_agent", _kill)
    monkeypatch.setattr(warm_pool, "WARM_POOL_MAX", 0)  # tout le monde est en trop

    evinces = fleet.sweep_warm_pool()

    assert len(tentatives) == 5, "la boucle d'éviction s'est arrêtée au premier refus"
    assert tentatives[0] not in evinces
    assert set(evinces) == set(tues) == set(tentatives[1:])
