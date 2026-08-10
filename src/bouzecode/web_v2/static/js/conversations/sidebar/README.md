# sidebar/

## Purpose
La liste de gauche : chargement paginé de `/api/agents/tree`, rendu KEYÉ des cartes
(chaque `n.key` garde la même instance DOM entre deux refresh) et archivage.

## Usage
| Fichier | Rôle |
|---------|------|
| `list.js` | pagination, garde anti-render pendant une interaction, `refreshList` (8 s) |
| `render_list.js` | racines, entrées fantômes, sectionnement par état → `renderList` |
| `reconcile.js` | place groupes et sections par `insertBefore`, ne retire que le delta |
| `group.js` | registres DOM persistants + `createGroup` |
| `group_update.js` | mise à jour in-place d'une carte (badge, chip d'activité, meta) |
| `toggles.js` | état déplié/replié persisté, `childrenOf`, libellés agrégés |
| `archive.js` | archivage du sous-arbre derrière un décompte de 3 s annulable |

Sept fichiers plutôt que cinq : ce sont sept responsabilités distinctes de moins de
210 lignes chacune. Les regrouper pour tenir un quota rendrait les fichiers plus gros
sans rendre le dossier plus lisible.
