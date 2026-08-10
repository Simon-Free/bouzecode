# [desc] Le nom affiché d'un agent dans la flotte : son sujet, ou son rôle. [/desc]
"""Ce que l'utilisateur lit sur un noeud de la flotte (barre latérale et onglets).

Une conversation qu'il a lancée doit s'annoncer par SON SUJET — la première ligne
de sa demande — et non par « Agent » partout ni par le nom d'un profil de projet, qui
ne lui dit rien. Un agent structurel (validateur, merge...) s'annonce par son rôle.

Aucune heure n'est cuite dans le libellé : le front la dérive de `started_at`.
"""
from bouzecode.web_v2.runtime.runner import Agent
from bouzecode.web_v2.services.work import fleet


def _agent(**over):
    base = dict(
        agent_id="a1", prompt="Tu valides le travail…", model="m", cwd="",
        pid=1, started_at="2026-07-06T10:39:00Z",
    )
    base.update(over)
    return Agent(**base)


def test_work_prend_la_premiere_ligne_du_prompt():
    """Une conversation s'affiche sous le sujet demandé, pas sous le profil qui l'exécute."""
    # Le profil (même "coder" ou un profil projet homonyme) N'APPARAÎT PLUS.
    a = _agent(run_kind="work", prompt="Corrige le bug X", profile="coder")
    assert fleet._short_label(a) == "Corrige le bug X"


def test_work_profil_projet_ignore():
    """Le nom d'un profil de projet ne fuite jamais dans le libellé d'une conversation."""
    # Régression du bug rapporté : le nom du profil projet ne doit plus fuiter.
    a = _agent(run_kind="work", prompt="Refais le dashboard", profile="demo-dashboard-refacto")
    assert fleet._short_label(a) == "Refais le dashboard"


def test_work_prompt_vide_donne_agent():
    """Une conversation sans demande lisible retombe sur le libellé neutre « Agent »."""
    a = _agent(run_kind="work", prompt="", profile="coder")
    assert fleet._short_label(a) == "Agent"


def test_work_multiligne_prend_premiere_ligne_non_vide():
    """Une demande commençant par des lignes vides s'annonce par sa première vraie ligne."""
    a = _agent(run_kind="work", prompt="\n  \nPremière vraie ligne\nDeuxième", profile="")
    assert fleet._short_label(a) == "Première vraie ligne"


def test_work_prompt_long_tronque_a_60():
    """Une demande très longue est tronquée pour tenir dans la barre latérale."""
    long = "x" * 100
    a = _agent(run_kind="work", prompt=long, profile="")
    assert fleet._short_label(a) == "x" * 60


def test_validate_affiche_le_role_sans_profil():
    """Un validateur s'annonce par son rôle, « Validateur », pas par son profil."""
    a = _agent(run_kind="validate", profile="coder")
    assert fleet._short_label(a) == "Validateur"


def test_run_kind_inconnu_capitalise():
    """Un rôle d'agent encore inconnu s'affiche tel quel, simplement capitalisé."""
    a = _agent(run_kind="review", profile="")
    assert fleet._short_label(a) == "Review"


def test_node_exposes_liveness(monkeypatch):
    """Chaque noeud de la flotte porte l'état réel de l'agent (en cours, livré, planté)."""
    # Le noeud d'arbre expose l'état de classification DÉRIVÉ DE PREUVES (running/
    # delivered/crashed) via le classifieur partagé, câblé sur chaque agent du parc.
    monkeypatch.setattr(fleet.liveness, "classify_agent_run",
                        lambda ticket, run: "delivered-sentinel")
    a = _agent(run_kind="work", profile="coder")
    node = fleet._node(a, {"status": {"state": "finished", "returncode": 0}}, [])
    assert node["liveness"] == "delivered-sentinel"
