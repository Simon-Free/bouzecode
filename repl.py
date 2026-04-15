# [desc] Interactive REPL loop, query execution, and sentinel-dispatch state machine for bouzécode. [/desc]
"""Main REPL loop for bouzécode.

Owns the interactive read-eval-print loop, run_query turn handler, and the
sentinel-dispatch state machine that processes commands whose execution must
flow back through the REPL (voice, image, brainstorm, SSJ menu, etc.).
"""
from __future__ import annotations

import atexit
import json as _json
import os
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path

import ui.rendering
import ui.spinner
from ui.ansi import clr, info, ok, warn, err
from ui.rendering import (
    console, _RICH, stream_text, stream_thinking, flush_response,
)
from ui.spinner import (
    _start_tool_spinner, _stop_tool_spinner, _change_spinner_phrase,
)
from ui.tool_display import print_tool_start, print_tool_end, _fmt_duration


def _fmt_tok_compact(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 10_000:
        return f"{n / 1_000:.0f}K"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)

from commands import (
    COMMANDS, handle_slash, setup_readline,
    ask_permission_interactive,
    save_latest, save_progressive, _build_session_data,
    _proactive_watcher_loop, _tg_send,
    _print_background_notifications,
)
from commands.basic import _interactive_ollama_picker
from commands.brainstorm import _save_synthesis
from commands.session import _save_session_checkpoint
from commands.telegram_cmd import _tg_poll_loop
from tools.interaction import PausedForInput


def _build_turn_generator(user_input: str, state, config: dict, system_prompt: str):
    """Normal turn via run(); when `_resume_pending`, switch to resume_paused + delete pending."""
    from agent import run as _run
    cancel_check = config.get("_cancel_check")
    if config.pop("_resume_pending", False):
        from web import pending as web_pending
        from agent.loop import resume_paused
        sf = config.get("_session_file")
        pending = web_pending.load(sf) if sf else None
        if pending is not None:
            web_pending.delete(sf)
            return resume_paused(pending, user_input, state, config, system_prompt, cancel_check=cancel_check)
    return _run(user_input, state, config, system_prompt, cancel_check=cancel_check)


def _persist_pause_and_exit(pause: PausedForInput, state, config) -> None:
    """On AskUserQuestion under web IPC: save session, persist pending, signal UI, exit."""
    sf = config.get("_session_file")
    if sf:
        _save_session_checkpoint(state, sf)
        save_progressive(state, config)
        from web import pending as web_pending
        web_pending.save(sf, pause)
    from web import ipc as web_ipc
    paths = web_ipc.from_env()
    if paths is not None:
        web_ipc.write_state(
            paths,
            web_ipc.STATUS_AWAITING_INPUT,
            question=pause.question,
            options=pause.options,
            allow_freetext=pause.allow_freetext,
            turn=getattr(state, "turn_count", 0),
        )
    sys.exit(0)


_telegram_thread: threading.Thread | None = None
_telegram_stop: threading.Event = threading.Event()


def _strip_surrogates(raw: str) -> str:
    recombined = raw.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
    return recombined.encode("utf-8", "replace").decode("utf-8", "replace")


