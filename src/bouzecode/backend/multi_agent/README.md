# multi_agent

## Purpose
Sous-agents : l'outil `Agent` et ses voisins (MessageAgent, SendMessage, CheckAgentResult,
ListAgentTasks, ListAgentTypes, Fleet), les quatre chemins de lancement (TUI en process, fenêtre
de terminal, ticket web gouverné, thread du `SubAgentManager`) et la relecture des enfants.

## Usage
| Module | Rôle |
|---|---|
| `tools.py` | enregistre les 7 outils dans `core.tool_registry` (importé par `tools/registration.py`) |
| `schema_agent.py`, `schemas.py` | schémas JSON exposés au modèle (`Agent` ; les six autres) |
| `outil_agent.py` | `_agent_tool` : garde-fous puis aiguillage TUI / terminal / web / thread |
| `appel_agent.py` | lu par tous les chemins : `_attend_l_enfant` (pause ou fond), refus manager→type générique, refus hors process sous `_tool_gate` |
| `lancement_terminal.py` | `_spawn_terminal_agent` (fenêtre `-p --result-file`, suivi par `surveillance_terminal`) |
| `lancement_web.py` | `_spawn_web_ticket_agent` : crée le ticket (`client_tickets`), rend les refus en `Error:`, attend ou rend la main |
| `attente_web.py` | `_wait_for_child`, `AttenteInterrompue`, sondage réveillable (`_reveil`, `_dormir`) |
| `travail_non_commite.py` | prévient parent et enfant des fichiers non commités du parent |
| `outils_enfants.py` | MessageAgent, SendMessage, CheckAgentResult (attente, arrêt), ListAgentTasks |
| `outils_flotte.py` | Fleet (lister / tuer), ListAgentTypes |
| `enfants.py` | mes enfants vus par le serveur + garde-fous (clôture, destruction) |
| `client_tickets.py` | routes tickets du serveur local (`_sur_le_serveur` suit `BOUZECODE_WEB_BASE_URL`) |
| `gestionnaire.py` | `get_agent_manager()`, singleton du `SubAgentManager` (`manager.py`, `task.py`) |
| `profondeur.py` | profondeur bornée (`max_agent_depth`) et isolation demandée |
| `terminal.py`, `surveillance_terminal.py`, `resultat_terminal.py` | lanceur de fenêtre, suivi par PID, lecture du résultat |
| `plugin_resolver.py` | plugins requis par un profil d'agent |

Tests : remplacer une fonction dans le module qui la PORTE (`gestionnaire.get_agent_manager`,
`outil_agent._is_terminal_mode`, `lancement_terminal._TERMINAL_WAIT_TIMEOUT`…) ; les appelants
l'importent dans leurs fonctions, donc à l'appel.

## Subfolders
| Folder | Description |
|--------|-------------|
| `en_process/` | sous-agents du TUI dans le même process, visibles dans la barre du bas |
