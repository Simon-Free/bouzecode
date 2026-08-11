# tests/backend/web_v2/

## Purpose
Covers the plugin service of the web server (`bouzecode.web_v2.services.plugins`)
from the backend side. Only the side-effect-free branches run: `load_user_profiles`
is swapped on the module for a lambda returning fake profile objects, so no network
call and no install happens.

## Usage
- `test_upgrade_profile_plugins.py` — `upgrade_profile_plugins` returns an `error` naming an unknown agent, and returns `requires_confirmation` plus the listed `sources` when a required plugin comes from a git source and `confirm_git=False`.
