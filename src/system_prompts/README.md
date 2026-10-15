# System Prompts — Bouzecode

Ce dossier contient les system prompts chargés par `_embedded_data.py` (via `_load_prompt`)
et assemblés par `context.py > build_system_prompt_parts()`. **C'est la source de vérité** :
ces `.txt` sont lus à l'import, pas de copie ailleurs.

## Architecture en 2 couches

Le system prompt envoyé au modèle est composé de :

1. **Noyau commun** (`01`) — agnostique, partagé par TOUS les agents : identité, cycle de
   vie du contexte, boucle micro, Methodology + todolist, Snippet, parallélisme/DAG,
   WritePlan, skills, exemple de tour, directives générales.
2. **Profil agent** — injecté APRÈS le noyau. Pour l'agent par défaut (agent de code),
   c'est `system_prompt_extra` de `.bouzecode/profiles/default.yaml` (démarche TDD, tests,
   découverte de code, lecture symbol-aware, interdits code). `dispatch.py` l'ajoute au
   noyau **uniquement à `_depth == 0`** (l'agent principal) ; les sous-agents héritent du
   noyau seul et appliquent leur propre profil.

## Fichiers

| Fichier | Description | Injection |
|---------|-------------|-----------|
| `01_main_system_prompt.txt` | Noyau commun (template avec `{tool_examples}`) | Toujours, base partagée |
| `04_windows_platform_hints.txt` | Commandes Windows | Non injecté (les consignes Windows vivent dans la description de Bash, sous Windows seulement) |
| `05_plan_mode.txt` | Instructions Plan Mode | Quand `/plan` est actif |
| `07_tool_examples_xml.txt` | Exemple de tour complet (syntaxe XML) | Substitué dans `{tool_examples}` (Anthropic) |
| `07_tool_examples_json.txt` | Exemple de tour complet (syntaxe JSON natif) | Substitué dans `{tool_examples}` (OpenRouter/DeepSeek) |

## Notes

- `01` est un template : `{tool_examples}` est substitué à l'exécution
  par `build_system_prompt_parts()`. Le bon fichier `07_*` (XML vs JSON) est choisi selon
  le provider du modèle.
- Le profil code ne vit PAS ici mais dans `backend/profiles/builtin/default.yaml`.
- Le contexte de session (date, plateforme, répertoire, branche) n'est PAS dans le préfixe :
  `dispatch.stream` le place en DERNIER (`context.build_session_context`), pour que le préfixe
  outils + noyau + profil reste identique d'un tour et d'un agent à l'autre (cache).
- Une consigne propre à une plateforme s'écrit dans un profil entre `<!-- si:windows -->`
  et `<!-- /si -->` (`profile_extra.filter_platform_blocks`).
- Aucun prompt ne demande au modèle d'écrire son raisonnement en texte (`<thinking>`),
  quel que soit le modèle ou le mode (`--loud` compris) : le thinking passe par l'API
  (`thinking_level.py`).
