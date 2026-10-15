# [desc] Dernier état SERVI de chaque agent par l'arbre : source unique de la pastille « en cours » et détecteur des changements d'état d'agent. [/desc]
"""Ce que la page Agents MONTRE, retenu agent par agent.

LE DÉFAUT CORRIGÉ (vérificateur d'invariants des E2E, à chaque passe complète) : la pastille
« en cours » comptait sur SA page d'arbre (l'arbre complet, entrée de `fleet_cache` distincte
de la page paginée servie à la page Agents, chacune rafraîchie en fond à son rythme), puis
gardait ce compte dans une mémoire dont la clé — la génération des écritures de TÂCHES — ne
bouge pas quand un agent change d'état. Mesuré dans le bac à sable : jusqu'à 15 s de « 0 »
pendant qu'un agent était affiché au travail, et « 1 » après qu'il avait fini.

LA RÈGLE. Chaque page servie par `fleet.agent_tree` (n'importe laquelle : paginée ou complète)
est notée ici, nœud par nœud, avec l'instant où elle a été CALCULÉE. Une page plus ancienne que
ce qu'on sait déjà d'un agent ne le fait pas reculer (le cache sert du périmé pendant ses
recalculs). La pastille compte ce registre : c'est, par construction, le dernier `etat` que
l'arbre a montré pour chaque agent — plus deux calculs qui divergent.

Et quand la CLASSE d'un agent change (au travail, attend ta réponse, fini, arrêté…), ou qu'un
agent apparaît ou disparaît, la GÉNÉRATION du parc avance — la boîte et les pastilles la
mettent dans leur clé (`taches_vue.cle_courante`) et se recalculent — et les autres pages
d'arbre sont périmées (`fleet_cache.expire_all`) pour rattraper celle qui a vu le changement.
Passer de « En cours » à « Le modèle lit… » n'est pas un changement de classe : rien n'est
jeté pour si peu. `expire_all` seul ne fait PAS avancer la génération : le réveil le déclenche
à chaque tick (tampon de vivacité des tickets) sans que rien de visible ait changé, et la boîte
serait recalculée pendant la requête des pastilles toutes les 8 s.
"""
from __future__ import annotations

import threading
import time

from . import fleet_cache

#  Ce que la pastille « en cours » compte : les mêmes clés du lexique que la page Agents range
#  « au travail » (`lexique`, SPEC §1.1).
AU_TRAVAIL = frozenset({"running", "thinking", "preparing"})

_lock = threading.Lock()
_vus: dict[str, tuple[float, str]] = {}   # clé du nœud → (calculé à, classe)
_complet_a: float | None = None
_generation = 0


def _classe(etat) -> str:
    return "au_travail" if etat in AU_TRAVAIL else str(etat or "")


def noter(noeuds: list[dict], calcule_a: float, complet: bool) -> bool:
    """Retient l'état des nœuds d'une page d'arbre calculée à `calcule_a` (monotone).

    `complet` : la page contient TOUS les agents — un agent absent n'est plus dans l'arbre.
    Une page paginée ne prouve l'absence que des nœuds servis sur toutes les pages (lancements,
    lancements échoués : clés hors `agent/`). Rend True si une classe a changé."""
    global _complet_a, _generation
    change = False
    with _lock:
        presentes = set()
        for n in noeuds:
            cle = str(n.get("key") or n.get("agent_id") or "")
            if not cle:
                continue
            presentes.add(cle)
            connu = _vus.get(cle)
            if connu is not None and connu[0] > calcule_a:
                continue
            classe = _classe(n.get("etat"))
            #  Un agent jamais vu n'est un changement que si le registre connaissait déjà tout
            #  le parc : le premier remplissage (démarrage, tests) ne périme rien.
            change = change or (connu[1] != classe if connu else _complet_a is not None)
            _vus[cle] = (calcule_a, classe)
        for cle, (vu_a, _) in list(_vus.items()):
            if cle not in presentes and vu_a <= calcule_a and (complet or not cle.startswith("agent/")):
                del _vus[cle]
                change = True
        if complet:
            _complet_a = calcule_a if _complet_a is None else max(_complet_a, calcule_a)
        if change:
            _generation += 1
    if change:
        fleet_cache.expire_all()
    return change


def au_travail() -> int:
    """Nombre d'agents que l'arbre a montrés au travail en dernier."""
    with _lock:
        return sum(1 for _, classe in _vus.values() if classe == "au_travail")


def generation() -> int:
    """Avance à chaque changement de classe, apparition ou disparition d'un agent montré."""
    return _generation


def age_complet() -> float | None:
    """Âge (s) de la dernière page COMPLÈTE notée ; None si aucune."""
    with _lock:
        return None if _complet_a is None else time.monotonic() - _complet_a


def vider() -> None:
    global _complet_a
    with _lock:
        _vus.clear()
        _complet_a = None


fleet_cache.au_vidage(vider)
