# [desc] Re-exports all tool submodules and triggers side-effect registrations for the tools package. [/desc]
"""Tools package — split from the original monolithic tools.py."""

from tools.state import (
    _read_files, _file_mtime, _file_content_cache,
    _track_read, _stale_edit_warning, _update_mtime_after_write,
    clear_file_state, _tg_thread_local, _is_in_tg_turn,
)
from tools.schemas import TOOL_SCHEMAS
from tools.interaction import (
    _ask_user_question, ask_input_interactive,
    drain_pending_questions, _sleeptimer,
)
from tools.ops.file_ops import generate_unified_diff, maybe_truncate_diff, _read, _write, _edit
from tools.ops.shell_search import _is_safe_bash, _kill_proc_tree, _bash, _glob, _grep, _has_rg
from tools.ops.web_ops import _webfetch, _websearch
from tools.ops.notebook_diagnostics import (
    _parse_cell_id, _notebook_edit, _detect_language, _run_quietly, _get_diagnostics,
)
from tools.plan_mode import _enter_plan_mode, _exit_plan_mode

import tools.registration  # noqa: F401 — trigger side-effect registrations

from tools.registration import execute_tool
