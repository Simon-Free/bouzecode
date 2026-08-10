# [desc] Re-exports all tool submodules and triggers side-effect registrations for the tools package. [/desc]
"""Tools package — split from the original monolithic tools.py."""

from .state import (
    _read_files, _file_mtime, _file_content_cache,
    _track_read, _stale_edit_warning, _update_mtime_after_write,
    clear_file_state, _tg_thread_local, _is_in_tg_turn,
)
from .schemas import TOOL_SCHEMAS
from .interaction import (
    _ask_user_question, ask_input_interactive,
    drain_pending_questions, _sleeptimer,
)
from .ops.file_ops import generate_unified_diff, maybe_truncate_diff, _read, _write, _edit
from .ops.shell_search import _is_safe_bash, _kill_proc_tree, _bash, _glob, _grep, _has_rg
from .ops.web_ops import _webfetch, _websearch
from .ops.notebook_diagnostics import (
    _parse_cell_id, _notebook_edit, _detect_language, _run_quietly, _get_diagnostics,
)
from .ops.project_config import _load_project_config
from .plan_mode import _enter_plan_mode, _exit_plan_mode

from . import registration  # noqa: F401 — trigger side-effect registrations

from .registration import execute_tool
