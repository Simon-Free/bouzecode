# providers/auth/

## Purpose
Covers authentication failures on the Anthropic path — that a denied model or a bad
credential surfaces as a clean, readable error instead of a crash inside
`_create_anthropic_stream_with_retry` (`providers.backends.anthropic_helpers`). One
unit test drives the retry helper with a fake client; the two others launch a real
run in a subprocess and read what the user would see, self-skipping without
credentials via `require_api_key` from `tests/cache_conversation_helpers.py`.

## Usage
- `test_auth_error_subprocess.py` — a run against a model the key cannot access exits with a clean message.
- `test_auth_retry_unit.py` — a model-access denial raises immediately, a generic auth error is retried then raised.
- `test_model_access_error.py` — same denial observed end to end through the CLI, checking the process output.
