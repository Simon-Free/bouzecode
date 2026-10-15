# runtime/runner/

## Purpose
Cycle de vie des process d'agents `bouzecode` lancés par le serveur web_v2 : fiche
persistée, spawn, reprises chaude et froide, constat de fin, arrêt. Ex-`runtime/runner.py`
(1515 lignes), découpé par responsabilité sans changement de comportement.

## Usage
Importer le module qui PORTE le nom (`from ...runtime.runner import agent_registre`) et
l'appeler par attribut (`agent_registre.list_agents()`). Le paquet ne ré-exporte rien : un test
patche le module propriétaire (`monkeypatch.setattr(agent_fiche, "AGENTS_DIR", …)`), et les
modules du paquet s'appellent entre eux par attribut pour que ces patchs les atteignent aussi.

| Module | Rôle | Noms publics |
|--------|------|--------------|
| `agent_fiche` | dataclass `Agent`, JSON dans `AGENTS_DIR`, écriture atomique, cache de liste invalidé à chaque écriture | `Agent`, `AGENTS_DIR`, `load_agent`, `invalidate_agents_cache` |
| `agent_commande` | ligne de commande, env du process (ticket, venv, PYTHONPATH), clés provider, args de profil | `MANUAL_PARENT`, `DRAPEAUX_DE_SPAWN`, `check_provider_env`, `MissingProviderEnvError` |
| `agent_creation` | premier spawn ; reprise sous un nouvel identifiant | `create_agent`, `resume_agent` |
| `agent_respawn` | relance sur SA session : verrou anti double-spawn, cwd de repli, signal d'environnement | `_respawn` |
| `agent_reprise` | message, réponse à une question, échec d'une vérification différée | `continue_agent`, `resume_pending_agent`, `resume_deferred_agent`, `RESUME_PROMPT` |
| `agent_chaud` | dialogue avec un process vivant (boîte, answer.txt), états warm / mid-turn | `is_warm`, `is_mid_turn` |
| `agent_etat` | état IPC (cache par mtime), code de retour, constat de fin | `get_ipc_state`, `refresh_agent_status` |
| `agent_registre` | liste du parc (cache TTL single-flight), réconciliation au démarrage | `list_agents`, `reconcile_dead_agents` |
| `agent_vivacite` | pid disparu / recyclé / zombie | `processus_absent`, `is_running`, `ZOMBIE` |
| `agent_processus` | process d'une session par cmdline, preuve d'identité d'un pid | `session_process_running`, `pid_still_belongs_to` |
| `agent_arret` | kill, cancel doux, reap des jumeaux, garde `destruction_permitted` | `kill_agent`, `graceful_cancel_agent`, `terminate_agent_process`, `reap_session_processes` |

Dépendances (sans cycle) : `agent_fiche` ← tous ; `agent_commande`, `agent_vivacite`,
`agent_processus` → `agent_respawn` → `agent_etat` → `agent_chaud` → `agent_reprise`,
`agent_arret` ; `agent_registre` lit `agent_etat`.

⚠️ `agent_commande` calcule des chemins en `parents[N]` depuis son propre emplacement
(`parents[4]` = `src`, `parents[5]` = racine du dépôt) : tout déplacement du fichier les décale.
