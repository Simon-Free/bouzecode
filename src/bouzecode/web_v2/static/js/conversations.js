// [desc] Point d'entrée de la page Agents (/conversations) : câble la liste, la recherche, les onglets et la barre de lancement. Toute la logique vit dans ./conversations/ (voir son README.md). [/desc]
//
// SPEC.md §5. Aucune maintenance silencieuse au chargement (R11) : cette page n'archive ni ne
// purge plus rien d'elle-même.

import { startList, setActive } from "./conversations/list.js";
import { wireSearch } from "./conversations/search.js";
import { initTabs, restoreTabs } from "./conversations/tabs.js";
import { wireLauncher } from "./conversations/launcher.js";
import { on } from "./conversations/store.js";

initTabs();
on("tabs", ({ active, keys }) => setActive(active, keys));
wireSearch();
wireLauncher();
startList();
restoreTabs();
