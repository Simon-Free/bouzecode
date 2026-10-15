# ui/

The UI package implements the interactive REPL, terminal rendering (Rich live display), spinner animations, tool output formatting, and all `/slash` commands.

---

## Entry Points

| Function | File | Description |
|----------|------|-------------|
| `main()` | `cli.py` | CLI entry point — parses args, loads config, launches REPL |
| `repl()` | `repl.py` | Interactive read-eval-print loop |
| `run_query()` | `repl.py` | Execute one user turn: stream LLM → process tools → display |
| `replay_messages()` | `replay.py` | Replay a saved conversation to terminal |
| `tickets_cli.main()` | `tickets_cli/` | `bouzecode tickets …` / `bouzecode projets …` : tickets, agents locaux ou Rundeck, suivi — sans serveur web (ou via son API s'il tourne). Routé par `cli.py` avant le parseur du REPL |
| `conclure()` | `cloture_cli.py` | End of a `-p` run: FinalAnswer text to `--result-file` (delivered runs only), exit code (0 FinalAnswer only, 3 model refusal, 4 end without delivery incl. prose, 5 interrupted/unknown) + `<result-file>.cloture.json` |

---

## Main Call Graph — `main()` → `repl()` → `run_query()`

```
main(argv)                                          [cli.py]
 │
 ├─ parse_args(), load_config()
 └─ repl(state, config)                             [repl.py]
      │
      ├─ setup_readline()                           [commands/readline_setup.py]
      ├─ prompt_toolkit / input()  → user_message
      │
      ├─ handle_slash(user_message, state, config)  [commands/dispatcher.py]
      │    └─ COMMANDS[cmd](args, state, config)    [commands/*]
      │         └─ returns True | sentinel tuple | SkillDef
      │
      ├─ process_sentinels(sentinel)                [repl_sentinels.py]
      │    └─ dispatches voice, image, brainstorm, SSJ, etc.
      │
      └─ run_query(user_message, state, config)     [repl.py]
           │
           ├─ agent.run(message, state, config, system_prompt)
           │    └─ yields: TextChunk, ThinkingChunk, ToolStart, ToolEnd, TurnDone
           │
           ├─ stream_text(chunk)                    [rendering.py]
           ├─ stream_thinking(chunk)                [rendering.py]
           ├─ _start_tool_spinner(tool_call)        [spinner.py]
           ├─ print_tool_start(tool_call)           [tool_display.py]
           ├─ print_tool_end(tool_call, result)     [tool_display.py]
           ├─ _stop_tool_spinner()                  [spinner.py]
           ├─ flush_response()                      [rendering.py]
           │
           ├─ [if PermissionRequest]
           │    └─ ask_permission_interactive()      [commands/]
           │
           └─ save_progressive(state, config)       [commands/]
```

---

## Component Zoom — Rendering

```
stream_text(text)                                   [rendering.py]
 ├─ _start_live() → creates Rich Live context
 ├─ _accumulated_text += text
 ├─ _make_renderable(text) → Markdown panel
 ├─ _estimate_rendered_lines() → overflow detection
 └─ _flush_overflow_line() → scroll buffer

stream_thinking(text)                               [rendering.py]
 └─ italic styling + same live display pipeline

flush_response()                                    [rendering.py]
 └─ stop Rich Live, print final accumulated text
```

---

## Component Zoom — Spinner

```
_start_tool_spinner(tool_call)                      [spinner.py]
 ├─ _spinner_phrase(tool_call) → pick animated phrase
 └─ threading.Thread(_run_tool_spinner)
      └─ animated dots + phrase rotation

_change_spinner_phrase(new_phrase)                   [spinner.py]
 └─ thread-safe phrase swap via _spinner_lock

_stop_tool_spinner()                                [spinner.py]
 └─ signal thread to stop, join, erase line
```

---

## Component Zoom — Tool Display

```
print_tool_start(tool_call)                         [tool_display.py]
 └─ _format_tool_call(name, inputs) → black-style multiline call (all params, values truncated to 100 chars with …)

print_tool_end(tool_call, result, duration)         [tool_display.py]
 ├─ _fmt_duration(seconds) → "1.2s"
 ├─ _has_diff(tc, result) → detect file changes
 └─ render_diff(old, new) → inline unified diff
```

---

## Component Zoom — Commands

```
handle_slash(text, state, config)                   [commands/dispatcher.py]
 ├─ parse command name + args
 ├─ COMMANDS[name] → handler function
 └─ handler(args, state, config)
      └─ returns True | sentinel | SkillDef

setup_readline()                                    [commands/readline_setup.py]
 ├─ history file load/save
 └─ tab-completion (command names + file paths)
```

### Command sub-packages

| Sub-folder | Purpose |
|------------|---------|
| `core/` | Essential commands: /clear, /quit, /model, /config |
| `session/` | Session management: /save, /load, /history |
| `extensions/` | Plugin/skill commands: /skill, /mcp, /agent |
| `info/` | Informational: /status, /tokens, /cost |
| `misc/` | Utilities: /voice, /image, /paste, /brainstorm |

---

## Component Zoom — Sous-agents et barre du bas (`barre_agents/`)

En TUI interactif, l'outil `Agent` lance ses sous-agents **dans ce process** (un fil chacun,
récursif jusqu'à `max_agent_depth`) ; `subagents_window: true` rend l'ancien mode « une fenêtre
de terminal par sous-agent ». Sous la saisie, une ligne par agent :

```
  ● main
  ◯ ▶ general-purpose  Rundeck remote run + Playwright   in 20.3k · out 1.2k · cache 8.0k · 0.31 $  1m 3s
    ◯ ? coder          sous-tâche du précédent            in 1.1k · out 90 · 0.02 $  12s
```

`●` = agent affiché ; état sans couleur : `▶` en cours, `?` attend ta réponse, `✓` fini,
`✗` erreur (dont « fini SANS FinalAnswer »), `■` interrompu, `⚑` alerte `Signaler`.

| Touche | Effet |
|---|---|
| `↓` (saisie vide) | focus dans la liste ; `↑`/`↓` choisir |
| `Entrée` | ouvrir la conversation de l'agent ; le texte tapé ensuite lui est envoyé (réponse à sa question, message lu à sa prochaine étape, ou reprise s'il est fini) |
| `Échap` | revenir à main |
| `x` (liste) / `Ctrl+X` (vue) | interrompre l'agent (et ses descendants) |

