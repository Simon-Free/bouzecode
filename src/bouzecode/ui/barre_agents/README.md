# barre_agents

## Purpose
Barre des sous-agents sous la saisie du TUI (façon Claude Code) et navigation entre leurs
conversations. Les agents eux-mêmes vivent dans `backend/multi_agent/en_process`.

## Usage
- `installer(state, config)` : appelé par `repl()` en mode interactif ; pose `_tui_agents`,
  `_attente_lot` et `_inbox_pop` sur la config du principal, rend l'`EcranAgents` (ou None).
- `EcranAgents.saisir(invite)` remplace la lecture du REPL ; `attente(fini, noms)` garde la
  saisie ouverte pendant que main attend ses enfants. Au repos, une question de sous-agent
  remontée à main (`en_process/questions.py`) ferme l'invite (saisie vide seulement) et
  devient un tour de main.
- `AIDE` : texte affiché par `/help`.

| Fichier | Rôle |
|---|---|
| `rendu.py` | lignes de la barre (texte pur, testé) |
| `defilement.py` | défilement horizontal d'une ligne trop large, fonction du temps (pur, testé) |
| `clavier.py` | `Navigation` (logique pure) + touches prompt_toolkit |
| `vue.py` | conversation rejouée d'un agent (main ou sous-agent) à chaque bascule de vue, question en attente, réponse tapée (refusée si déjà prise) |
| `ecran.py` | session prompt_toolkit, suivi en direct (même rendu que le rejeu : `ui/deroule.py`), routage de la saisie |
