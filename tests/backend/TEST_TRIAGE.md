# Triage des tests backend bouzecode

**Inventaire reconstruit sur le disque le 2026-07-27** (branche `develop`). Chaque
fichier cité ci-dessous a été vérifié comme existant, et chaque nombre de tests
recompté par AST. Les chiffres de la version précédente de ce document
(« ~1148 tests », 6 fichiers cités qui n'existaient plus) étaient périmés.

La méthode et la politique à 4 niveaux : `TEST_METHODOLOGY.md`.

**Règle** : un test unitaire n'est supprimé que si un test de conversation couvre
déjà le comportement **et qu'il est vert** (`CUT`). Sinon, on écrit d'abord ce test
(`WRITE_THEN_CUT`). On garde en unitaire ce qui ne peut pas être exercé via une
conversation et qui est load-bearing (`KEEP_UNIT`). **En cas de doute, on garde.**

---

## 1. Où on en est

### Volumétrie réelle

| Périmètre | Fichiers `test_*.py` | Fonctions de test |
|---|---:|---:|
| `tests/` + `src/bouzecode/web_v2/tests/` (toute la suite) | 449 | 2748 |
| `tests/backend/` | 273 | 1705 |

`pytest --collect-only` sur `tests/backend` remonte ~1858 items (l'écart vient des
`@parametrize`). La suite a **plus que doublé** depuis la rédaction initiale de ce
document.

### Indicateurs de qualité (suite complète)

| Indicateur | Valeur | Cible |
|---|---:|---|
| Fichiers pilotant l'agent via `bouzecode()` | 50 / 449 (11 %) | majoritaire |
| Tests avec docstring | 1207 / 2748 (**43 %**) | 100 % |
| Fichiers utilisant `MagicMock` | **16** | 0 |
| Fichiers important un symbole privé | **113** | 0 hors unitaires assumés |
| Fichiers utilisant `mock_api` | 6 | réservé au transport |
| Fichiers Playwright | 1 | **ne pas en ajouter** |

### Les tests de conversation existants (l'ensemble « couverture »)

**50 fichiers, 232 tests** dans `tests/backend`. Les principaux :

| Cluster | Fichiers |
|---|---|
| agent_loop | `e2e/test_e2e_hello.py` (2), `e2e/test_e2e_mock.py` (8), `e2e/test_e2e_token_optimizations.py` (8), `test_close_requires_final_answer.py` (7), `test_empty_turn_continuation_e2e.py` (5), `test_meta_only_continue_e2e.py` (5), `test_final_answer_e2e.py` (3), `test_readonly_nudge.py` (3), `test_swallowed_tooluse_recovery.py` (3), `turn/test_truncated_stream.py` (3) |
| enforcement | `e2e/test_e2e_snippet_coverage.py` (5), `e2e/test_e2e_skill_enforcement.py` (4), `test_enforcement_recovery.py` (2 sur 10), `test_reemit_after_swallowed_batch.py` (3), `test_recovery_best_effort.py` (2), `e2e/test_e2e_plan_rejected_enforcement.py` (1) |
| methodology | `snippet/test_snippet_e2e.py` (16), `test_methodology_tool_e2e.py` (5), `test_methodology_resume.py` (4), `ends_turn/test_meta_only_ends_turn_e2e.py` (3), `cache/test_cache_wire_e2e.py` (2, **mock_api**), `snippet/test_tool_id_snippet_e2e.py` (1) |
| tools | `runner/test_e2e_run_python_test.py` (11), `symbols/test_symbols_e2e.py` (10), `search/test_search_e2e.py` (7), `checkpoint/test_getdiff_e2e.py` (6), `runner/test_run_summary_e2e.py` (2), `test_deferred_flow_e2e.py` (2) |
| multi_agent / plan_mode / skills | `multi_agent/test_task_e2e.py` (11), `skills/test_skills_prompt_e2e.py` (8), `plan_mode/test_plan_enforcement_e2e.py` (7), `plan_mode/test_plan_tools_e2e.py` (5), `plan_mode/ipc/test_write_plan_ipc_e2e.py` (4) |
| sessions / startup / profiles | `sessions/test_session_save_e2e.py` (6), `dag/test_dag_depends_on_e2e.py` (5), `startup/test_auto_load_bouzecode_e2e.py` (4), `profiles/test_profile_loop_flags.py` (4) |
| transport (**mock_api**, lents) | `providers/test_resilience_mock_api_e2e.py` (5), `xml_protocol/test_xml_stream_e2e.py` (5), `providers/test_mock_api_e2e.py` (4), `agent_loop/test_classification_e2e.py` (3), `thinking/test_thinking_stream_e2e.py` (2) |

---

## 2. Ce qui est FAIT

### Triage déjà exécuté (fichiers supprimés, document non mis à jour à l'époque)

Ces fichiers étaient cités par la version précédente de ce document ; ils
n'existent plus. Leur comportement est repris par le test de conversation nommé.

| Fichier supprimé | Repris par |
|---|---|
| `enforcement/test_enforcement_conversation.py` | `enforcement/e2e/*` |
| `enforcement/hooks/test_enforcement_hooks.py` | `enforcement/e2e/test_e2e_skill_enforcement.py` + `e2e/test_e2e_snippet_coverage.py` |
| `enforcement/hooks/test_thinking_enforcement.py` | idem (doublon de `test_enforcement_hooks.py`) |
| `enforcement/hooks/test_enforcement_reinject.py` | idem |
| `enforcement/hooks/test_enforcement_warning.py` | idem |
| `enforcement/hooks/test_enforcement_schema_filtering.py` | `enforcement/test_enforcement_cache_stability.py` |
| `methodology/snippet/test_tool_id_snippet.py` | `methodology/snippet/test_tool_id_snippet_e2e.py` |
| `plan_mode/test_plan_enforcement.py` | `plan_mode/test_plan_enforcement_e2e.py` |
| `sessions/test_session_thinking_bug.py`, `test_session_thinking_preserved.py`, `test_thinking_session_bug.py` | `sessions/test_session_save_e2e.py` |

Le sous-dossier `enforcement/hooks/` a entièrement disparu.
`sessions/test_session_build_data.py` et `test_cmd_clear_context_state.py` existent
toujours mais **à la racine de `tests/`**, pas sous `tests/backend/sessions/` — le
chemin cité était faux.

### Vague du 2026-07-27 — clusters `enforcement/` et `methodology/snippet/`

**Réparations** (29 tests de conversation étaient rouges, tous pour la même cause :
un batch méta-seul ne clôt plus le tour, il faut une réponse texte nue en dernier —
cf. `TEST_METHODOLOGY.md`, gotchas) :
`methodology/snippet/test_snippet_e2e.py`, `methodology/test_methodology_tool_e2e.py`,
`methodology/snippet/test_tool_id_snippet_e2e.py`, `methodology/cache/test_cache_wire_e2e.py`
(passé de 550 s à 5 s : le serveur mock partait en retry), `enforcement/e2e/*`,
`enforcement/test_enforcement_recovery.py`, `enforcement/test_recovery_best_effort.py`.

**Conversions et suppressions** :

| Supprimé | n | Remplacé par |
|---|---:|---|
| `methodology/snippet/test_snippet_tool.py` | 12 | `methodology/snippet/test_snippet_e2e.py` (16, dont `test_snippet_is_journalled_in_the_notes_timeline` écrit pour l'occasion) |
| `enforcement/test_same_batch_snippet.py` | 5 | `enforcement/e2e/test_e2e_snippet_coverage.py` (5, écrit pour l'occasion) |
| moitié « intégration » de `methodology/snippet/test_snippet_tool_fallback.py` | 4 | `test_snippet_e2e.py` (fallback + `test_snippet_on_the_right_path_mentions_no_fallback`) — les 7 tests du matcher pur restent |

Les deux clusters sont à **100 % de docstrings** (51/51 et 44/44), **0 `MagicMock`**,
et `test_snippet_e2e.py` n'importe plus `_read_files` : la précondition « ce fichier
a déjà été lu » est produite par un vrai tour de Read.

---

## 3. Ce qui RESTE

### CUT — supprimable (le test de conversation existe et est vert)

À vérifier une dernière fois cas par cas avant suppression : le nombre de tests de
conversation est parfois inférieur au nombre d'unitaires, ce qui peut cacher un
mode non couvert.

| Fichier | n | Couvert par | n |
|---|---:|---|---:|
| `thinking/test_thinking_save.py` | 6 | `thinking/overflow/test_thinking_save_e2e.py` + `test_thinking_e2e.py` | 3 + 27 |
| `tools/test_edit_compact_result.py` | 5 | `agent_loop/e2e/test_e2e_token_optimizations.py` | 8 |
| `tools/test_gfd_depth.py` | 4 | idem (GFD depth) | 8 |
| `tools/registry/test_tool_truncation.py` | 8 | idem (troncature Bash) | 8 |
| `tools/test_folder_desc.py` | 8 | `tools/symbols/test_symbols_e2e.py` | 10 |
| `tools/symbols/test_symbols.py` | 11 | idem | 10 |
| `tools/symbols/test_symbol_not_found_message.py` | 2 | idem | 10 |
| `methodology/ends_turn/test_meta_only_breaks_loop.py` | 3 | `methodology/ends_turn/test_meta_only_ends_turn_e2e.py` + `agent_loop/test_meta_only_continue_e2e.py` | 3 + 5 |
| `methodology/ends_turn/test_meta_only_ends_turn.py` | 3 | idem | 3 + 5 |
| `methodology/ends_turn/test_methodology_ends_turn_bug.py` | 3 | idem | 3 + 5 |
| `prompts/test_code_discovery_prompt.py` | 1 | `prompts/test_prompt_build_e2e.py` (build_system_prompt exercé par tout e2e) | 1 |
| `prompts/test_system_prompt_format.py` | 1 | idem | 1 |
| `prompts/test_get_memory_context.py` | 2 | idem | 1 |
| `regression/smoke/test_version.py` | 1 | doublon de `regression/smoke/test_version_sync.py` | 1 |

> `methodology/ends_turn/test_meta_only_breaks_loop.py` est aussi le seul fichier
> du cluster methodology à utiliser `MagicMock` — raison de plus de le couper.

### WRITE_THEN_CUT — le test de conversation existe mais ne couvre pas encore tout

| Test de conversation | n | Unitaires à faire tomber | n |
|---|---:|---|---:|
| `skills/test_skills_prompt_e2e.py` | 8 | `skills/test_skills.py` (26), `test_skills_section.py` (4), `test_skill_loading_prompt.py` (2) | 32 |
| `providers/wire/test_minimal_wire.py` | 4 | `providers/wire/test_minimal_payload.py` | 19 |
| `tools/runner/test_e2e_run_python_test.py` | 11 | `tools/runner/test_test_runner_progress.py` | 6 |
| `tools/search/test_search_e2e.py` | 7 | `tools/search/test_gitignore_grep_glob.py` (7), `test_grep_summary.py` (10), `test_shell_ban.py` (9) | 26 |
| `checkpoint/test_getdiff_e2e.py` | 6 | `checkpoint/test_getdiff_revert.py` | 4 |
| `multi_agent/test_task_e2e.py` | 11 | `multi_agent/test_subagent.py` (11), `test_terminal_subagent.py` (10) | 21 |
| `startup/test_auto_load_bouzecode_e2e.py` | 4 | `startup/test_auto_load_bouzecode.py` (4), `test_project_config.py` (11) | 15 |
| `methodology/test_methodology_tool_e2e.py` | 5 | `methodology/test_methodology_tool.py` (12), `test_methodology_append_only.py` (6, invariant append-only load-bearing) | 18 |
| `enforcement/e2e/test_e2e_snippet_coverage.py` | 5 | `methodology/snippet/test_skill_snippet_enforcement.py` (5, mêmes hooks sur des messages forgés) | 5 |
| `profiles/test_profile_loop_flags.py` | 4 | `profiles/test_profiles.py` | 7 |
| `plan_mode/test_plan_tools_e2e.py` | 5 | `plan_mode/test_plan_tools.py` | 6 |

**À écrire de zéro** (aucun test de conversation encore) :

| Test à écrire | Remplacerait |
|---|---|
| **Edit safeguards** : Read → modif externe → Edit (warning), Read→Edit consécutifs, Write→Edit sans re-read | `tools/test_mods.py`, partie file-state (~9 sur 26) — ⚠️ voir la note « warning invisible » de `TEST_METHODOLOGY.md` |
| **System prompt override + routing OpenRouter en conversation** | `providers/dispatch/test_dispatch_system_override.py` (3), `test_dispatch_openrouter_routing.py` (3), `test_dispatch_inject.py` (4) |
| **Sanitisation des noms d'outil + inputs manquants sur le fil** (niveau `mock_api`) | `providers/wire/test_tool_name_sanitization.py` (7), `test_conversion_missing_inputs.py` (3) |
| **Snippet par symbole en conversation** | `methodology/snippet/test_snippet_symbol.py` (13), moitié `snippet_tool` |
| **Auth / erreur d'accès modèle** | `providers/auth/test_model_access_error.py` (1), `test_auth_error_subprocess.py` (1) |

### KEEP_UNIT — garder (load-bearing, non exerçable en conversation)

- **`xml_protocol/`** (170) : invariants du parseur streaming (chunks mid-tag, CDATA,
  fences, thinking, sérialisation). Fondation de tous les tests de conversation.
- **`thinking/`** parser units (149 au total dans le dossier, dont
  `test_thinking_parser.py` 34) : indentation, escape, strip_tool_use, protection
  des blocs.
- **`agent_loop/`** détecteurs : loop_detector, tool_loop_detector, cache
  frozen/multiturn, token_accounting.
- **`providers/`** résilience : inter_chunk_timeout, stream_resilience, retry,
  openrouter_registry / openrouter_conversion, `wire/test_fake_llm` (infra MockLLM).
- **`methodology/cache/`** hors `test_cache_wire_e2e.py` : budget, split, multiturn,
  delta_invalidation (assertions byte-level).
- **`methodology/test_methodology_race.py`** (1) : concurrence ThreadPool.
- **`dag/`** (49), **`checkpoint/test_checkpoint.py`** (24), **`multi_agent/test_task.py`** (37) :
  machines à états, timing, structures de données.
- **`sessions/persistence/`** : safe_write_json, rotate_backup (I/O atomique).
- **`tools/`** : test_diff_view, registry/test_tool_registry, test_tool_enable_disable,
  test_commands_cleanup, `test_mods` partie DAG/sanitize.
- **`compaction/`** (24), **`prompts/test_system_prompts_loading.py`** (4) : intégrité
  build-time des prompts, estimate_tokens.
- **`enforcement/test_snippet_threshold.py`** (16) et
  **`methodology/snippet/test_snippet_tool_fallback.py`** (7) : bornes/seuils et
  départage de chemins — une conversation atteint *une* branche, pas *chaque* branche.

### KEEP_GUARD — garder (gardes de nettoyage, peu coûteux)

`regression/removed/*`, `regression/structure/*`, `regression/smoke/*`
(sauf `test_version.py`, doublon) — 48 tests au total.

---

## 4. Chantiers parallèles

Au 2026-07-27, d'autres périmètres sont en cours de refonte par d'autres agents et
bougent d'un jour à l'autre — les chiffres ci-dessus les concernant sont un
instantané, à revérifier avant d'agir :

- `sessions/`, `checkpoint/`, `plan_mode/` — plusieurs fichiers en cours de
  suppression/renommage (`plan_mode/test_plan_auto_validator*.py` ne s'importe plus :
  `bouzecode.backend.tools.plan_auto_validator` n'existe pas).
- `web_v2/` — descente des tests Playwright vers le client de test Flask (niveau 3).
  `sessions/resume/test_resume_*.py` importe encore `bouzecode.web`, paquet supprimé.

**Règle absolue de ce chantier : ne jamais écrire un chemin dans ce document sans
l'avoir vérifié sur le disque.** La cause racine de toute la dérive précédente est
une doc écrite de mémoire.
