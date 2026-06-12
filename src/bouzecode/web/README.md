# web — BouzéqUI

## Purpose

Flask web interface for bouzecode: launch agents on demand, browse/edit skills, inspect available tools.

## Usage

```powershell
bouzequi              # via entry point (after pip install -e .[web])
python -m web         # or directly
powershell -File ..\bouzequi.ps1  # one-shot launcher: ensures uv, env, deps
```

Default: http://127.0.0.1:5055

## Files

| File | Role |
|------|------|
| `app.py` | Flask factory, routes, `main()` entry |
| `runner.py` | Spawn + track `bouzecode_sncf` subprocesses |
| `skills_service.py` | Load/edit skills via `skill.loader` |
| `tools_service.py` | List tools from `tool_registry` |
| `__main__.py` | Enables `python -m web` |
| `templates/` | Jinja templates (base + agents/skills/tools subdirs) |
| `static/style.css` | Minimal styles |

Agent state is persisted under `~/.bouzecode/web_agents/`.
