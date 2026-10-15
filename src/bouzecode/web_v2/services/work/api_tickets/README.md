# services/work/api_tickets/

## Purpose
Services de l'API cible des tickets (spec §5-§6), communs aux routes, aux alias et au Bureau.

## Usage
- `creation.creer` — validation stricte (`validation`), Idempotency-Key, collision 409, lancement
- `execution` — champ `execution` à la création (cible local | rundeck, fichiers non suivis)
- `lancement.lancer` — un run neuf (202, `deja_actif`), isolation du ticket conservée
- `remise.remettre` — LA remise d'un message (livré / mis en file / refus)
- `controle` — interrompre, arrêter, répondre (agent ou ticket)
- `livraison` — `delivery` (fichiers de code en avance), diff, récolte
- `integration_async.integrer` — intégration en fond (202)
- `lectures`, `agents_vue` — lectures pures (listes paginées, fiches, occupation)
- `fin_de_run` — fin d'un run (jeton propre au run) ; `garde` — garde d'environnement unique
- `refus.Refus` — l'erreur métier (code, message, statut, détails)
