// État mutable PARTAGÉ de la page Conversations.
//
// Ces quatre valeurs sont lues par presque tous les modules et réassignées par
// plusieurs d'entre eux. Les regrouper ici évite les cycles d'import : chaque
// module importe `state.js` (qui ne dépend de rien) au lieu d'importer celui qui
// se trouve détenir la variable.
//
// Les `export let` sont des LIENS VIVANTS : un lecteur qui fait
// `import { NODES } from "./state.js"` voit toujours la valeur courante. Seul ce
// module peut réassigner, d'où les setters — c'est une contrainte des modules ES,
// pas une indirection décorative.

// Dernier /api/agents/tree (toutes pages chargées, fusionnées).
export let NODES = [];
export function setNodes(nodes) { NODES = nodes; }

// key -> entry d'onglet { tab, panel, conv, status, poller, … }. Jamais réassignée
// (mutée en place), donc aucun setter nécessaire.
export const openTabs = new Map();

// Clé de l'onglet courant (null = aucun onglet actif).
export let activeKey = null;
export function setActiveKey(key) { activeKey = key; }

// Entrées synthétiques « starting » qui tiennent la place d'un agent demandé mais
// pas encore né. Fusionnées aux NODES au rendu, retirées dès l'arrivée du vrai node.
export let optimisticNodes = [];
export function setOptimisticNodes(nodes) { optimisticNodes = nodes; }
