# conversations/

## Purpose
Logique de la page `/conversations`, découpée depuis `../conversations.js` (~2 960 lignes).
`../conversations.js` n'est plus que le point d'entrée : il câble la page et lance le
premier rendu. Chargement réel : `<script type="module">` dans `templates/conversations.html`
— tout est module ES, aucune variable globale hormis le hook de debug `window.__convTest`.

## Usage
Ces modules ne s'appellent pas depuis l'extérieur : ils sont importés par le point d'entrée
et entre eux. Les quatre variables réellement globales à la page vivent dans `state.js` et
sont réassignées par des setters — les modules ES interdisent d'affecter un import.

| Fichier | Rôle |
|---------|------|
| `dom.js` | `node()` / `agentId()` — feuille du graphe, ne dépend de rien |
| `state.js` | état partagé : `NODES`, `openTabs`, `activeKey`, `optimisticNodes` |
| `contract.js` | ce que le front lit sur un node de `/api/agents/tree` |
| `badges.js` | tables d'état et de phase (des CLÉS i18n), `effectiveState`, `badge` |
| `activity.js` | ce que l'agent fait, recomposé et TRADUIT depuis les faits servis |
| `search.js` | recherche plein-texte au-dessus de la sidebar |

Les libellés viennent tous de `../i18n/` (`import { t } from "../i18n/index.js"`) : rien
n'est écrit en dur, et rien n'est résolu à l'évaluation du module — sinon une bascule de
langue laisserait le texte figé.

## Subfolders
| Folder | Description |
|--------|-------------|
| `sidebar/` | liste des conversations : chargement, cartes, réconciliation, archivage |
| `panel/` | intérieur d'un onglet : fil, poll, streaming, question, envoi, meta |
| `composer/` | barre de nouvelle conversation, bannières, talonnage du démarrage |
| `recap/` | sous-onglet Récap et rendu des diffs |

## Note sur les cycles d'import
`sidebar/`, `panel/` et `composer/` s'importent mutuellement (une carte ouvre un onglet ;
fermer un onglet rafraîchit la liste). Ces cycles sont sains ici : tous les appels croisés
se font depuis des corps de fonction, jamais à l'évaluation du module, et les `function`
sont hissées. Ne pas introduire d'appel croisé au niveau module.
