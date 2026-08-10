# [desc] Background Bash process registry: launch detached, poll output, kill. [/desc]
"""Run Bash commands detached so a long/persistent process (Flask server, watcher,
build) doesn't block the turn. A reader thread drains stdout into a buffer so the
OS pipe never fills; BashOutput returns the output produced since the last poll."""
import contextlib
import os
import subprocess
import sys
import threading

_bg_procs: dict[str, dict] = {}
_bg_lock = threading.Lock()
_bg_counter = 0


def _new_id() -> str:
    global _bg_counter
    with _bg_lock:
        _bg_counter += 1
        return f"bg_{_bg_counter}"


def _drain(proc: subprocess.Popen, entry: dict) -> None:
    """Continuously move the process's combined output into entry['buf']."""
    for line in proc.stdout:
        with entry["lock"]:
            entry["buf"].append(line)
    proc.stdout.close()


def start_background(command: str) -> str:
    """Launch `command` detached and return its bash_id for later polling."""
    from .shell_search import (
        _build_popen_command, _get_env_with_user_vars, spill_or_refuse_inline_python,
    )
    command, note = spill_or_refuse_inline_python(command)
    if not command:
        return note
    popen_cmd, shell, temp_path = _build_popen_command(command)
    kwargs = dict(
        shell=shell, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8",
        errors="replace", cwd=os.getcwd(), env=_get_env_with_user_vars(),
    )
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(popen_cmd, **kwargs)
    entry = {"proc": proc, "buf": [], "offset": 0,
             "lock": threading.Lock(), "temp": temp_path}
    thread = threading.Thread(target=_drain, args=(proc, entry), daemon=True)
    entry["thread"] = thread
    thread.start()
    bash_id = _new_id()
    with _bg_lock:
        _bg_procs[bash_id] = entry
    return note + (
        f"Background started: bash_id={bash_id} (pid={proc.pid}).\n"
        f"Read its output with BashOutput(bash_id=\"{bash_id}\"); "
        f"stop it with BashOutput(bash_id=\"{bash_id}\", kill=true)."
    )


def _read_new(entry: dict) -> str:
    with entry["lock"]:
        chunk = "".join(entry["buf"][entry["offset"]:])
        entry["offset"] = len(entry["buf"])
    return chunk


def _finalize(bash_id: str, entry: dict) -> None:
    temp = entry.get("temp")
    if temp:
        with contextlib.suppress(OSError):
            os.remove(temp)
    with _bg_lock:
        _bg_procs.pop(bash_id, None)


def bash_output(bash_id: str, kill: bool = False) -> str:
    """Return [status] + output since the last poll. kill=True stops the process."""
    from .truncation import truncate_tool_output
    entry = _bg_procs.get(bash_id)
    if entry is None:
        return f"Error: unknown bash_id={bash_id!r} (already finished and cleared?)."
    proc = entry["proc"]
    if kill:
        from .shell_search import _kill_proc_tree
        if proc.poll() is None:
            _kill_proc_tree(proc.pid)
            proc.wait()
        entry["thread"].join(timeout=2)
        body = _read_new(entry).strip() or "(no output)"
        _finalize(bash_id, entry)
        return truncate_tool_output(f"[killed] bash_id={bash_id}\n{body}", "Bash")
    rc = proc.poll()
    if rc is not None:
        entry["thread"].join(timeout=2)
    body = _read_new(entry).strip() or "(no new output)"
    if rc is None:
        return truncate_tool_output(f"[running] bash_id={bash_id}\n{body}", "Bash")
    _finalize(bash_id, entry)
    return truncate_tool_output(f"[exited code={rc}] bash_id={bash_id}\n{body}", "Bash")
