# [desc] Un sous-agent ne reste pas chaud : le quart d'heure est pour l'utilisateur, qui n'en a pas. [/desc]
"""Décision utilisateur : on garde les agents chauds 15 min après la dernière interaction,
pour laisser à l'utilisateur le temps de revenir — et SEULEMENT les agents, pas les
sous-agents.

Elle n'était appliquée nulle part. `_web_keep_warm` rendait True pour tout agent web, la
parenté n'étant même pas transmise au process ; et `decide_evictions` ne regardait la
parenté que pour l'immunité des parents. Les douze sous-agents d'un manager tenaient donc
douze process (89 à 687 Mo chacun) et douze slots de warm-pool, au détriment des
conversations où quelqu'un revient vraiment.

La règle est tenue AUX DEUX BOUTS : à la source (le process ne reste pas résident) et à
l'éviction (les sous-agents déjà chauds sont récupérés). Une politique qui ne tient qu'à un
seul point de câblage cesse de s'appliquer en silence le jour où ce point change.
"""
from datetime import datetime, timezone

import pytest

from bouzecode.web_v2.runtime import warmpool

MAINTENANT = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)
RECENT = "2026-07-30T11:59:30+00:00"  # 30 s : très en deçà du quart d'heure


def _noeud(agent_id, *, parent="", state="finished", warm=True, activite=RECENT):
    return {"agent_id": agent_id, "parent": parent, "state": state,
            "warm": warm, "last_activity": activite}


def test_un_sous_agent_termine_est_evince_sans_attendre_le_quart_d_heure():
    """Il vient de finir (30 s), donc la TTL ne le touche pas — c'est sa PARENTÉ qui le sort."""
    noeuds = [_noeud("manager0001"), _noeud("sousagent01", parent="manager0001")]
    assert warmpool.decide_evictions(noeuds, MAINTENANT, max_pool=10) == ["sousagent01"]


def test_l_agent_racine_garde_bien_son_quart_d_heure():
    """Le contre-exemple qui donne son sens au test précédent : une conversation
    d'utilisateur reste chaude, c'est exactement ce à quoi sert la résidence."""
    noeuds = [_noeud("racine00001")]
    assert warmpool.decide_evictions(noeuds, MAINTENANT, max_pool=10) == []


def test_un_sous_agent_qui_TRAVAILLE_n_est_pas_tue():
    """On ne récupère que ce qui a fini. Tuer un sous-agent en plein tour perdrait son travail."""
    noeuds = [_noeud("manager0001"),
              _noeud("sousagent01", parent="manager0001", state="running")]
    assert warmpool.decide_evictions(noeuds, MAINTENANT, max_pool=10) == []


def test_un_sous_agent_qui_attend_une_reponse_n_est_pas_tue():
    """`awaiting_input` est un état ACTIF : quelqu'un lui doit une réponse."""
    noeuds = [_noeud("manager0001"),
              _noeud("sousagent01", parent="manager0001", state="awaiting_input")]
    assert warmpool.decide_evictions(noeuds, MAINTENANT, max_pool=10) == []


def test_un_sous_manager_dont_les_enfants_travaillent_survit():
    """Cas limite qui justifie `active_recursive` plutôt qu'un simple test d'état : ce nœud
    a fini son propre tour mais reste le parent d'un agent vivant. Le tuer orphelinerait un
    sous-arbre actif."""
    noeuds = [
        _noeud("racine00001"),
        _noeud("sousmanager1", parent="racine00001", state="finished"),
        _noeud("petitfils01", parent="sousmanager1", state="running"),
    ]
    assert warmpool.decide_evictions(noeuds, MAINTENANT, max_pool=10) == []


def test_la_ttl_de_quinze_minutes_reste_la_regle_pour_les_racines():
    """La décision porte sur QUI reste chaud, pas sur COMBIEN de temps : 15 min inchangé."""
    assert warmpool.DEFAULT_TTL_SECONDS == 900
    vieux = _noeud("racine00001", activite="2026-07-30T11:44:00+00:00")  # 16 min
    assert warmpool.decide_evictions([vieux], MAINTENANT, max_pool=10) == ["racine00001"]


def test_le_process_d_un_sous_agent_ne_reste_pas_resident(monkeypatch):
    """L'autre bout de la règle : le sous-agent ne devient même pas chaud.

    Le process ne connaît pas sa parenté — seul le serveur la connaît — d'où l'env
    `BOUZECODE_PARENT`. Sans elle, `_web_keep_warm` gardait TOUT agent web résident."""
    from bouzecode.ui import repl

    config = {"_web_agent_dir": "/agents/x.ipc"}
    monkeypatch.delenv("BOUZECODE_PARENT", raising=False)
    assert repl._web_keep_warm(config) is True, "un agent racine doit rester chaud"
    monkeypatch.setenv("BOUZECODE_PARENT", "manager0001")
    assert repl._web_keep_warm(config) is False, "un sous-agent ne doit PAS rester chaud"


def test_la_parente_est_bien_transmise_au_sous_process():
    """Le maillon qui rend la règle applicable. S'il saute, `_web_keep_warm` ne voit plus
    aucune parenté et TOUS les sous-agents redeviennent résidents — en silence."""
    from bouzecode.web_v2.runtime import runner

    enfant = runner.Agent(agent_id="a" * 12, prompt="p", model="", cwd="", pid=0,
                          started_at="", parent="manager0001")
    racine = runner.Agent(agent_id="b" * 12, prompt="p", model="", cwd="", pid=0,
                          started_at="", parent="")
    assert runner._ticket_env(enfant).get("BOUZECODE_PARENT") == "manager0001"
    assert "BOUZECODE_PARENT" not in runner._ticket_env(racine)


@pytest.mark.parametrize("parent", ["", "manager0001"])
def test_un_agent_deja_froid_n_est_jamais_dans_la_liste(parent):
    """`warm=False` : aucun process à récupérer, rien à évincer — la liste ne doit pas
    enfler de noms qui ne correspondent à aucun process vivant."""
    noeuds = [_noeud("manager0001"), _noeud("agentfroid1", parent=parent, warm=False)]
    assert "agentfroid1" not in warmpool.decide_evictions(noeuds, MAINTENANT, max_pool=10)
