# [desc] JSON schema definitions for tools exposed to the Claude API. [/desc]
"""Tool JSON schemas sent to the Claude API."""
import platform as _platform

_BASH_BASE_DESCRIPTION = (
    "Execute a shell command. Returns stdout+stderr. Stateless (no cd persistence)."
)
# Rapport docs/reduction_tokens §2.1 : 5 tours perdus à écrire une sonde puis la lancer au tour
# suivant. Le heredoc marche tel quel sous Linux/macOS (pas sous PowerShell).
_SONDE_EN_UN_APPEL = (
    " Une sonde jetable s'écrit ET s'exécute dans ce même appel : `python3 - <<'EOF'` … `EOF` "
    "(ou Write(temp=True) puis Bash avec depends_on, dans le même lot)."
)

# Envoyé SEULEMENT sous Windows : sous Linux ce paragraphe coûtait des tokens à chaque appel
# et invitait le modèle à écrire du PowerShell (audit du 2026-09-24).
_WINDOWS_BASH_HINTS = """ On Windows, commands are executed via PowerShell (auto-encoded as Base64), so ALWAYS write PowerShell-compatible syntax (e.g. Get-Content, Get-ChildItem, $env:VAR).
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
- Commit messages: NEVER `git commit -m "..."` containing `$` or backticks (PowerShell silently replaces `$x` by nothing and `` `t `` by a TAB). Write the message with Write(temp=True), then `git commit -F <path>`. A bash heredoc (`<<'EOF'`) does not exist in PowerShell and is refused.
- Multi-line PowerShell runs fine inline: a large/multi-line command is auto-spilled to a temp .ps1 and launched via -EncodedCommand, so there is no command-length limit and no quoting hassle. Just pass it in `command`."""

_BASH_DESCRIPTION = (
    _BASH_BASE_DESCRIPTION + _WINDOWS_BASH_HINTS
    if _platform.system() == "Windows"
    else _BASH_BASE_DESCRIPTION + _SONDE_EN_UN_APPEL
)

