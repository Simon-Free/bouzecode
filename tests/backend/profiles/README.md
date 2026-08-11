# profiles/

## Purpose
Covers the agent-profile system, `bouzecode.backend.profiles` (models, loader,
composer, discovery, catalog) and the launch-time appliers in `bouzecode.ui.cli`
(`apply_profile_tools`, `apply_profile_hooks`, `apply_profile_plan_mode`,
`apply_profile_recap`), plus the built-in YAML profiles shipped under
`src/bouzecode/backend/profiles/builtin/`. Tests load real YAML — either the shipped
files or ones written into `tmp_path` — and assert on the resolved profile, the
composed `system_prompt_extra` and the tool registry state; a `restore_tool_state`
fixture puts the registry back. Two files reach further: the catalog test builds a
real git remote with `subprocess`, and the loop-flag test runs `bouzecode()`
conversations with `MockLLM`.

## Usage
- `test_app_kind_exclusion.py` — a `kind: app` profile loads by path but is excluded from the switchable set and from dispatch typologies.
- `test_builtin_capabilities.py` — packaged capabilities compose with a typology profile, are added even with no profile, and are never injected twice.
- `test_catalog.py` — `profiles.catalog`: clone then split a remote repo, missing plugin, local profiles always installed, idempotent pull, and URL resolution rules.
- `test_frontend_profile.py` — the built-in `frontend` profile loads, registers as a dispatch typology, and carries its test guidance, guardrails and devtools flag.
- `test_manager_profile.py` — the built-in `manager` profile: read-only dispatcher, no methodology enforcement, one implementation ticket per deliverable, investigation kept apart from implementation.
- `test_meta_agent_delegation.py` — the meta-agent declares the delegation and editing tools, and applying it enables the dispatch tool.
- `test_profile_composition.py` — `--profile X` augments the shared default layer: ordering, no double injection, project profiles, opting out, and allowlists that gain nothing from composition.
- `test_profile_hooks_plan_mode.py` — `apply_profile_hooks` wires the completion chain per profile, and the `plan_mode` / `require_recap` fields take effect.
- `test_profile_loop_flags.py` — profile `hooks:` drive per-agent loop behaviour, observed in conversations (methodology enforcement on and off, no smuggling window).
- `test_profiles.py` — `AgentProfile`, `load_profile_from_path`, `load_profiles_from_dir`, `merge_profiles`, `_union_lists`, and the default profile.
- `test_profiles_integration.py` — `SubAgentManager._resolve_profiles` merges profiles found on disk at spawn time, and returns nothing for unknown names.
- `test_python_coder_template.py` — the coder profile's report template declares its six sections, in order.
