# [desc] JSON schema definitions for tools exposed to the Claude API. [/desc]
"""Tool JSON schemas sent to the Claude API."""
import platform as _platform

_BASH_BASE_DESCRIPTION = (
    "Execute a shell command. Returns stdout+stderr. Stateless (no cd persistence). "
    "On Windows, commands are executed via PowerShell (auto-encoded as Base64), "
    "so ALWAYS write PowerShell-compatible syntax (e.g. Get-Content, Get-ChildItem, $env:VAR)."
)

_WINDOWS_BASH_HINTS = """
WINDOWS SHELL RULES (you are on Windows):
- **CRITICAL**: NEVER use `&&` to chain commands — it DOES NOT WORK in PowerShell and causes a parse error. ALWAYS use `;` instead. Example: `cmd1 ; cmd2 ; cmd3`
- `type file.txt` instead of `cat file.txt`
- `type file.txt | findstr /n /i "pattern"` instead of `grep`
- `powershell -NonInteractive -Command "Get-Content file.txt -Tail 20"` instead of `tail -n 20`
- `powershell -NonInteractive -Command "Get-Content file.txt -Head 20"` instead of `head -n 20`
- `dir /s /b *.py` or `powershell -NonInteractive -Command "Get-ChildItem -Recurse -Filter *.py"` instead of `find . -name '*.py'`
- `del file.txt` instead of `rm file.txt`
- `mkdir folder` works on both (no -p needed)
- `copy` / `move` instead of `cp` / `mv`
- Paths use backslashes `\\` but forward slashes `/` also work in most cases
- NEVER use `python -c` -- write a temp_*.py file, run it, delete it
- Multi-line commands: NEVER run multi-line commands inline. ALWAYS write a temp script file (.ps1, .py, .cmd), execute it, then delete it."""

_BASH_DESCRIPTION = (
    _BASH_BASE_DESCRIPTION + _WINDOWS_BASH_HINTS
    if _platform.system() == "Windows"
    else _BASH_BASE_DESCRIPTION
)

