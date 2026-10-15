# [desc] Pastilles de navigation contre un vrai serveur : « à moi » = la boîte, « en cours » = la page Agents, aussitôt après un changement d'état d'agent sans écriture de tâche. [/desc]
"""Le vérificateur d'invariants ne faisait qu'AVERTIR (« données héritées ») d'un écart que
chaque passe complète montrait : `nav a_moi=8 ≠ boîte 9`, `nav en_cours=0 ≠ agents affichés au
travail [...]`. Ce test, lui, ÉCHOUE : un agent libre pose une question (son process l'écrit,
aucune tâche ne change), et dès que la page Agents le montre, la boîte, la pastille « à moi »
et la pastille « en cours » doivent le dire aussi — pas 15 à 30 s plus tard.

Étanche : le bac est partagé, on ne compare jamais à un total attendu, seulement la pastille à
la page qu'elle résume, lue juste avant elle (comme le navigateur les montre côte à côte)."""
from __future__ import annotations

import time

import pytest

from bureau_e2e_support import BASE, DEPOT, MARQUES, api, attendre, uid  # noqa: F401

pytestmark = [*MARQUES, pytest.mark.couvre(
    "routes/work/inbox.py",
    "services/work/inbox.py",
    "services/work/taches_vue.py",
    "services/work/fleet.py",
    "services/work/fleet_cache.py",
    "services/work/fleet_vue.py",
    "services/work/bureau_lignes.py",
)]

AU_TRAVAIL = {"running", "thinking", "preparing"}
#  Délai accordé après que la page Agents a montré le changement : une seconde (la boîte et
#  les pastilles sont invalidées par le changement lui-même), pas la mémoire de 3 à 30 s d'avant.
DELAI = 1.0


def _page_agents() -> list[dict]:
    return api("GET", "/api/agents/tree?offset=0&limit=500").get("nodes") or []


def _en_cours_coherent() -> tuple | None:
    noeuds = _page_agents()
    montres = sorted(n.get("agent_id") or n.get("key") for n in noeuds if n.get("etat") in AU_TRAVAIL)
    nav = api("GET", "/api/nav/counts")
    return (nav["en_cours"], montres) if nav["en_cours"] == len(montres) else None


def _a_moi_coherent(agent_id: str) -> tuple | None:
    boite = api("GET", "/api/inbox")
    nav = api("GET", "/api/nav/counts")
    ids = {c.get("agent_id") for c in boite.get("items") or []}
    return (nav["a_moi"], boite["compte"]) if agent_id in ids and nav["a_moi"] == boite["compte"] else None


def test_une_question_d_agent_libre_arrive_aussitot_dans_les_pastilles():
    """Dès que la boîte montre la question, « à moi » la compte ; dès que la page Agents montre
    l'agent en attente (il ne travaille plus), « en cours » le décompte."""
    titre = uid("Pastille")
    api("POST", f"/api/projects/{DEPOT}/tickets", {"title": "e2e", "prompt": f"{titre}\n[scn:question]",
                                  "typology": "default", "defer": False}, attendu=201)

    def question_dans_la_boite():
        for c in api("GET", "/api/inbox").get("items") or []:
            if c.get("type") == "question" and titre in str(c.get("titre") or ""):
                return c
        return None

    carte = attendre(question_dans_la_boite, delai=90, pas=0.2,
                     message=f"question de « {titre} » dans la boîte")
    attendre(lambda: _a_moi_coherent(carte["agent_id"]), delai=DELAI, pas=0.2,
             message="« à moi » = compte de la boîte qui montre la question")

    def question_montree():
        return any(n.get("agent_id") == carte["agent_id"] and n.get("etat") == "awaiting_input"
                   for n in _page_agents())

    attendre(question_montree, delai=30, pas=0.2, message="agent affiché en attente de réponse")
    attendre(_en_cours_coherent, delai=DELAI, pas=0.2,
             message="« en cours » = agents que la page Agents montre au travail")
