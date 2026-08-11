# agent/

## Purpose
Tests of the `bouzecode.backend.agent` modules that sit around the turn loop: close
validation, task classification, the hook pipeline, pause and resume on
`AskUserQuestion`, and close bookkeeping after a fatal API failure. The approach is
unit-level with hand-written fakes and `pytest.monkeypatch`; the provider stream is
replaced either through `stream_interceptor` or by swapping the module-level
`dispatch_stream`, never with `unittest.mock.patch`.

## Usage
- `test_close_validator.py` — `close_validator.validate_close`: OK and KO verdict parsing with feedback, best-effort acceptance when the call raises, the config gate that skips the call entirely, and the validator request staying light.
- `test_task_classifier.py` — `task_classifier.classify_task` and `classify`: type parsing (case- and noise-tolerant), the scope axis, garbage and exception fallbacks to `autre`/`doute`, the config and `_depth` gates, long-message truncation.
- `test_hooks_pipeline.py` — `agent.hooks.pipeline` (`register_hook`, `fire`, `reset`, the named builtin catalog, a failing hook not aborting the others) and `hooks.context.HookContext` / `completion_context`; then asserts `loop.run` fires `on_completion` on graceful closes (text with no tools, FinalAnswer, deferred FinalAnswer) but not on `assistant_none` nor on a partial stream.
- `test_multi_ask_resume.py` — `loop.resume_paused` surfaces several `AskUserQuestion` calls from one turn one at a time, each as a fresh `PausedForInput`, and `core.tool_registry.execute_tool` propagates that control-flow exception instead of turning it into an error string.
- `test_resume_paused_object.py` — `resume_paused` accepts a live `PausedForInput` object as its pending argument, not only a dict.
- `test_api_error_close_reason.py` — a streamer raising `anthropic.APIConnectionError` before any event leaves `close_reason="api_error"` on the `AgentState` before the exception propagates; the failure is injected with `set_stream_interceptor`.

## Subfolders
| Folder | Description |
|--------|-------------|
| `providers/` | Tests of the provider layer; the concrete cases live in its `backends/` child. |
