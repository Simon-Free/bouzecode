# enforcement/e2e/

## Purpose
Enforcement observed from real `bouzecode()` conversations (`tests.e2e_harness` +
`MockLLM`): nothing is faked but the model's replies, and the assertions read the
loop's own `EnforcementWarning` events and tool results rather than a hand-built
message list.

## Usage
- `test_e2e_plan_rejected_enforcement.py` — after a `WritePlan` is approved, a `Write` goes through (the plan gate is advisory).
- `test_e2e_skill_enforcement.py` — a `Skill` result is tracked like a `Read`: uncovered triggers recovery, covered by `Snippet` (with or without ranges) completes, and a mixed Read+Skill batch recovers only what is still uncovered.
- `test_e2e_snippet_coverage.py` — an un-snippeted `Read` raises `EnforcementWarning(missing_tools=["Snippet"])`; covering it in the same batch, discarding it, or snippeting it on the next turn stays silent.
