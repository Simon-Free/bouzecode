# plan_mode/

## Purpose
Covers plan mode: the tools in `bouzecode.backend.tools.plan_mode`
(`EnterPlanMode`, `ExitPlanMode`, `WritePlan`), the permission gate in
`bouzecode.backend.agent._check_permission`, the answer reader
`tools.plan_validation.is_plan_approved`, and the LLM-backed
`tools.plan_auto_validator`. Two levels on purpose: unit tests call the gate and the
parsers directly, while the `_e2e` files play whole `bouzecode()` conversations
driven by `MockLLM` and read the tool results and the offered tool set.

## Usage
- `conftest.py` — `_plan_files_stay_out_of_the_repo`, autouse: every test runs from a throwaway cwd so plan files never land in the checkout.
- `test_plan_auto_validator.py` — `_parse_verdict`, `validate_plan_auto` with an override and with a context state, and the instructions separator.
- `test_plan_auto_validator_e2e.py` — an approved verdict unblocks the following write, a rejected one returns its feedback.
- `test_plan_auto_validator_xml.py` — the XML decision format is parsed correctly, against a scripted provider stream.
- `test_plan_enforcement_e2e.py` — the `WritePlan` contract: writes and edits allowed without a plan, temp and test files allowed, plan appended to the methodology, empty plan rejected, reads never gated.
- `test_plan_mode_hides_write_tools_e2e.py` — entering plan mode removes the write tools from what is offered, leaving restores them, and a tool the profile never had is not handed out.
- `test_plan_tools.py` — `_enter_plan_mode` switches the permission mode; reads stay allowed, writes are blocked except the plan file, plan tools are never gated.
- `test_plan_tools_e2e.py` — `EnterPlanMode` / `ExitPlanMode` in conversation: activation and plan file creation, idempotent entry, exit echoing the plan and restoring the mode, empty plan and exit-without-enter rejected.
- `test_plan_validation.py` — `is_plan_approved`: only the option-number-one answer approves.

## Subfolders
| Folder | Description |
|--------|-------------|
| `ipc/` | Plan validation seen through the IPC state file the web UI watches. |
