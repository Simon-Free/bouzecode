# vm

## Purpose
Code execute sur la VM (stdlib Python 3.11), embarque en base64 dans le job a usage unique.

## Usage
- `job_template.yaml_job(run_id, {nom: code}, entree, options, description, arguments=...)`.
- `vm_runner.py <paquet> <travail> <resultat>` : reconstruit, execute, depose `resultat.json` (en mode agent : `close_reason`/`close_detail`/`final_answer` lus dans `reponse.cloture.json`, la fiche du CLI), JUnit, captures, bundle.

## Subfolders
| Folder | Description |
|--------|-------------|
| `navigateur/` | Equivalent `playwright install chromium` sans root ni Internet (Ubuntu 18.04) |
| `sondes/` | Sondes de faisabilite (systeme, reseau, navigateur) a relancer si la VM change |