TOOL_SCHEMAS = [
    {
        "name": "Read",
        "description": (
            "Read a file's contents. Returns content with line numbers "
            "(format: 'N\\tline'). Use limit/offset for chunks, or symbol='name' "
            "to read a specific function/class/method (Python, JS/TS). Over 300 lines "
            "without limit/offset/symbol: returns the file's outline (symbols + line "
            "numbers) and its first 120 lines. An image returns one line with its path: "
            "look at it with ImageQuestion."
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
                "temp":      {"type": "boolean", "description": "If true, write to an ephemeral scratch file OUTSIDE the git worktree (never trackable/committable, auto-destroyed at session end). Use for throwaway working files: extraction dumps, captured fixtures, timelines. Read reads it back transparently by the same file_path."},
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
                "temp":        {"type": "boolean", "description": "If true, edit the ephemeral scratch file (temp=True Write) addressed by this file_path, outside the git worktree."},
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
                "timeout": {"type": "integer", "description": "Secondes (défaut 180, porté à l'attente écrite dans la commande si elle est plus longue ; 300-900 pour installs et builds ; pytest est refusé ici : RunPythonTest)."},
                "deferred": {"type": "boolean", "description": "Exécute APRÈS FinalAnswer (commande > 3 min : suite complète, scan) ; tu n'es réveillé que si elle échoue."},
                "background": {"type": "boolean", "description": "Lance sans bloquer et rend aussitôt un bash_id ; sert aux process qu'on laisse tourner pendant qu'on fait autre chose (serveur, watcher). Une commande dont on attend la fin (build, publication, install de quelques minutes) se lance plutôt au premier plan avec un `timeout` adapté ; sinon, attends-la avec BashOutput(wait_s=…)."},
            },
            "required": ["command"],
        },
    },
    {
        "name": "BashOutput",
        "description": (
            "Lit la sortie (stdout+stderr) d'une commande lancee avec Bash(background=true), "
            "depuis la derniere lecture, avec son statut ([running] / [exited code=N]). "
            "Pour attendre la suite au lieu de relire a chaque tour, passe wait_s : l'appel "
            "rend des qu'une sortie arrive, que le process se termine, ou au bout de wait_s. "
            "Mets kill=true pour arreter le process et tout son arbre. "
            "Read-only : ne demande jamais de permission."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "bash_id": {"type": "string", "description": "L'id retourne par Bash(background=true)."},
                "kill": {"type": "boolean", "description": "Si true, tue le process (et son arbre) puis renvoie la sortie restante."},
                "wait_s": {"type": "integer", "description": "Secondes d'attente max (0 par defaut = rendu immediat, plafond 600) : rend a la premiere sortie nouvelle, a la fin du process, ou a l'expiration."},
                "until_exit": {"type": "boolean", "description": "Avec wait_s, ignore la sortie intermediaire et n'attend que la fin du process (ou wait_s ; 600 s si wait_s absent). Pour un script qui affiche sa progression."},
            },
            "required": ["bash_id"],
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
            "Ajoute du texte à ta note de travail : append-only, relue en entier à chaque tour, "
            "seule mémoire qui survit. N'écris QUE le delta de ce tour : fait mesuré, décision + "
            "pourquoi, piste écartée + pourquoi, prochaine étape. Jamais la mission, la todolist "
            "entière ni une décision déjà notée ; pour cocher un élément, écris seulement "
            "« [x] <élément> ». Jamais une ligne déjà visible dans un snippet : cite-le (fichier "
            "+ lignes, ou symbole). Un tour sans rien de neuf : une ligne courte suffit. Le "
            "harnais préfixe chaque ajout par « ### T<n> » (numéro de tour réel) et signale un "
            "ajout déjà présent dans la note. Pour garder du code, utilise Snippet."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Le delta du tour, en markdown."},
            },
            "required": ["content"],
        },
    },
    {
        "name": "FinalAnswer",
        "description": (
            "Clôt la session (signal de fin), dans le même lot que ta dernière Methodology, "
            "quand la tâche est finie (tests verts, todolist entièrement [x]) ou ta réponse "
            "prête. Aucun tour ne suit : `answer` se suffit à lui-même (résultat, fichiers "
            "touchés, preuves de validation)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "answer": {
                    "type": "string",
                    "description": (
                        "The complete final answer/result delivered to the user. Après une "
                        "clôture refusée ou suspendue, OMETS-LE si le texte reste juste : le "
                        "harnais reprend celui de ta tentative (recap et parcours_verifies omis aussi)."
                    ),
                },
                "taches_terminees": {
                    "type": "array",
                    "description": (
                        "Obligatoire, même vide ([]), sauf pour le profil assistant de bureau "
                        "(qui tient la TODO via les outils Taches) : ce qui est fait, une ligne "
                        "par tâche. Hors assistant, l'omettre refuse la clôture. Sous-agent : "
                        "tout aussi obligatoire, mais la liste va dans le rapport rendu à ton "
                        "parent, jamais dans la TODO du Bureau."
                    ),
                    "items": {"type": "string"},
                },
                "taches_restantes": {
                    "type": "array",
                    "description": (
                        "Obligatoire, même vide ([]), sauf pour le profil assistant de bureau "
                        "(optionnel ; fourni, il est pris en compte) : ce qui reste, un objet "
                        "par tâche, écrit "
                        "en entier — `titre` (la ligne courte), `corps` optionnel (brief long : "
                        "contexte, chemins, critère d'acceptation), chantier via `macro_id` sinon "
                        "`macro_titre` (optionnel), `decision=true` si un humain doit trancher "
                        "(avec `options` quand tu sais les nommer). Sous-agent : tout aussi "
                        "obligatoire, mais rien n'est créé dans la TODO du Bureau : la liste va "
                        "dans le rapport rendu à ton parent, qui consolide."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "macro_id": {"type": "string"},
                            "macro_titre": {"type": "string"},
                            "titre": {"type": "string"},
                            "corps": {"type": "string"},
                            "decision": {"type": "boolean"},
                            "options": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "key": {"type": "string", "description": "Short stable key, e.g. 'garder_coalesce'."},
                                        "label": {"type": "string", "description": "Wording shown to the user."},
                                    },
                                    "required": ["key", "label"],
                                },
                            },
                        },
                        "required": ["titre"],
                    },
                },
                "parcours_verifies": {
                    "type": "array",
                    "description": (
                        "Obligatoire si tu as écrit une interface (html/css/js…) : un objet par "
                        "exigence de la demande — le parcours joué comme un utilisateur (ex. "
                        "afficher → éditer → enregistrer → relire), l'`appel` qui le prouve "
                        "(le tool_call_alias ou l'id de l'appel EXÉCUTÉ, vert, après ta dernière "
                        "modification d'interface ; plusieurs si besoin, ex. [\"clic_edit\", "
                        "\"snap_apres\"]) et sa `preuve` (ce que cet appel montre). Donne un "
                        "tool_call_alias à tes appels de preuve pour pouvoir les désigner. Les "
                        "appels des tours PRÉCÉDENTS comptent. Le harnais résout chaque `appel` "
                        "dans tes appels réels ; sans `appel`, il recoupe le texte de `preuve`."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "exigence": {"type": "string"},
                            "parcours": {"type": "string"},
                            "preuve": {
                                "type": "string",
                                "description": "Ce que l'appel montre (sortie, état relu). "
                                               "Sans `appel` : la commande exacte exécutée.",
                            },
                            "appel": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "tool_call_alias (ou id) des appels qui prouvent "
                                               "ce parcours, ex. [\"e2e\"] ou [\"clic\", "
                                               "\"snap\"] pour geste + constat.",
                            },
                        },
                        "required": ["exigence", "parcours", "preuve"],
                    },
                },
                "recap": {
                    "type": "object",
                    "description": (
                        "Obligatoire pour un profil de code (clôture refusée sans lui) : "
                        "symptoms (bug ou besoin vu par l'utilisateur, sans jargon), explanation "
                        "(cause ou plan, vulgarisé), tests (combien, quel niveau, verts ?), changes "
                        "(fichiers touchés dans l'ordre du récit, non vide). Pas de diff : le serveur "
                        "les assemble. Un point que tu ne peux pas trancher va dans "
                        "`taches_restantes` avec decision=true, pas ici."
                    ),
                    "properties": {
                        "symptoms": {"type": "string"},
                        "explanation": {"type": "string"},
                        "tests": {"type": "string"},
                        "changes": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "file": {"type": "string", "description": "Repo-relative path."},
                                    "summary": {"type": "string", "description": "What this file brings, action verb first (≤200 chars)."},
                                },
                                "required": ["file", "summary"],
                            },
                        },
                    },
                },
                "related_files": {
                    "type": "array",
                    "description": (
                        "Fichiers produits ou à consulter par l'humain (rapport .html, .pptx, "
                        ".pbix, export…) : chemins absolus, cliquables dans bouzeui. Renseigne-le "
                        "dès que tu produis un livrable consultable : l'humain l'ouvre au lieu "
                        "de relire le code."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Chemin ABSOLU du fichier."},
                            "label": {"type": "string", "description": "Libellé court affiché."},
                            "kind": {"type": "string", "description": "Type : rapport, présentation, export, tableau de bord…"},
                        },
                        "required": ["path"],
                    },
                },
            },
            #  `answer` n'est plus requis par le registre : omis, il reprend la tentative
            #  refusée (agent/cloture_reprise.py) ; vide sans tentative, `_final_answer` refuse.
            #  taches_terminees / taches_restantes ne sont plus `required` au registre :
            #  c'est validate_close qui les exige, selon le profil (require_taches ;
            #  levé pour bureau-assistant, qui tient déjà la TODO via les outils Taches).
            "required": [],
        },
    },
    {
        "name": "Snippet",
        "description": (
            "Fige dans ta note une région d'un résultat, qui sinon meurt au tour suivant. "
            "Obligatoire au tour qui suit chaque résultat marqué « A SNIPPETER » "
            "(Read/Skill, Edit/Write longs, LoadProjectConfig, FindCode) : garde les régions "
            "utiles, ou `discard=true`. `symbol=` (re-résolu à chaque tour, insensible aux Edit) "
            "de préférence à `ranges=`. Clé : `file_path` pour un marqueur `id: file=…`, "
            "`tool_id` pour `id: tool_id=…` (plages 1..N sur le bloc). Un appel par région."
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
            "Entrée dans un projet, une fois par projet, avant d'y travailler : rend ses skills "
            "trouvables par SkillResearch, branche ses outils, dit comment parcourir son code. Hors projet, "
            "liste les projets qu'il contient. Snippet le résultat, sinon il est perdu au tour "
            "suivant."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the directory you are about to work in.",
                },
                "cd": {
                    "type": "boolean",
                    "description": (
                        "Déplace ton cwd dans ce dossier pour de bon (Bash, chemins relatifs). "
                        "Requis si ce n'est pas ton dossier de départ, AVANT "
                        "Environment(action='worktree'|'venv') qui provisionne depuis le cwd. "
                        "Ne t'isole pas pour autant."
                    ),
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "RunPythonTest",
        "description": (
            "Seul moyen de lancer pytest (le Bash le refuse). Sans `targets` : les tests impactés "
            "par ta branche (git diff depuis develop, testmon, `.bouzecode/tests.yaml`) ; "
            "`targets` pour cibler. Jamais la suite complète : un build nightly la joue sur "
            "develop et alimente la comparaison. Run impacté : les échecs sont rejoués sur "
            "develop ; ceux marqués pre-existing on base ne sont pas les tiens, ne corrige que "
            "les NEW. Échecs identiques regroupés, remède pour les erreurs d'environnement, "
            "chemin de la sortie complète. `show` pour en voir plus ; `wait=false` rend aussitôt "
            "un job_id, à suivre avec TestStatus."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "targets": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Fichiers, dossiers ou motifs (`tests/test_x*.py`) de test. Absent : tests impactés.",
                },
                "parallel": {
                    "type": "string",
                    "description": "Workers xdist : '4' (défaut), '2' ou 'off'. 'auto' refusé.",
                },
                "marker": {
                    "type": "string",
                    "description": "Expression -m. Remplace le -m des addopts du projet, qui peut écarter des marqueurs (ex. network) : marker='network' les lance.",
                },
                "keyword": {
                    "type": "string",
                    "description": "Pytest keyword expression (-k). E.g. 'test_login'.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Max seconds before killing the test process (default 300). Un test seul est tué à 30 s (60 s navigateur, 300 s si lent).",
                },
                "extra_args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Additional pytest arguments passed verbatim.",
                },
                "no_sync": {
                    "type": "boolean",
                    "description": "Sans effet (conservé) : un venv existant est exécuté tel quel, jamais synchronisé.",
                },
                "testmon": {
                    "type": "boolean",
                    "description": "pytest-testmon : 1er passage complet (construit sa base), puis seulement les tests affectés. Incompatible avec `marker` (borne avec `targets`) ; aveugle aux .html/.css/.js et fichiers de données.",
                },
                "show": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["warnings", "durations", "passed", "full"]},
                    "description": "Détail en plus du minimal : 'warnings' (tous, dédoublonnés), 'durations' (15 plus lents), 'passed' (tests passés), 'full' (sortie brute, tête+queue).",
                },
                "wait": {
                    "type": "boolean",
                    "description": "false : rend aussitôt un job_id (le run attend son tour dans la file de la machine) ; suis-le avec TestStatus.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "TestStatus",
        "description": (
            "État d'un run lancé par RunPythonTest(wait=false) : position en file ou n/N, échecs "
            "avec extrait dès qu'ils arrivent, test le plus long en cours, puis le même rapport "
            "final que RunPythonTest (NEW / pre-existing pour un run impacté)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
                "wait_s": {
                    "type": "integer",
                    "description": "Attend jusqu'à la fin, un nouvel échec ou ce délai (max 600).",
                },
                "cancel": {"type": "boolean", "description": "Annule le run."},
            },
            "required": ["job_id"],
        },
    },
]
