# testd

## Purpose
Démon de tests unique par utilisateur, derrière `RunPythonTest` : file d'attente admise sur un budget
de 8 workers pour la machine (≤ 4 par job, `-n` choisi par job, durées mesurées, plus longs
d'abord), tests navigateur séparés et branchés sur un
navigateur chaud partagé, serveur applicatif chaud par worktree (opt-in), état consultable par
le modèle (`TestStatus`). Dossier : `~/.bouzecode/testd/` (`daemon.json`, `daemon.log`, `jobs/`).

## Usage
- `RunPythonTest(..., wait=false)` → `job_id` ; `TestStatus(job_id, wait_s, cancel)` (`rendu.py`).
- `client.soumettre / etat / annuler / arreter_demon` ; le démon démarre à la demande.
- Claude Code : serveur MCP stdio `python -m bouzecode.backend.testd.mcp_server` (`mcp_server.py`),
  mêmes outils et schémas + `cwd` ; cible relative = relative à `cwd` (défaut : cwd du lancement),
  à passer depuis un worktree. Journal `mcp.log` du dossier testd.
- La commande arrive prête (sélection impactée, défauts, plugin d'issues) ; si RunPythonTest le
  demande, la comparaison avec la base tourne dans le créneau du job (`run/job.py`).
- Cibles toutes en fichiers déjà classés (chemin + mtime, `budget/classes.py`) : pas de collecte.
- Collecte bornée (`collecte_s`, 180 s) : au-delà ou en échec, arbre tué et job lancé d'un seul tenant.
- 0 test lancé : verdict de pytest + cause (`-m` des addopts…) + `marker=` qui les lance (`tools/ops/pytest_zero.py`).
- Tests navigateur : au plus `browser_jobs` (2) sous-runs navigateur à la fois sur la machine,
  position d'attente visible (`budget/creneaux.py`). Navigateur chaud servi à la demande à TOUT
  job (`warm/demande.py`, plugin `_bz_pw_patch`) ; un test qu'il a servi classe son fichier
  « navigateur » pour la suite.
- Navigateur (chaud ou vrai lancement du patch) : coquille headless livrée par le Playwright du
  projet si installée, Edge système sinon (dit dans les notes) ; un navigateur lancé par le patch
  est tué à sa fermeture (`plugin/_bz_pw_lancement.py`).
- Worktree neuf : dès la soumission, ses fichiers suivis puis les paquets importés du venv sont
  lus en arrière-plan (antivirus payé d'avance), une fois par (dossier, HEAD) (`warm/prechauffage.py`).
- Délai par test : 30 s, 60 s navigateur, ≥ 300 s si `impacted.slow` ou marqueur `slow` (`timeouts.per_test` / `per_test_browser` de `tests.yaml`, 0 coupe, `garde/limites.py`) ; au-delà, sous-run tué, pile
  faulthandler dans le rapport (`garde/bloque.py`).
- Réglages : `config.json` du dossier ou `BZ_TESTD_WORKERS_TOTAL|BROWSER_SLOTS|BROWSER_JOBS|IDLE_S|COLLECTE_S`,
  `BZ_TESTD_HOME`, `BZ_TESTD_BROWSER_CHANNEL` ; `BZ_TESTD=0` coupe le démon.
- `.bouzecode/tests.yaml` : `browser.marker`, `app_server` (exige `test_equivalent: true`).

## Subfolders
| Folder | Description |
|--------|-------------|
| `run/` | Job, file d'attente, collecte navigateur / hors navigateur |
| `budget/` | Budget de workers (charge RAM/CPU), durées des tests, choix du `-n`, classement des fichiers |
| `warm/` | Navigateur chaud (`playwright launch-server`), serveur applicatif, préchauffage des worktrees |
| `plugin/` | Plugins pytest injectés : séparation, événements de progression, navigateur chaud (`_bz_pw_patch`) |
| `garde/` | Délai par test pendant un sous-run |

## Réserve d'interpréteurs (non construite)
Idée : un pytest déjà démarré par (venv, projet), imports lourds faits, remis au job suivant.
Pas simple, donc pas commencé : Windows n'a pas de `fork`, un interpréteur ne se clone pas ;
il faudrait un serveur pytest qui reçoit la commande (cwd, env, `-p`, cibles), alors que l'env
de chaque job diffère (PYTHONPATH du plugin, `BZ_*`, serveur applicatif) et que xdist lance ses
propres workers, eux aussi froids. Un module importé d'avance masquerait aussi les changements
du worktree (code d'un autre commit). À reprendre seulement si les imports dominent encore une
fois le préchauffage en place : sous-run sans xdist, env identique, invalidé au changement de HEAD.
