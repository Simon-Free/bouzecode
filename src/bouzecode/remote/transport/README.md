# transport

## Purpose
Acces REST au Rundeck rec (API 40, jeton `RUNDECK_PRIVATE_TOKEN_REC`) et au file share Azure (Shared Key,
`AZURE_PRIVATE_TOKEN_REC`), sans connectorlib (absent du venv bouzecode). Seul l'environnement `rec` est servi.

## Usage
- `settings.charger_reglages()`, `settings.secrets_manquants()`, `settings.nouvel_identifiant_execution()`.
- `ClientRundeck` : `importer_job`, `lancer_job`, `etat_execution`, `journal_execution`, `attendre_fin`, `supprimer_job`.
- `ClientFileShare` : `deposer`, `lire`, `existe`, `lister`, `supprimer_arborescence`.
