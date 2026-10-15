# conversations/

## Purpose
Logique de la page Agents (`/conversations`, SPEC.md §5). `../conversations.js` n'est que le
point d'entrée : il câble la liste, la recherche, les onglets et la barre de lancement. Tout
est module ES ; les échanges entre modules passent par le bus de `store.js` (`emit`/`on`),
pas par des imports croisés.

Règles de la page (SPEC §2) : tout appel réseau passe par `lib/ui.js::api`, tout bouton
d'action par `ui.busy`, tout rafraîchissement par `lib/poll.js::poller`. Aucune maintenance
silencieuse au chargement, aucune interruption d'agent sans geste explicite.

## Usage
| Fichier | Rôle |
|---------|------|
| `model.js` | logique PURE : état d'un nœud, arbre, groupes, filtre, étapes de lancement, mode du champ de message |
| `store.js` | état partagé (nœuds de l'arbre, archivés, clés masquées) et bus d'événements (`open`, `tree`, `tabs`, `render`, `refresh-tree`, `reload-tree`, `archives-changed`) |
| `memory.js` | préférences mémorisées localement (dépôt, profil, environnement, onglets, groupes repliés) |
| `actions.js` | gestes partagés liste / panneau : archiver (+ Annuler), restaurer, copier |
| `list.js` | colonne gauche : `/api/agents/tree`, groupes À traiter / En cours / Terminés / Archivés, « Afficher plus » |
| `list_card.js` | une carte d'agent (rendu keyé), ses sous-agents repliables et son menu ⋯ |
| `search.js` | filtre instantané + recherche plein texte (`/api/search`) |
| `tabs.js` | barre d'onglets, activation/fermeture au clavier, rebranchement `launching/<t>` → `agent/<id>`, onglets mémorisés, `?agent=` |
| `launcher.js` | barre « nouvelle conversation » avec chips dépôt / profil / environnement |

Tests : `tests/js/agents.*.test.js` (comportements vus par l'utilisateur, fetch simulé) et
`tests/e2e_sandbox/test_agents_*.py` (navigateur réel sur le bac à sable).

## Subfolders
| Folder | Description |
|--------|-------------|
| `panel/` | intérieur d'un onglet : en-tête et actions, fil, streaming, question, champ de message et file d'attente, vues Récap / Fichiers / Coûts |
