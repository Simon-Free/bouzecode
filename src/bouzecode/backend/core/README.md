# core/

## Purpose
The shared foundation every other backend package imports: configuration, the tool registry, system-prompt assembly, extra source directories, and a few small self-contained utilities.

## Usage
- `config.py` — `load_config`, `save_config`, `current_provider`, `has_api_key`, `calc_cost`; the path constants `CONFIG_DIR`, `CONFIG_FILE`, `HISTORY_FILE`, `SESSIONS_DIR`, `DAILY_DIR`, `SESSION_HIST_FILE`, and the `DEFAULTS` dict
- `context.py` — `build_system_prompt_parts()` returns the (stable, volatile) halves of the system prompt, the boundary being where the cache breakpoint belongs; `build_system_prompt()` concatenates them. Section builders: `get_git_info`, `checked_out_branch`, `get_platform_hints`, `get_skills_section`, `render_profile_skills`, `get_memory_context`, `get_readme_navigation_section`, `agents_map_enabled`
- `_embedded_data.py` — loads the prompt templates and text assets at import: `SYSTEM_PROMPT_TEMPLATE`, `THINK_OUT_LOUD_PROMPT`, `WINDOWS_PLATFORM_HINTS`, `PLAN_MODE_TEMPLATE`, `TOOL_EXAMPLES_XML`, `TOOL_EXAMPLES_JSON`, `LOGO_TEXT`, `COMPACTION_SYSTEM_PROMPT`
- `tool_registry.py` — `ToolDef`, `register_tool`, `unregister_tool`, `get_tool`, `get_all_tools`, `get_tool_schemas`, `execute_tool`; enable/disable (`disable_tool`, `enable_tool`, `is_enabled`, `list_disabled`, `reset_disabled`, `available_tool_names`); thread-local overlays for parallel conversations (`push_local_overlay`, `pop_local_overlay`); `FRAMEWORK_ALWAYS_ON`, `ends_turn`, `is_concurrent_safe`, `clear_registry`
- `tool_mentions.py` — `tool_names_cited` (tool names in prose), `suggest_substitutes`, `unavailable_tool_message` (a terminal refusal quoting the live registry)
- `paths.py` — extra source dirs injected at the CLI: `register_extra_dirs`, `get_extra_dirs`, `add_extra_dir`, `remove_extra_dir`, plus the persisted variants `persist_extra_dir`, `unpersist_extra_dir`, `load_persisted_extra_dirs`, `register_persisted_extra_dirs`
- `profile_extra.py` — `get_agent_profile_extra(classification)` and `get_default_agent_profile_extra()`: the composed `system_prompt_extra` for a profile, merged with the always-on builtin capability fragments and cached per resolution root
- `lean_prompt.py` — `apply_lean_turn_protocol` strips the heavy methodology sections for lightweight profiles
- `local_http.py` — `local_json`, `no_proxy_opener`, `proxy_vars_in_env`, `LocalServerError`: an HTTP client for the local server that is never proxied and reports actionable errors
- `payload_view.py` — reads the payload journal of a session and folds its deltas back into full payloads: `read_records`, `fold_records`, `load_turn_records`, `load_turn_map`, `payload_dir`, `to_refs`, `from_refs`
- `gitlab_resolve.py` — `resolve_input` turns a repo URL or a local git directory into plugin source coordinates; `plugin_install_target`; `SourceError`
- `__init__.py` re-exports the public surface
