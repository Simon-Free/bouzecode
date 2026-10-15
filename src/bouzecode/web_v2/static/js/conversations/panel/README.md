# panel/

## Purpose
Tout ce qui vit dans le panneau d'un agent ouvert.

## Usage
| Fichier | Rôle |
|---------|------|
| `panel.js` | construit le panneau, onglets de vue Fil / Récap / Fichiers modifiés / Coûts & tours |
| `header.js` | état, titre, dépôt/branche/tâche, boutons selon l'état, menu ⋯ |
| `header_actions.js` | gestes Continuer, Relancer, Arrêter, Forcer l'arrêt, Réessayer le lancement |
| `thread.js` | `/blocks` (rapide si actif et vivant), onglet de lancement, « ↓ Nouveaux messages », introuvable |
| `thread_view.js` | encarts d'état du fil (étapes de lancement, échec, introuvable, vide, erreur) |
| `streaming.js` | `/partial` token par token quand l'onglet est actif |
| `question.js` | question / plan à valider : options verrouillées au premier clic |
| `composer.js` | champ de message : envoi direct, mise en file si l'agent travaille, reprise, écho |
| `composer_queue.js` | messages en file (Annuler, Interrompre et envoyer) et messages jamais lus (Renvoyer) |
| `recap.js`, `files.js`, `costs.js` | vues Récap, Fichiers modifiés, Coûts & tours (`view_tools.js` : bouton Actualiser) |
| `diff.js`, `diff_highlight.js` | diff côte à côte hors ligne et coloration syntaxique légère |
