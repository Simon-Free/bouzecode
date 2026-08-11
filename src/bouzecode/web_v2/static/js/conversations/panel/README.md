# panel/

## Purpose
Tout ce qui vit à l'intérieur d'un onglet de conversation : le panneau lui-même, le
streaming des blocs, le bloc question/réponse et l'envoi de message.

## Usage
| Fichier | Rôle |
|---------|------|
| `tabs.js` | ouvrir / activer / fermer un onglet, construction du panneau, Ctrl+C |
| `poll.js` | `/blocks` toutes les 1,5 s, placeholder d'état, cadence adaptative |
| `streaming.js` | `/partial` toutes les 250 ms tant que l'agent est `running` |
| `question.js` | AskUserQuestion, validation de plan, reprise après interruption |
| `send.js` | `POST /continue`, avec interruption gracieuse puis reprises bornées sur 409 |
| `meta.js` | ligne meta (badge, modèle, id copiable, branche) et menu « document » |
| `tool_blocks.js` | appariement `tool_call` / `tool_result` (imbrique le résultat dans l'appel) |

Sept fichiers plutôt que cinq : découper davantage séparerait des morceaux qui se
lisent ensemble (`poll` et `streaming` sont les deux moitiés d'un même affichage).
