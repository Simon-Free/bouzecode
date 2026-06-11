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

from . import rendering
from . import spinner
from .ansi import clr, info, ok, warn, err
from bouzecode.backend.agent.thinking_parser import ThinkingStreamParser, LoopDetector
from .rendering import (
    console, _RICH, stream_text, stream_thinking, flush_response,
    end_thinking_block,
)
from .spinner import (
    _start_tool_spinner, _stop_tool_spinner, _change_spinner_phrase,
)
from .tool_display import print_tool_start, print_tool_end, _fmt_duration

from bouzecode.backend.commands import (
    COMMANDS, handle_slash, setup_readline,
    ask_permission_interactive,
    save_latest, save_progressive, _build_session_data,
    _proactive_watcher_loop, _tg_send,
    _print_background_notifications,
)

from bouzecode.backend.commands.session import _save_session_checkpoint
from bouzecode.backend.commands.telegram_cmd import _tg_poll_loop
from bouzecode.backend.tools.interaction import PausedForInput


def _fmt_tok_compact(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 10_000:
        return f"{n / 1_000:.0f}K"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _build_turn_generator(user_input: str, state, config: dict, system_prompt: str):
    """Normal turn via run(); when `_resume_pending`, switch to resume_paused + delete pending."""
    from bouzecode.backend.agent import run as _run
    cancel_check = config.get("_cancel_check")
    if config.pop("_resume_pending", False):
        from ..web import pending as web_pending
        from bouzecode.backend.agent.loop import resume_paused
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
        _save_session_checkpoint(state, sf, config.get("_session_id"), config.get("_session_path"))
        save_progressive(state, config)
        from ..web import pending as web_pending
        web_pending.save(sf, pause)
    from ..web import ipc as web_ipc
    paths = web_ipc.from_env()
    if paths is not None:
        status = "awaiting_plan_validation" if pause.is_plan_validation else web_ipc.STATUS_AWAITING_INPUT
        web_ipc.write_state(
            paths,
            status,
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
    from bouzecode.backend.core.config import HISTORY_FILE
    from bouzecode.backend.core.context import build_system_prompt
    from bouzecode.backend.agent import (
        AgentState, run, TextChunk, ThinkingChunk, ToolCallParsed, ToolIdRemap,
        ToolStart, ToolEnd, TurnDone, PermissionRequest, CheckpointReady,
        EnforcementWarning, RecoveryFailed,
    )
    from bouzecode import VERSION

    setup_readline(HISTORY_FILE)
    state = AgentState()
    verbose = config.get("verbose", False)
    config["_tg_send_callback"] = _tg_send

    from bouzecode.backend import checkpoint as ckpt
    session_id = uuid.uuid4().hex[:8]
    config["_session_id"] = session_id
    ckpt.set_session(session_id)
    ckpt.cleanup_old_sessions()
    ckpt.make_snapshot(session_id, state, config, "(initial state)", tracked_edits=None)

    if not initial_prompt and not config.get("_web_agent_dir"):
        from bouzecode.backend.agent.providers import detect_provider
        try:
            from bouzecode.backend.core._embedded_data import LOGO_TEXT
            _BOUZECODE_LOGO = LOGO_TEXT.rstrip("\n").splitlines()
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
        from bouzecode.backend.core.config import DAILY_DIR as _DAILY_DIR
        from datetime import datetime as _dt
        _today_dir = _DAILY_DIR / _dt.now().strftime("%Y-%m-%d")
        print(clr(f"  Session log \u2192 {_today_dir}", "dim"))

        active_flags = []
        if config.get("verbose"):
            active_flags.append("verbose")
        if config.get("thinking"):
            mode = config.get("thinking_mode", "extended")
            active_flags.append(f"thinking:{mode}")
        if config.get("_proactive_enabled"):
            active_flags.append("proactive")
        if config.get("telegram_token") and config.get("telegram_chat_id"):
            active_flags.append("telegram")
        if active_flags:
            print(info(f"Active: " + " · ".join(clr(f, "green") for f in active_flags)))
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
    rendering._RICH_LIVE = _RICH and config.get("rich_live", _rich_live_default)

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
            _thinking_chunks: list[str] = []
            _thinking_parser = ThinkingStreamParser()
            _loop_detector = LoopDetector()
            _shown_inline_ids: set[str] = set()
            _query_timing_start = len(state.timing_entries)
            _duplicate_suppressed = False

            try:
                gen = _build_turn_generator(user_input, state, config, system_prompt)
                for event in gen:
                    if spinner_shown:
                        show_thinking = isinstance(event, ThinkingChunk)
                        if isinstance(event, (TextChunk, ToolStart, ToolCallParsed, ToolEnd, ToolIdRemap)) or show_thinking:
                            _stop_tool_spinner()
                            spinner_shown = False
                            if isinstance(event, TextChunk) and not _RICH and not _post_tool:
                                print(clr("\u2502 ", "dim"), end="", flush=True)

                    if isinstance(event, TextChunk):
                        _cancel = False
                        for _kind, _content in _thinking_parser.feed(event.text):
                            if _kind == "thinking":
                                if not thinking_started:
                                    flush_response()
                                    print("\033[3m" + clr("  [thinking]", "dim"))
                                    thinking_started = True
                                _thinking_chunks.append(_content)
                                stream_thinking(_content)
                                if _loop_detector.feed(_content):
                                    flush_response()
                                    print(warn("\n[Loop detected in thinking - cancelling turn]"))
                                    gen.close()
                                    _cancel = True
                                    break
                            else:
                                if thinking_started:
                                    end_thinking_block()
                                    print()
                                    thinking_started = False
                                if _post_tool and not _duplicate_suppressed:
                                    _post_tool_buf.append(_content)
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
                                    _pre_tool_text.append(_content)
                                stream_text(_content)
                        if _cancel:
                            break
                    elif isinstance(event, ThinkingChunk):
                        _thinking_chunks.append(event.text)
                        if not thinking_started:
                            flush_response()
                            print("\033[3m" + clr("  [thinking]", "dim"))
                            thinking_started = True
                        stream_thinking(event.text)
                        if _loop_detector.feed(event.text):
                            flush_response()
                            print(warn("\n[Loop detected in thinking - cancelling turn]"))
                            gen.close()
                            break
                    elif isinstance(event, ToolCallParsed):
                        flush_response()
                        print_tool_start(event.name, event.inputs, verbose)
                        _shown_inline_ids.add(event.tool_id)
                    elif isinstance(event, ToolIdRemap):
                        for old_id, new_id in event.remap.items():
                            if old_id in _shown_inline_ids:
                                _shown_inline_ids.discard(old_id)
                                _shown_inline_ids.add(new_id)
                    elif isinstance(event, ToolStart):
                        if event.tool_id not in _shown_inline_ids:
                            flush_response()
                            print_tool_start(event.name, event.inputs, verbose)
                    elif isinstance(event, PermissionRequest):
                        _stop_tool_spinner()
                        flush_response()
                        event.granted = ask_permission_interactive(event.description, config)
                    elif isinstance(event, ToolEnd):
                        print_tool_end(event.name, event.result, verbose, event.duration,
                                       tool_id=event.tool_id, inputs=event.inputs)
                        _post_tool = True
                        _post_tool_buf.clear()
                        _duplicate_suppressed = False
                        if not _RICH:
                            print(clr("\u2502 ", "dim"), end="", flush=True)
                        _change_spinner_phrase()
                        _start_tool_spinner()
                        spinner_shown = True
                        sf = config.get("_session_file")
                        if sf:
                            _save_session_checkpoint(state, sf, config.get("_session_id"), config.get("_session_path"))
                    elif isinstance(event, TurnDone):
                        _stop_tool_spinner()
                        spinner_shown = False
                        for _kind, _content in _thinking_parser.finalize():
                            if _kind == "thinking":
                                _thinking_chunks.append(_content)
                        if thinking_started:
                            end_thinking_block()
                            print()
                            thinking_started = False
                        if _thinking_chunks:
                            state.thinking_log.append({"turn": state.turn_count, "text": "".join(_thinking_chunks)})
                        sf = config.get("_session_file")
                        if sf:
                            _save_session_checkpoint(state, sf, config.get("_session_id"), config.get("_session_path"))
                        last_llm = next((t for t in reversed(state.timing_entries) if t["phase"] == "llm"), None)
                        if last_llm and last_llm.get("duration", 0.0) > 0.05:
                            flush_response()
                            parts = [f"LLM {_fmt_duration(last_llm['duration'])}"]
                            ttft = last_llm.get("ttft", 0.0)
                            if ttft > 0.05:
                                parts.append(f"ttft {_fmt_duration(ttft)}")
                            thinking = last_llm.get("thinking", 0.0)
                            if thinking > 0.05:
                                think_str = f"think {_fmt_duration(thinking)}"
                                _tc = sum(len(c) for c in _thinking_chunks)
                                if _tc > 0:
                                    think_str += f" ({_tc // 1000}K chars)" if _tc >= 1000 else f" ({_tc} chars)"
                                llm_time = last_llm.get("llm_time", 0.0)
                                if llm_time > 0 and thinking / llm_time > 0.3:
                                    think_str += f" {thinking / llm_time:.0%}"
                                parts.append(think_str)
                            tps = last_llm.get("tokens_per_sec", 0.0)
                            if tps > 0:
                                parts.append(f"{tps:.0f} tok/s")
                            _cr = last_llm.get("cache_read_tokens", 0)
                            _cw = last_llm.get("cache_creation_tokens", 0)
                            if _cr or _cw:
                                _fresh = event.input_tokens - _cw  # exclude cache-write from fresh
                                _in_parts = []
                                if _fresh:
                                    _in_parts.append(f"{_fmt_tok_compact(_fresh)} fresh")
                                if _cr:
                                    _in_parts.append(f"{_fmt_tok_compact(_cr)} cached")
                                if _cw:
                                    _in_parts.append(f"{_fmt_tok_compact(_cw)} cache-write")
                                parts.append("+%s in" % " +".join(_in_parts))
                            else:
                                parts.append(f"+{_fmt_tok_compact(event.input_tokens)} in")
                            parts.append(f"+{_fmt_tok_compact(event.output_tokens)} out")
                            print(clr(f"  ⏱  {' · '.join(parts)}", "dim"))
                    elif isinstance(event, EnforcementWarning):
                        _stop_tool_spinner()
                        flush_response()
                        tools_str = ", ".join(event.missing_tools)
                        print(clr(f"  ⚠️  Enforcement: requesting {tools_str}...", "yellow"))
                        _start_tool_spinner()
                        spinner_shown = True
                    elif isinstance(event, RecoveryFailed):
                        _stop_tool_spinner()
                        flush_response()
                        print(clr(f"  ⚠️  {event.tool} recovery failed — continuing without it: "
                                  f"{event.error[:160]}", "yellow"))
                        _start_tool_spinner()
                        spinner_shown = True
                    elif isinstance(event, CheckpointReady):
                        sf = config.get("_session_file")
                        if sf:
                            _save_session_checkpoint(state, sf, config.get("_session_id"), config.get("_session_path"))
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
                        _tc_total = sum(len(t) for c in state.thinking_log for t in [c.get("text", "")])
                        think_sum = f"thinking {_fmt_duration(_think_total)}"
                        if _tc_total >= 1000:
                            think_sum += f" (~{_tc_total // 1000}K chars)"
                        parts.append(think_sum)
                    parts.append(f"LLM {_fmt_duration(_llm_total)}")
                    if _tool_total > 0.05:
                        parts.append(f"tools {_fmt_duration(_tool_total)}")
                    print(clr(f"  {' | '.join(parts)}", "dim"))
                _total_cr = getattr(state, "total_cache_read_tokens", 0)
                _total_cw = getattr(state, "total_cache_creation_tokens", 0)
                # Anthropic's `usage.input_tokens` is ONLY the fresh/non-cached
                # tokens. `cache_read_input_tokens` and `cache_creation_input_tokens`
                # are SEPARATE and ADDITIVE. So:
                #   total_prompt = Σ input_tokens + Σ cache_read + Σ cache_create
                #   uncached     = Σ input_tokens (already fresh-only)
                _cumulated = state.total_input_tokens + _total_cr + _total_cw
                _cum_str = f"{_cumulated:,} cumulated in"
                if _total_cr or _total_cw:
                    _uncached = state.total_input_tokens
                    _cum_str += f" ({_total_cr:,} cached, {_total_cw:,} cache-write, {_uncached:,} uncached)"
                tok_parts = [f"{_q_distinct:,} distinct in", f"{_q_out:,} out", _cum_str]
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
            from bouzecode.backend.tools import drain_pending_questions
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
            _save_session_checkpoint(state, sf, config.get("_session_id"), config.get("_session_path"))

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
        if result[0] == "__worker__":
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

    if sys.platform == "win32":
        try:
            import ctypes
            _kernel32 = ctypes.windll.kernel32

            @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_ulong)
            def _console_ctrl_handler(ctrl_type):
                CTRL_C_EVENT = 0
                CTRL_CLOSE_EVENT = 2
                CTRL_BREAK_EVENT = 1
                CTRL_LOGOFF_EVENT = 5
                CTRL_SHUTDOWN_EVENT = 6
                if ctrl_type == CTRL_C_EVENT:
                    return False  # let Python handle via SIGINT/KeyboardInterrupt
                if ctrl_type in (CTRL_CLOSE_EVENT, CTRL_BREAK_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT):
                    try:
                        config["_session_saved"] = True
                        save_latest("", state, config)
                    except Exception:
                        try:
                            save_progressive(state, config)
                        except Exception:
                            pass
                    return False  # let Windows terminate
                return False

            _kernel32.SetConsoleCtrlHandler(_console_ctrl_handler, True)
        except Exception:
            pass

    def _track_ctrl_c():
        now = time.time()
        _ctrl_c_times.append(now)
        _ctrl_c_times[:] = [t for t in _ctrl_c_times if now - t <= 2.0]
        if len(_ctrl_c_times) >= 3:
            _stop_tool_spinner()
            import signal as _sig
            _sig.signal(_sig.SIGINT, _sig.SIG_IGN)
            try:
                config["_session_saved"] = True
                save_latest("", state, config)
            except Exception:
                try:
                    save_progressive(state, config)
                except Exception:
                    pass
            print(clr("\n\n  Force quit (3x Ctrl+C).", "red", "bold"))
            os._exit(1)
        return False

    resume_path = config.get("_resume_from")
    resume_auto = config.get("_resume_auto", False)
    if resume_path and Path(resume_path).exists():
        _resumed = _json.loads(Path(resume_path).read_text(encoding="utf-8"))
        state.messages = _resumed.get("messages", [])
        state.turn_count = _resumed.get("turn_count", 0)
        state.user_loop_count = _resumed.get("user_loop_count", 0)
        state.total_input_tokens = _resumed.get("total_input_tokens", 0)
        state.total_output_tokens = _resumed.get("total_output_tokens", 0)
        state.total_cache_read_tokens = _resumed.get("total_cache_read_tokens", 0)
        state.total_cache_creation_tokens = _resumed.get("total_cache_creation_tokens", 0)
        state.distinct_base = _resumed.get("distinct_base", 0)
        _gc_data = _resumed.get("gc_state")
        if _gc_data:
            state.gc_state.notes = _gc_data.get("notes", {})
        resumed_sid = _resumed.get("session_id")
        if resumed_sid:
            session_id = resumed_sid
            config["_session_id"] = session_id
            ckpt.set_session(session_id)
        resumed_path = _resumed.get("session_path")
        if resumed_path:
            config["_session_path"] = resumed_path
        if not initial_prompt and not resume_auto:
            initial_prompt = "Continue."

    if initial_prompt or resume_auto:
        web_agent_dir = config.get("_web_agent_dir")
        if web_agent_dir:
            from ..web import ipc as _ipc
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
        result_path = config.get("_result_file")
        if (plan_path or result_path) and state.messages:
            for msg in reversed(state.messages):
                if msg.get("role") == "assistant":
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        content = "\n".join(
                            b["text"] for b in content
                            if isinstance(b, dict) and b.get("type") == "text"
                        )
                    if content:
                        if plan_path:
                            Path(plan_path).write_text(content, encoding="utf-8")
                        if result_path:
                            Path(result_path).write_text(content, encoding="utf-8")
                    break
        return

    from .paste_input import read_input_with_paste_blocks as _paste_input

    def _read_input(prompt: str) -> str:
        raw = _paste_input(prompt) if sys.stdin.isatty() else input(prompt)
        return _strip_surrogates(raw)

    from .repl_sentinels import process_sentinel_result

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
