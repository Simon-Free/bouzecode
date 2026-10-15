# tools/ops/

## Purpose
Concrete implementations of the built-in agent tools (file I/O, shell, web, notebooks, diagnostics).

## Usage
- `file_ops.py` — `_read`, `_write`, `_edit`, `generate_unified_diff`, `maybe_truncate_diff`
- `edit_match.py` — why an `Edit` missed: `describe_missing_old_string` (line-level diff marking diverging lines with `≠`), `find_uniform_reindent` + `reindent_block` (the ONE tolerated repair, under four cumulative guards)
- `edit_context.py` — post-edit enrichment: `build_edit_context`, `find_enclosing_symbol`
- `long_lines.py` — giant lines (minified HTML/JS) in tool echoes: `ecourter_ligne` (head + « … N car. … » + tail past 200 chars), `compacter_diff` (a paired -/+ line shows only the changed window with char positions), `plafonner_caracteres` (char cap on top of the line cap). Short lines are rendered unchanged
- `read_params.py` — `normalize_read_params`: converts Snippet's 1-indexed `ranges` / `start_line` into Read's 0-indexed `offset`+`limit`, refuses multi-range and `command=`
- `shell_search.py` — `_bash`, `bash_handler`, `_build_popen_command`, `_kill_proc_tree`, `_is_safe_bash` (re-exports the search helpers below)
- `pytest_zero.py` — `explication` : run sans aucun test → verdict de pytest, ce qui a désélectionné, `marker=` qui les lance
- `cibles_pytest.py` — `cibles_absolues` : `targets` lus une fois depuis le dossier de l'agent ; cible introuvable refusée
- `pytest_shell_guard.py` — `refus_pytest_shell` : pytest lancé par le Bash (`pytest`, `py.test`, `python -m pytest`, `uv run …`, préfixes compris) est refusé avec l'appel `RunPythonTest(...)` équivalent ; `# allow-raw-pytest: <raison>` laisse passer
- `shell_command_rewrite.py` — `unwrap_nested_powershell`, `spill_inline_python`: the two pre-execution rewrites (see below)
- `shell_env.py` — `_get_env_with_user_vars`, `_merge_user_env`, `_powershell_exe`: the environment a command runs in
- `grep_glob.py` — `_glob`, `_grep`, `_has_rg`, `_build_grep_summary`
- `glob_cap.py` — `cap_glob_matches`, `GLOB_CAP`: a Glob result over the cap prints its first `GLOB_CAP` paths plus a directory rollup of the rest. A cap, never a refusal
- `grep_cap.py` — `plafonner_fichiers`, `relativiser`, `GREP_FILES_CAP`: a Grep `files_with_matches`/`count` list prints paths relative to the agent's folder, capped at `GREP_FILES_CAP` files spread across top-level folders, plus a per-folder count. A cap, never a refusal
- `bash_bg.py` — `start_background`, `bash_output`
- `web_ops.py` — `_webfetch`, `_websearch`
- `notebook_diagnostics.py` — `_notebook_edit`, `_get_diagnostics`, `_detect_language`, `_run_quietly`
- `test_runner.py` — `run_python_test` (RunPythonTest) ; `runner_guards.py` — ses garde-fous : `-n 4` par défaut et `-n auto` refusé (machine partagée), `--durations=5` ajouté (15 avec `show=['durations']`), `-o faulthandler_timeout=120` et `-p no:rerunfailures` sauf choix de l'appelant
- Sans cible, RunPythonTest lance la sélection impactée : `impacted.py` (`selection_impactee` : git diff depuis le merge-base develop/master + non commité + non suivi → testmon lu en SQLite, `.bouzecode/tests.yaml`, fichiers de test modifiés), `tests_config.py` (`lire_config_tests`, globs `**`), `git_base.py` (merge-base, fichiers changés, `worktree_jetable`), `selection_plugin.py` (plugin pytest injecté : filtre par ids, écrit l'issue de chaque test)
- `baseline.py` — `comparer_avec_la_base` : après un run impacté ou `full=true`, les ids en échec sont rejoués sur le merge-base dans un worktree jetable, cache `~/.bouzecode/test_baselines/<dépôt>/<sha>.json` ; sépare NEW failures et pre-existing on base (`failed` ou `error` sur la base = pre-existing) ; sous le démon, appelée dans le créneau du job (`testd/run/job.py`)
- `pytest_compact.py` — `rendu_pytest`, `compact_pytest_output` : sortie pytest minimale (vert = verdict + tests ≥ 1 s ; rouge = extrait par échec, résumé, chemin de la sortie complète ; vues `show`) ; s'appuie sur `pytest_sections.py` (découpage `=== titre ===`, warnings dédoublonnés, tests lents) et `pytest_failures.py` (`extrait_d_echec`)
- `env_diagnosis.py` — `regrouper`, `rendu_groupes` : échecs de même signature (type + 1re ligne, chemins `<path>`, nombres `N`) sur une ligne `N × signature (e.g. id)`, un seul extrait par signature ; remède d'une ligne pour les signatures d'environnement connues (navigateur Playwright absent, module absent, connexion refusée, port pris, setups à ~2 s)

### Why a command may not run verbatim
- A command that is itself `powershell -Command "..."` is **unwrapped**: Bash already runs
  PowerShell, and the extra shell interpolates the body's variables away before the inner
  one sees them. Wrappers carrying `-ExecutionPolicy`, `-File`, or `pwsh` are left alone —
  decision boundary in `shell_command_rewrite.unwrap_nested_powershell`.
- `python -c "<code>"` is **spilled** to a `temp_*.py` scratch file which is then run; the
  tool result says where. It is refused only when the code cannot be unquoted losslessly.
