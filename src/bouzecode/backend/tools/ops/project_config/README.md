# project_config

## Purpose
Implémente `LoadProjectConfig`, la porte d'entrée d'un projet. Répond l'une de trois
choses selon ce que l'utilisateur a désigné : **projet** (rend ses skills trouvables,
branche ses outils, indique comment parcourir son code), **écarté** (ne repose pas la question, liste ce que le
dossier contient), **inconnu** (liste, puis fait poser la question une seule fois).

Rien n'est deviné : aucun marqueur (`.git`, `.bouzecode/`) ne qualifie un projet.
Le `.bouzecode/` d'un dossier est en revanche toujours branché comme source de
skills quand il existe — « être un projet » et « être équipé » sont deux notions
distinctes. Le briefing ne liste pas les skills : il en donne le nombre et renvoie à
`SkillResearch(query=...)` (recherche par mots-clés), puis `Skill(name=...)`.

## Usage
```python
from bouzecode.backend.tools.ops.project_config import _load_project_config

_load_project_config(r"C:\chemin\vers\le\projet")   # -> texte du briefing

# Signature complète : (path, config=None, cd=False)
_load_project_config(r"C:\autre\depot", config, cd=True)  # briefing + DÉPLACE le process
```

`cd=True` adopte le dossier comme répertoire courant de l'agent, via
`backend.tools.environment.adopt_cwd(root, config, worktree=False)` — le même mécanisme que
`Environment(action='worktree')` : `os.chdir()` dans CE process **plus** un signal IPC `env.json`
pour que le serveur recale le cwd à la reprise (l'agent est un process séparé dont le cwd est fixé
au `Popen`).

Deux garde-fous délibérés :

- `worktree=False` ⇒ `BOUZECODE_WORKTREE_ROOT` n'est **pas** posée. Un projet n'est pas un worktree
  d'agent ; la poser ferait apparaître au tour suivant le contrat « tu travailles dans un worktree
  isolé » alors que l'agent serait dans l'arbre principal du dépôt — un mensonge coûteux.
- `cd` est **opt-in** et n'agit que si le dossier existe. Sans lui, le cwd ne bouge jamais : les
  appels d'exploration (le cas courant) restent gratuits et sans effet de bord.

Raison d'être : `Environment(action='worktree'|'venv')` se base sur le cwd. Un agent qui a spawné
dans le dépôt A et doit travailler dans le dépôt B provisionnait son worktree dans A. `cd=True`
au moment où il ouvre B est le seul point du parcours où il sait déjà que B est le bon dépôt.

Modules internes :

| Module | Rôle |
|--------|------|
| `registry.py` | Situe un chemin : désigné / écarté / inconnu, ses projets enfants, les silences (worktrees, dossier temporaire) |
| `briefing.py` | Met en forme ce qu'un dossier équipé apporte — nombre de skills, outils branchés, indice Code |
