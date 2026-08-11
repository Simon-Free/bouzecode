# tests/backend/config/

## Purpose
Pins the defaults returned by `bouzecode.backend.core.config.load_config`, read from
the real configuration rather than a fixture.

## Usage
- `test_native_reasoning_default.py` — `native_reasoning` is off by default, so reasoning goes through manual `<thinking>` text instead of the provider's native channel.
