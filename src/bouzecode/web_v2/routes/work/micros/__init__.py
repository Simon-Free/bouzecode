# [desc] Blueprint `micros_api` : les macro-tâches (chantiers) et les micro-tâches du Bureau — brouillon, précisions, verrou de lancement, gestes d'un passage. Un module par groupe de routes. [/desc]
"""Les routes du modèle cible de `docs/bureau-todo-modele-et-api.md` (§10.1 et §10.2).

Trois règles gouvernent ce module, et elles expliquent tous ses codes d'erreur :

- **La création et le dispatch sont deux actes séparés.** Une micro-tâche naît `brouillon` et
  aucune route d'ici ne la lance : il faut un geste explicite `pret`, puis un second `lancer`.
  `lancer` répond 409 tant que l'état n'est pas `prete` — c'est L'invariant de la spec,
  « rien ne part sans brief ».
- **Une proposition ne s'impose pas.** Une précision écrite en `en_attente_de_validation`
  (retour de clôture d'agent, point ouvert) n'entre PAS dans le prompt de l'agent avant que
  l'humain ne l'ait validée (éventuellement corrigée) ou jetée.
- **Les précisions sont append-only.** On n'écrase jamais un ajout ; on en empile un autre.
  Un retour de livraison insuffisante devient lui aussi une précision, ce qui enrichit le
  brief au lieu de le perdre.
"""
from __future__ import annotations

from flask import Blueprint

micros_bp = Blueprint("micros_api", __name__)

#  Les modules enregistrent leurs routes sur `micros_bp` à l'import.
from . import gestes, lignes_et_chantiers, rendu, taches  # noqa: E402,F401
