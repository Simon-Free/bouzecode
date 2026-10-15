# remote

## Purpose
Faire tourner une tache bouzecode (agent ou suite de tests, Playwright compris) sur une VM Rundeck **rec**
au lieu du poste : paquet git + fichiers non suivis filtres -> file share -> job `BZ_<run_id>` -> resultat.
Spec : `docs/specs/rundeck_execution.md` ; mesures : `docs/specs/rundeck_faisabilite.md`.

## Usage
- `lancer_sur_rundeck(ticket, execution)` -> `{ok, execution_id, url, statut, run_id}` ou `{ok: False, code, message}`.
- `lancer_tests_sur_rundeck(projet, "args pytest", fichiers_non_suivis, chemin=..., navigateur=True)`.
- `suivre(execution_id)` (statut + fin du journal), `recuperer(execution_id)` (JUnit, captures, branche `agent/<ticket>`, nettoyage).

## Subfolders
| Folder | Description |
|--------|-------------|
| `transport/` | Reglages rec et clients REST Rundeck / Azure Files |
| `paquet/` | Construction du paquet de transfert, filtre des fichiers, reimport du bundle resultat |
| `vm/` | Code embarque dans le job et execute sur la VM |
