# sondes

## Purpose
Mesures de faisabilite executees sur la VM (resultats dans `docs/specs/rundeck_faisabilite.md`).

## Usage
Embarquer le fichier dans un job `yaml_job(...)` ; sortie `SONDE|<cle>|<json>` dans le journal Rundeck.
- `sonde_vm.py` : OS, Python/uv, disques, reseau sortant, Playwright standard.
- `sonde_navigateur.py` : Node en roue + Chromium npm, ldd, lancement Playwright.
