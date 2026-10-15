# en_process

## Purpose
Sous-agents du TUI interactif exécutés dans le MÊME process (un fil chacun), visibles dans la
barre du bas (`ui/barre_agents`). Aucun code de terminal ici : tout se teste sans écran.

## Usage
| Élément | Rôle |
|---|---|
| `RegistreAgents` (`registre.py`) | arbre main/enfants, `interrompre` (cascade), `signaler`, `attendre_changement` |
| `CourrierAgents` (`courrier.py`, mêlé au registre) | boîtes aux lettres, `envoyer(id, texte)` (réponse à sa question, file de messages, ou reprise), `poser_question`, `repondre` (la première réponse l'emporte) |
| `questions.py` | la question d'un sous-agent (AskUserQuestion) part aussi à son PARENT (ou au premier ancêtre vivant, main en dernier) : il y répond par `MessageAgent(ticket_id, text, question=N)` ou la relaie par AskUserQuestion ; les permissions restent à l'utilisateur |
| `FicheAgent` (`fiche.py`) | état (▶ ? ✓ ✗ ■), début/fin, question, alertes ; tokens et coût lus sur son `AgentState` |
| `execution.lancer(registre, params, config)` | crée la fiche + la tâche du `SubAgentManager`, démarre le fil (`agent.run`), session écrite dans `daily/<date>/session_*_<id>.json` |
| `agent_tui(params, config)` (`outil.py`) | chemin TUI de l'outil `Agent` : `background=true` rend la main, sinon attente via `config["_attente_lot"]` |
| `message_tui` / `flotte_tui` (`outil.py`) | `MessageAgent` / `Fleet` sur cette flotte (proposés au modèle via `tool_registry.flotte_disponible`) |

Isolation (`outil.preparer_atelier`) : décidée par le parent — `shared` (dossier du parent),
`worktree` / `worktree_venv` (provisionnés comme l'outil Environment) ; chaque enfant porte
son `Atelier` (`core/dossier_agent.py`, contextvar activée par `execute_tool`) : ses outils
résolvent chemins, cwd des process et variables (venv) chez LUI, sans `os.chdir` global.
Impossible = refus explicite (`Error: sous-agent REFUSÉ`), jamais un repli silencieux.
L'atelier est actif pour TOUT le fil de l'enfant (pas seulement ses outils) et porte sa sortie :
stdout/stderr de l'enfant → `~/.bouzecode/logs/sous-agent-<id>.log` (`fiche.journal`,
`core/sortie_agent.py`), et ses LoadProjectConfig restent à lui (`core/paths.py`).

Règles : seul FinalAnswer livre (fin sans FinalAnswer = `Error:` explicite) ; profondeur bornée
par `max_agent_depth` ; `config["subagents_window"] = true` rend l'ancien mode fenêtre.