TOOL_SCHEMAS = [
    {
        "name": "Read",
        "description": (
            "Read a file's contents. Returns content with line numbers "
            "(format: 'N\\tline'). Use limit/offset for chunks, or symbol='name' "
            "to read a specific function/class/method (Python, JS/TS)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Absolute file path"},
                "limit":     {"type": "integer", "description": "Max lines to read"},
                "offset":    {"type": "integer", "description": "Start line (0-indexed)"},
                "symbol":    {"type": "string", "description": "Read only a specific symbol (function/class/method). Use 'ClassName.method' for nested. Python and JS/TS only. Ignores limit/offset."},
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "Write",
        "description": "Write content to a file, creating parent directories as needed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "content":   {"type": "string"},
            },
            "required": ["file_path", "content"],
        },
    },
    {
        "name": "Edit",
        "description": (
            "Replace exact text in a file. old_string must match exactly (including whitespace). "
            "If old_string appears multiple times, use replace_all=true or add more context."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path":   {"type": "string"},
                "old_string":  {"type": "string", "description": "Exact text to replace"},
                "new_string":  {"type": "string", "description": "Replacement text"},
                "replace_all": {"type": "boolean", "description": "Replace all occurrences"},
            },
            "required": ["file_path", "old_string", "new_string"],
        },
    },
    {
        "name": "Bash",
        "description": _BASH_DESCRIPTION,
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer", "description": "Seconds before timeout (default 30). Use 120-300 for package installs (npm, pip, npx), builds, and long-running commands. Test suites (pytest) often need 120-600s; prefer RunPythonTest which has a dedicated long timeout."},
            },
            "required": ["command"],
        },
    },
    {
        "name": "Glob",
        "description": "Find files matching a glob pattern. Returns sorted list of matching paths. Respects .gitignore by default.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern e.g. **/*.py"},
                "path":    {"type": "string", "description": "Base directory (defaults to cwd)."},
                "ignore_gitignore": {"type": "boolean", "description": "Respect .gitignore files (default true). Set false to include all files."},
                "include_patterns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Gitignore-syntax patterns to RE-INCLUDE despite .gitignore (e.g. ['*.csv', 'data/']). Only effective when ignore_gitignore=true.",
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "Grep",
        "description": (
            "Search file contents with regex using ripgrep. "
            "Respects .gitignore by default. Path defaults to cwd if omitted."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern":      {"type": "string", "description": "Regex pattern"},
                "path":         {"type": "string", "description": "Directory or file to search (defaults to cwd)."},
                "glob":         {"type": "string", "description": "File filter e.g. *.py"},
                "output_mode":  {
                    "type": "string",
                    "enum": ["content", "files_with_matches", "count"],
                    "description": "content=matching lines, files_with_matches=file paths, count=match counts",
                },
                "case_insensitive": {"type": "boolean"},
                "context":      {"type": "integer", "description": "Lines of context around matches"},
                "ignore_gitignore": {"type": "boolean", "description": "Respect .gitignore files (default true). Set false to search all files."},
                "include_patterns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Gitignore-syntax patterns to RE-INCLUDE despite .gitignore (e.g. ['*.csv', 'data/']). Only effective when ignore_gitignore=true.",
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "WebFetch",
        "description": "Fetch a URL and return its text content (HTML stripped).",
        "input_schema": {
            "type": "object",
            "properties": {
                "url":    {"type": "string"},
                "prompt": {"type": "string", "description": "Hint for what to extract"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "WebSearch",
        "description": "Search the web via DuckDuckGo and return top results.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "TaskCreate",
        "description": (
            "Create a new task in the task list. "
            "Use this to track work items, to-dos, and multi-step plans."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "subject":     {"type": "string", "description": "Brief title"},
                "description": {"type": "string", "description": "What needs to be done"},
                "active_form": {"type": "string", "description": "Present-continuous label while in_progress"},
                "metadata":    {"type": "object", "description": "Arbitrary metadata"},
            },
            "required": ["subject", "description"],
        },
    },
    {
        "name": "TaskUpdate",
        "description": (
            "Update a task: change status, subject, description, owner, "
            "dependency edges, or metadata. "
            "Set status='deleted' to remove. "
            "Statuses: pending, in_progress, completed, cancelled, deleted."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id":       {"type": "string"},
                "subject":       {"type": "string"},
                "description":   {"type": "string"},
                "status":        {"type": "string", "enum": ["pending","in_progress","completed","cancelled","deleted"]},
                "active_form":   {"type": "string"},
                "owner":         {"type": "string"},
                "add_blocks":    {"type": "array", "items": {"type": "string"}},
                "add_blocked_by":{"type": "array", "items": {"type": "string"}},
                "metadata":      {"type": "object"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "TaskGet",
        "description": "Retrieve full details of a single task by ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID to retrieve"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "TaskList",
        "description": "List all tasks with their status, owner, and pending blockers.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "NotebookEdit",
        "description": (
            "Edit a Jupyter notebook (.ipynb) cell. "
            "Supports replace (modify existing cell), insert (add new cell after cell_id), "
            "and delete (remove cell) operations. "
            "Read the notebook with the Read tool first to see cell IDs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "notebook_path": {
                    "type": "string",
                    "description": "Absolute path to the .ipynb notebook file",
                },
                "new_source": {
                    "type": "string",
                    "description": "New source code/text for the cell",
                },
                "cell_id": {
                    "type": "string",
                    "description": (
                        "ID of the cell to edit. For insert, the new cell is inserted after this cell "
                        "(or at the beginning if omitted). Use 'cell-N' (0-indexed) if no IDs are set."
                    ),
                },
                "cell_type": {
                    "type": "string",
                    "enum": ["code", "markdown"],
                    "description": "Cell type. Required for insert; defaults to current type for replace.",
                },
                "edit_mode": {
                    "type": "string",
                    "enum": ["replace", "insert", "delete"],
                    "description": "replace (default) / insert / delete",
                },
            },
            "required": ["notebook_path", "new_source"],
        },
    },
    {
        "name": "GetDiagnostics",
        "description": (
            "Get LSP-style diagnostics (errors, warnings, hints) for a source file. "
            "Uses pyright/mypy/flake8 for Python, tsc for TypeScript/JavaScript, "
            "and shellcheck for shell scripts. Returns structured diagnostic output."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute or relative path to the file to diagnose",
                },
                "language": {
                    "type": "string",
                    "description": (
                        "Override auto-detected language: python, javascript, typescript, "
                        "shellscript. Omit to auto-detect from file extension."
                    ),
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "AskUserQuestion",
        "description": (
            "Pause execution and ask the user a clarifying question. "
            "Use this when you need a decision from the user before proceeding. "
            "Returns the user's answer as a string."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question to ask the user.",
                },
                "options": {
                    "type": "array",
                    "description": "Optional list of choices. Each item: {label, description}.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label":       {"type": "string"},
                            "description": {"type": "string"},
                        },
                        "required": ["label"],
                    },
                },
                "allow_freetext": {
                    "type": "boolean",
                    "description": "If true (default), user may type a free-text answer instead of selecting an option.",
                },
            },
            "required": ["question"],
        },
    },
    {
        "name": "SleepTimer",
        "description": (
            "Schedule a silent background timer. When the timer finishes, it injects an automated prompt into the chat history: "
            "'(System Automated Event): The timer has finished...' so you can seamlessly wake up and execute deferred monitoring tasks."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "seconds": {"type": "integer", "description": "Number of seconds to sleep before waking up."}
            },
            "required": ["seconds"],
        },
    },
    {
        "name": "Methodology",
        "description": (
            "Persist text into the methodology note (the cached working-memory block "
            "injected at the top of every future turn). This is your WORKING MEMORY — "
            "use it to state what you are TRYING TO DO, what you DID this turn, and "
            "what your NEXT STEP will be. You ALWAYS have something to write — even on "
            "turn 1, state your goal and plan. Also save plans, decisions, and extracted "
            "facts here. For file regions, use the Snippet tool instead — it freezes "
            "labeled line ranges from a file into the same note. "
            "Tool_results from your current batch DISAPPEAR at the next turn, so save "
            "what matters here BEFORE moving on. "
            "Content is always appended to the existing note."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Markdown text to append."},
            },
            "required": ["content"],
        },
    },
    {
        "name": "FinalAnswer",
        "description": (
            "End the session by delivering your final answer — the EXPLICIT close "
            "signal. Call it when the task is fully done (tests green, todolist all "
            "[x]) or your answer to the user is ready, in the SAME batch as your "
            "last Methodology. The session closes immediately after this turn; no "
            "further turns happen, so `answer` must be COMPLETE and self-contained "
            "(result, files touched, validation evidence). Do NOT keep iterating "
            "after success: validated task = call FinalAnswer now."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "answer": {
                    "type": "string",
                    "description": "The complete final answer/result delivered to the user.",
                },
            },
            "required": ["answer"],
        },
    },
    {
        "name": "Snippet",
        "description": (
            "Freeze labeled line range(s) into the methodology note. "
            "TWO MODES: (1) symbol= — stores file_path + symbol name, RE-RESOLVED "
            "dynamically at each turn (immune to staleness after Edits); prefer this "
            "for functions/classes/methods. (2) ranges= — frozen line ranges (legacy). "
            "HARD RULE: every snippetable tool_result MUST be either snippeted or "
            "explicitly discarded the turn after you receive it. Snippetable results "
            "are wrapped on the wire between '==== A SNIPPETER id: ... ====' and "
            "'==== FIN DE L'ELEMENT A SNIPPETER ====' markers; the marker tells you "
            "the exact id to use. "
            "Two keys: for a file result (Read/Skill/Grep/GetFolderDescription/WebFetch, "
            "marker 'id: file=...') pass file_path; "
            "for an inline tool output (marker 'id: tool_id=...') pass tool_id — the "
            "content is read back from the wrapped block, numbered 1..N for ranges. "
            "Emit one Snippet call per region you want to keep. "
            "PREFER symbol= over ranges= whenever a Python/JS/TS symbol is identifiable."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "ABSOLUTE path to the file (for 'id: file=...' markers)."},
                "tool_id": {"type": "string", "description": "The tool_call id from an 'id: tool_id=...' marker (for inline tool outputs)."},
                "symbol": {"type": "string", "description": "Symbol name (function/class/method) to snapshot dynamically. Use 'ClassName.method' for nested. Re-resolved at each turn — immune to line shifts after Edits. Requires file_path. Mutually exclusive with ranges/tool_id."},
                "ranges": {
                    "type": "array",
                    "description": "Non-empty list of [start, end] 1-indexed inclusive line ranges. Use only when no symbol name is identifiable.",
                    "items": {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2},
                },
                "label": {"type": "string", "description": "Short hint about what the snippet covers (function name, purpose, etc.)."},
                "discard": {"type": "boolean", "description": "If true, explicitly acknowledge the result doesn't need saving (satisfies enforcement without saving). Pass the matching file_path or tool_id. If 'ranges' is also provided, ranges takes precedence and the snippet is saved normally."},
            },
            "required": [],
        },
    },
    {
        "name": "GetDiff",
        "description": (
            "Show unified diffs of files modified in this turn. "
            "Returns diff text for review before deciding to revert or continue."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Optional: show diff for a specific file only. Omit to see all diffs.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "LoadProjectConfig",
        "description": (
            "Load a project's .bouzecode/ configuration (skills, MCP servers, plugins) "
            "into the current session. The system prompt is regenerated on the next turn "
            "to include the project's skills. Calls are cumulative — each new path adds "
            "to the active configuration."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the project root (must contain a .bouzecode/ directory).",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "RunPythonTest",
        "description": (
            "Run Python tests via pytest with automatic environment detection. "
            "Finds the nearest pyproject.toml, loads .env, and uses uv run pytest. "
            "Call with no targets to run all tests, or pass specific files/directories."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "targets": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Test files or directories to run. Empty or omitted = all tests.",
                },
                "parallel": {
                    "type": "string",
                    "description": "Parallelism: 'auto' (default, uses -n auto), 'off' (no xdist), or a number like '4'.",
                },
                "marker": {
                    "type": "string",
                    "description": "Pytest marker expression (-m). E.g. 'not slow'.",
                },
                "keyword": {
                    "type": "string",
                    "description": "Pytest keyword expression (-k). E.g. 'test_login'.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Max seconds before killing the test process (default 300).",
                },
                "extra_args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Additional pytest arguments passed verbatim.",
                },
                "no_sync": {
                    "type": "boolean",
                    "description": "If true, pass --no-sync to uv run (prevents venv modifications). Required for bouzecode self-testing.",
                },
            },
            "required": [],
        },
    },
]