def repl(config: dict, initial_prompt: str = None):
    from config import HISTORY_FILE
    from context import build_system_prompt
    from agent import (
        AgentState, run, TextChunk, ThinkingChunk,
        ToolStart, ToolEnd, TurnDone, PermissionRequest, CheckpointReady,
    )
    from bouzecode import VERSION

    setup_readline(HISTORY_FILE)
    state = AgentState()
    verbose = config.get("verbose", False)
    config["_tg_send_callback"] = _tg_send

    import checkpoint as ckpt
    session_id = uuid.uuid4().hex[:8]
    config["_session_id"] = session_id
    ckpt.set_session(session_id)
    ckpt.cleanup_old_sessions()
    ckpt.make_snapshot(session_id, state, config, "(initial state)", tracked_edits=None)

    if not initial_prompt:
        from providers import detect_provider
        _logo_path = Path(__file__).parent / "logo.txt"
        try:
            _BOUZECODE_LOGO = _logo_path.read_text(encoding="utf-8").rstrip("\n").splitlines()
        except Exception:
            _BOUZECODE_LOGO = ["  bouz\u00e9code"]

        _GALAXY_FRAMES = ["\u25dc", "\u25dd", "\u25de", "\u25df"]
        try:
            for i in range(8):
                frame = _GALAXY_FRAMES[i % 4]
                sys.stdout.write(f"\r  {clr(frame, 'cyan', 'bold')} Initializing bouz\u00e9code...")
                sys.stdout.flush()
                time.sleep(0.12)
            sys.stdout.write(f"\r{' ' * 45}\r")
            sys.stdout.flush()
        except Exception:
            pass

        for line in _BOUZECODE_LOGO:
            print(clr(line, "cyan", "bold"))
        print()

        model = config["model"]
        pname = detect_provider(model)
        model_clr = clr(model, "cyan", "bold")
        prov_clr = clr(f"({pname})", "dim")
        pmode = clr(config.get("permission_mode", "auto"), "yellow")
        ver_clr = clr(f"v{VERSION}", "green")
        print(clr("  \u256d\u2500 ", "dim") + clr("bouz\u00e9code ", "cyan", "bold")
              + clr("(based on cheetahclaws) ", "dim") + ver_clr
              + clr(" \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u256e", "dim"))
        print(clr("  \u2502", "dim") + clr("  Model: ", "dim") + model_clr + " " + prov_clr)
        print(clr("  \u2502", "dim") + clr("  Permissions: ", "dim") + pmode)
        print(clr("  \u2502", "dim") + clr("  /model to switch \u00b7 /help for commands \u00b7 /where for session paths", "dim"))
        print(clr("  \u2570\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u256f", "dim"))
        from config import DAILY_DIR as _DAILY_DIR
        from datetime import datetime as _dt
        _today_dir = _DAILY_DIR / _dt.now().strftime("%Y-%m-%d")
        print(clr(f"  Session log \u2192 {_today_dir}", "dim"))

        active_flags = []
        if config.get("verbose"):
            active_flags.append("verbose")
        if config.get("thinking"):
            active_flags.append("thinking")
        if config.get("_proactive_enabled"):
            active_flags.append("proactive")
        if config.get("telegram_token") and config.get("telegram_chat_id"):
            active_flags.append("telegram")
        if active_flags:
            print(info(f"Active: " + " \u00b7 ".join(clr(f, "green") for f in active_flags)))
        print()

    query_lock = threading.RLock()

    def _atexit_save():
        if config.get("_session_saved"):
            return
        config["_session_saved"] = True
        save_latest("", state, config)

    atexit.register(_atexit_save)

    _in_ssh = bool(os.environ.get("SSH_CLIENT") or os.environ.get("SSH_TTY"))
    _is_dumb = (console is not None and getattr(console, "is_dumb_terminal", False))
    _rich_live_default = not _in_ssh and not _is_dumb
    ui.rendering._RICH_LIVE = _RICH and config.get("rich_live", _rich_live_default)

    config.setdefault("_proactive_enabled", False)
    config.setdefault("_proactive_interval", 300)
    config.setdefault("_last_interaction_time", time.time())
    if config.get("_proactive_thread") is None:
        t = threading.Thread(target=_proactive_watcher_loop, args=(config,), daemon=True)
        config["_proactive_thread"] = t
        t.start()

    def run_query(user_input: str, is_background: bool = False):
        nonlocal verbose
        with query_lock:
            verbose = config.get("verbose", False)
            system_prompt = build_system_prompt(config)
            if is_background and not config.get("_telegram_incoming"):
                print(clr("\n\n[Background Event Triggered]", "yellow"))
            config["_in_telegram_turn"] = config.pop("_telegram_incoming", False)
            print(clr("\n\u256d\u2500 bouz\u00e9code ", "dim") + clr("\u25cf", "green")
                  + clr(" \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500", "dim"))

            thinking_started = False
            spinner_shown = True
            _start_tool_spinner()
            _pre_tool_text = []
            _post_tool = False
            _post_tool_buf = []
            _query_timing_start = len(state.timing_entries)
            _duplicate_suppressed = False

            try:
                gen = _build_turn_generator(user_input, state, config, system_prompt)
                for event in gen:
                    if spinner_shown:
                        show_thinking = isinstance(event, ThinkingChunk) and verbose
                        if isinstance(event, TextChunk) or show_thinking or isinstance(event, ToolStart):
                            _stop_tool_spinner()
                            spinner_shown = False
                            if isinstance(event, TextChunk) and not _RICH and not _post_tool:
                                print(clr("\u2502 ", "dim"), end="", flush=True)

                    if isinstance(event, TextChunk):
                        if thinking_started:
                            print("\033[0m\n")
                            thinking_started = False
                        if _post_tool and not _duplicate_suppressed:
                            _post_tool_buf.append(event.text)
                            post_so_far = "".join(_post_tool_buf).strip()
                            pre_text = "".join(_pre_tool_text).strip()
                            if pre_text and pre_text.startswith(post_so_far):
                                if len(post_so_far) >= len(pre_text):
                                    _duplicate_suppressed = True
                                    _post_tool_buf.clear()
                                continue
                            elif post_so_far and not pre_text.startswith(post_so_far):
                                for chunk in _post_tool_buf:
                                    stream_text(chunk)
                                _post_tool_buf.clear()
                                _duplicate_suppressed = True
                                continue
                        if not _post_tool:
                            _pre_tool_text.append(event.text)
                        stream_text(event.text)
                    elif isinstance(event, ThinkingChunk):
                        if verbose:
                            if not thinking_started:
                                flush_response()
                                print(clr("  [thinking]", "dim"))
                                thinking_started = True
                            stream_thinking(event.text, verbose)
                    elif isinstance(event, ToolStart):
                        flush_response()
                        print_tool_start(event.name, event.inputs, verbose)
                    elif isinstance(event, PermissionRequest):
                        _stop_tool_spinner()
                        flush_response()
                        event.granted = ask_permission_interactive(event.description, config)
                    elif isinstance(event, ToolEnd):
                        print_tool_end(event.name, event.result, verbose, event.duration)
                        _post_tool = True
                        _post_tool_buf.clear()
                        _duplicate_suppressed = False
                        if not _RICH:
                            print(clr("\u2502 ", "dim"), end="", flush=True)
                        _change_spinner_phrase()
                        _start_tool_spinner()
                        spinner_shown = True
                    elif isinstance(event, TurnDone):
                        _stop_tool_spinner()
                        spinner_shown = False
                        last_llm = next((t for t in reversed(state.timing_entries) if t["phase"] == "llm"), None)
                        if last_llm and last_llm.get("duration", 0.0) > 0.05:
                            flush_response()
                            parts = [f"LLM {_fmt_duration(last_llm['duration'])}"]
                            ttft = last_llm.get("ttft", 0.0)
                            if ttft > 0.05:
                                parts.append(f"ttft {_fmt_duration(ttft)}")
                            thinking = last_llm.get("thinking", 0.0)
                            if thinking > 0.05:
                                parts.append(f"think {_fmt_duration(thinking)}")
                            tps = last_llm.get("tokens_per_sec", 0.0)
                            if tps > 0:
                                parts.append(f"{tps:.0f} tok/s")
                            parts.append(f"+{_fmt_tok_compact(event.input_tokens)} in")
                            parts.append(f"+{_fmt_tok_compact(event.output_tokens)} out")
                            print(clr(f"  \u23f1  {' \u00b7 '.join(parts)}", "dim"))
                    elif isinstance(event, CheckpointReady):
                        sf = config.get("_session_file")
                        if sf:
                            _save_session_checkpoint(state, sf)
                        try:
                            save_progressive(state, config)
                        except Exception:
                            pass
            except KeyboardInterrupt:
                _stop_tool_spinner()
                flush_response()
                raise
            except PausedForInput as pause:
                _stop_tool_spinner()
                flush_response()
                _persist_pause_and_exit(pause, state, config)
            except Exception as e:
                _stop_tool_spinner()
                import urllib.error
                if isinstance(e, urllib.error.HTTPError) and e.code == 404:
                    from providers import detect_provider
                    if detect_provider(config["model"]) == "ollama":
                        flush_response()
                        err(f"Ollama model '{config['model']}' not found.")
                        if _interactive_ollama_picker(config):
                            if state.messages and state.messages[-1]["role"] == "user":
                                state.messages.pop()
                            return run_query(user_input, is_background)
                        return
                raise e

            _stop_tool_spinner()
            flush_response()

            _query_entries = state.timing_entries[_query_timing_start:]
            _llm_turns = sum(1 for e in _query_entries if e["phase"] == "llm")
            _tool_entries = [e for e in _query_entries if e["phase"] != "llm"]
            if _query_entries:
                _llm_total = sum(e["duration"] for e in _query_entries if e["phase"] == "llm")
                _tool_total = sum(e["duration"] for e in _tool_entries)
                _think_total = sum(e.get("thinking", 0.0) for e in _query_entries if e["phase"] == "llm")
                _q_last_in = next((e.get("in_tokens", 0) for e in reversed(_query_entries) if e["phase"] == "llm"), 0)
                _q_out = sum(e.get("out_tokens", 0) for e in _query_entries if e["phase"] == "llm")
                _q_distinct = state.distinct_base + _q_last_in
                if _llm_turns > 1 or _tool_entries:
                    parts = []
                    if _think_total > 0.05:
                        parts.append(f"thinking {_fmt_duration(_think_total)}")
                    parts.append(f"LLM {_fmt_duration(_llm_total)}")
                    if _tool_total > 0.05:
                        parts.append(f"tools {_fmt_duration(_tool_total)}")
                    print(clr(f"  {' | '.join(parts)}", "dim"))
                tok_parts = [f"{_q_distinct:,} distinct in", f"{_q_out:,} out", f"{state.total_input_tokens:,} cumulated in"]
                _last_followup_saved = next(
                    (e.get("tokens_est_saved", 0) for e in reversed(getattr(state, "compaction_log", []))
                     if e.get("event") == "followup_compact" and e.get("turn") == state.turn_count),
                    0,
                )
                if _last_followup_saved > 0:
                    tok_parts.append(f"~{_last_followup_saved:,} tokens saved (follow-up compact)")
                print(clr(f"  {' | '.join(tok_parts)}", "dim"))

            print(clr("\u2570\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500", "dim"))
            print()

            if is_background:
                print(clr(f"\n[{Path.cwd().name}] \u00bb ", "yellow"), end="", flush=True)
                is_tg_turn = config.get("_in_telegram_turn", False)
                ttok = config.get("telegram_token")
                tchat = config.get("telegram_chat_id")
                if not is_tg_turn and ttok and tchat:
                    if state.messages and state.messages[-1].get("role") == "assistant":
                        ans_content = state.messages[-1].get("content", "")
                        if isinstance(ans_content, list):
                            parts = [b["text"] if isinstance(b, dict) else str(b)
                                     for b in ans_content
                                     if (isinstance(b, dict) and b.get("type") == "text") or isinstance(b, str)]
                            ans_content = "\n".join(parts)
                        if ans_content:
                            _tg_send(ttok, tchat, ans_content)

        sys.stdout.flush()
        sys.stderr.flush()

        try:
            from tools import drain_pending_questions
            drain_pending_questions(config)
        except Exception as _drain_err:
            print(clr(f"\n  \u2717 drain_pending_questions failed: {type(_drain_err).__name__}: {_drain_err}", "red"))
            print(clr(traceback.format_exc().rstrip(), "dim"))

        try:
            tracked = ckpt.get_tracked_edits()
            last_snaps = ckpt.list_snapshots(session_id)
            skip = False
            if not tracked and last_snaps:
                if len(state.messages) == last_snaps[-1].get("message_index", -1):
                    skip = True
            if not skip:
                ckpt.make_snapshot(session_id, state, config, user_input, tracked_edits=tracked)
            ckpt.reset_tracked()
        except Exception as _ckpt_err:
            if os.environ.get("BOUZECODE_DEBUG_POST_TURN"):
                print(clr(f"\n  \u2717 checkpoint failed: {type(_ckpt_err).__name__}: {_ckpt_err}", "red"))
                print(clr(traceback.format_exc().rstrip(), "dim"))

        sf = config.get("_session_file")
        if sf:
            _save_session_checkpoint(state, sf)

        try:
            save_progressive(state, config)
        except Exception:
            pass

        config["_last_interaction_time"] = time.time()

    config["_run_query_callback"] = lambda msg: run_query(msg, is_background=True)

    def _handle_slash_from_telegram(line: str):
        result = handle_slash(line, state, config)
        if not isinstance(result, tuple):
            return "simple"
        if result[0] == "__brainstorm__":
            _, brain_prompt, brain_out_file = result
            run_query(brain_prompt)
            _save_synthesis(state, brain_out_file)
            _todo_path = str(Path(brain_out_file).parent / "todo_list.txt")
            run_query(
                f"Based on the Master Plan you just synthesized, generate a todo list file at {_todo_path}. "
                "Format: one task per line, each starting with '- [ ] '. "
                "Order by priority. Include ALL actionable items from the plan. "
                "Use the Write tool to create the file. Do NOT explain, just write the file now."
            )
        elif result[0] == "__worker__":
            _, worker_tasks = result
            for i, (line_idx, task_text, prompt) in enumerate(worker_tasks):
                print(clr(f"\n  \u2500\u2500 Worker ({i+1}/{len(worker_tasks)}): {task_text} \u2500\u2500", "yellow"))
                run_query(prompt)
        return "query"

    config["_handle_slash_callback"] = _handle_slash_from_telegram

    global _telegram_thread, _telegram_stop
    if config.get("telegram_token") and config.get("telegram_chat_id"):
        if not (_telegram_thread and _telegram_thread.is_alive()):
            config["_state"] = state
            _telegram_stop = threading.Event()
            _telegram_thread = threading.Thread(
                target=_tg_poll_loop,
                args=(config["telegram_token"], config["telegram_chat_id"], config),
                daemon=True,
            )
            _telegram_thread.start()

    _ctrl_c_times = []

    def _track_ctrl_c():
        now = time.time()
        _ctrl_c_times.append(now)
        _ctrl_c_times[:] = [t for t in _ctrl_c_times if now - t <= 2.0]
        if len(_ctrl_c_times) >= 3:
            _stop_tool_spinner()
            try:
                save_progressive(state, config)
            except Exception:
                pass
            print(clr("\n\n  Force quit (3x Ctrl+C).", "red", "bold"))
            os._exit(1)
        return False

    resume_path = config.get("_resume_from")
    if resume_path and Path(resume_path).exists():
        _resumed = _json.loads(Path(resume_path).read_text(encoding="utf-8"))
        state.messages = _resumed.get("messages", [])
        state.turn_count = _resumed.get("turn_count", 0)
        state.total_input_tokens = _resumed.get("total_input_tokens", 0)
        state.total_output_tokens = _resumed.get("total_output_tokens", 0)
        state.total_cache_read_tokens = _resumed.get("total_cache_read_tokens", 0)
        state.total_cache_creation_tokens = _resumed.get("total_cache_creation_tokens", 0)
        state.distinct_base = _resumed.get("distinct_base", 0)
        if not initial_prompt:
            initial_prompt = "Continue."

    if initial_prompt:
        web_agent_dir = config.get("_web_agent_dir")
        if web_agent_dir:
            from web import ipc as _ipc
            _ipc_paths = _ipc.from_dir(web_agent_dir)
            config["_cancel_check"] = lambda: _ipc.consume_cancel(_ipc_paths)
            if config.get("_resume_pending"):
                run_query(initial_prompt)
                sys.stdout.flush()
                sys.stderr.flush()
                os._exit(0)
            _ipc.run_agent_event_loop(initial_prompt, run_query, _ipc_paths)
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(0)
        try:
            run_query(initial_prompt)
        except KeyboardInterrupt:
            _track_ctrl_c()
            print()
        plan_path = config.get("_plan_output")
        if plan_path and state.messages:
            for msg in reversed(state.messages):
                if msg.get("role") == "assistant":
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        content = "\n".join(
                            b["text"] for b in content
                            if isinstance(b, dict) and b.get("type") == "text"
                        )
                    if content:
                        Path(plan_path).write_text(content, encoding="utf-8")
                    break
        return

    from paste_input import read_input_with_paste_blocks as _paste_input

    def _read_input(prompt: str) -> str:
        raw = _paste_input(prompt) if sys.stdin.isatty() else input(prompt)
        return _strip_surrogates(raw)

    from repl_sentinels import process_sentinel_result

    while True:
        try:
            _print_background_notifications()
        except Exception as _bg_err:
            print(clr(f"\n  \u2717 background-notifications failed: {type(_bg_err).__name__}: {_bg_err}", "red"))
            print(clr(traceback.format_exc().rstrip(), "dim"))
        try:
            cwd_short = Path.cwd().name
            prompt = clr(f"\n[{cwd_short}] ", "dim") + clr("\u00bb ", "cyan", "bold")
            sys.stdout.flush()
            user_input = _read_input(prompt)
        except KeyboardInterrupt:
            print()
            _track_ctrl_c()
            print(clr("  (Ctrl+C \u2014 press 3\u00d7 in 2s to quit)", "yellow"))
            continue
        except EOFError:
            print()
            if sys.stdin.isatty():
                continue
            try:
                config["_session_saved"] = True
                save_latest("", state, config)
            except Exception as e:
                warn(f"Auto-save failed on exit: {e}")
            ok("Goodbye!")
            sys.exit(0)

        if not user_input:
            continue

        result = handle_slash(user_input, state, config)
        if isinstance(result, tuple):
            process_sentinel_result(result, state, config, run_query, _track_ctrl_c)
            continue
        if result:
            continue

        try:
            run_query(user_input)
        except KeyboardInterrupt:
            _track_ctrl_c()
            print(clr("\n  (Ctrl+C detected \u2014 turn cancelled. Press Ctrl+C 3\u00d7 in 2s to force-quit.)", "yellow"))
        except SystemExit:
            raise
        except Exception as e:
            _stop_tool_spinner()
            print(clr(f"\n  \u2717 Turn aborted due to an unhandled error: {type(e).__name__}: {e}", "red", "bold"))
            print(clr("  \u2500\u2500 traceback \u2500\u2500", "dim"))
            print(clr(traceback.format_exc().rstrip(), "dim"))
            print(clr("  REPL is still alive. You can retry or correct the input.", "yellow"))