Pendant que main attend ses enfants (`Agent` sans `background`, `CheckAgentResult(wait=true)`),
la saisie et la barre restent ouvertes ; un texte tapé dans la vue main entre dans sa boîte
aux lettres (relevée à sa prochaine étape). Rendu de la barre testé en texte
(`tests/ui/barre_agents`), TUI piloté de bout en bout au clavier contre un faux LLM HTTP.
Pendant les tours de main (invite fermée), la barre est dessinée en pied du spinner, du
`rich.Live` du texte et de la réflexion (`barre_agents/rendu.py`, section « pied ») ; la
navigation clavier reste réservée aux moments où l'invite est ouverte.
`bouzecode --prompt-file x.txt` (ou un prompt positionnel) dans une console, sans `-p` : le prompt
est soumis comme un 1er message tapé, barre posée avant lui, et le REPL reste ouvert ensuite
(`lancement_tui.py`) ; `-p`, agent web, stdin sans console et reprises auto gardent le run
non interactif.

---

## Component Zoom — Paste Input

```
get_paste_block()                                   [paste_input/]
 ├─ detect platform (Windows / macOS / Linux)
 ├─ platform-specific clipboard read
 └─ return multi-line string
```

---

## Module Reference

| File | Lines | Purpose |
|------|-------|---------|
| `__init__.py` | 18 | Re-exports: ANSI colors, rendering, spinner, tool display, replay |
| `cli.py` | ~120 | CLI entry point: arg parsing, config loading, `main()` |
| `repl.py` | ~670 | REPL loop, `run_query()` turn handler, sentinel dispatch |
| `lancement_tui.py` | ~30 | Prompt de lancement (`--prompt-file`/positionnel, sans `-p`) en console : 1er message du TUI interactif |
| `repl_sentinels.py` | ~150 | Process sentinel tuples from slash commands |
| `rendering.py` | ~250 | Rich Live display: `stream_text()`, `stream_thinking()`, `flush_response()` |
| `spinner.py` | ~130 | Animated tool spinner with thread-safe phrase rotation |
| `tool_display.py` | ~180 | Tool start/end formatting, inline diffs |
| `ansi.py` | ~60 | ANSI color constants and helper functions: `C`, `clr`, `info`, `ok`, `warn`, `err` |
| `replay.py` | ~110 | `replay_messages()` — replay saved conversations to terminal (returns the `DerouleConversation` used) |
| `deroule.py` | ~95 | `DerouleConversation` — incremental renderer shared by replay and the live follow of a sub-agent |
| `commands/` | — | All `/slash` commands (see `commands/README.md`) |
| `paste_input/` | ~200 | prompt_toolkit input with paste badges (`main_session_with` for extra keys) |
| `barre_agents/` | ~490 | Sub-agents bar under the input, navigation, sub-agent views |
| `tickets_cli/` | ~600 | `bouzecode tickets` / `projets` : commandes sans serveur (cf. `tickets_cli/README.md`) |

---

## External Dependencies (called from ui/)

| Module | Functions used |
|--------|---------------|
| `backend.agent` | `run()`, `resume_paused()`, `AgentState`, event types (`ToolStart`, `ToolEnd`, `TurnDone`, `PermissionRequest`) |
| `backend.thinking_parser` | `ThinkingStreamParser`, `LoopDetector` |
| `backend.config` | `load_config()`, `BouzecodeConfig` |
| `backend.providers` | `TextChunk`, `ThinkingChunk` |
| `backend.sessions` | `save_session()`, `load_session()` |
| `rich` | `Console`, `Live`, `Markdown`, `Panel`, `Text` |
| `prompt_toolkit` | Input handling (optional, falls back to `input()`) |
