# recap/

## Purpose
Sous-onglet Récap : bascule de vue, chargement de `/api/sessions/<key>/recap` et rendu.
Le front n'ordonne rien — le serveur trie et regroupe, l'affichage suit l'ordre reçu.

## Usage
| Fichier | Rôle |
|---------|------|
| `view.js` | `setView` / `openRecap` / `maybeEnableRecap`, rendu texte et récap agrégé |
| `diff.js` | moteur de diff side-by-side maison (LCS + coloration), repli `<pre>` unifié |

`diff.js` est PUR : aucune dépendance à l'état de la page, et 100 % hors-ligne (aucun
CDN ni Monaco, donc immunisé aux proxys restrictifs).
