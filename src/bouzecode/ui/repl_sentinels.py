# [desc] Processes sentinel tuples from slash commands to drive REPL state transitions and follow-ups. [/desc]
"""Sentinel-dispatch state machine for the REPL loop.

When a slash command returns a sentinel tuple (voice, image, brainstorm, SSJ,
debate, etc.), this module processes it — often re-entering handle_slash to
loop back to the SSJ menu or chain follow-up prompts.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

from .ansi import clr, info, ok
from .spinner import _start_tool_spinner, _stop_tool_spinner
from . import spinner
from bouzecode.backend.commands import handle_slash


def _spin_and_query(phrase: str, prompt: str, run_query) -> None:
    """Show spinner with phrase, stop it on first model output, run query."""
    with ui.spinner._spinner_lock:
        ui.spinner._spinner_phrase = phrase
    _start_tool_spinner()

    class _DebateSpinnerWrapper:
        def __init__(self, real_out):
            self._real = real_out
            self._stopped = False

        def write(self, s):
            if not self._stopped and s and not s.startswith("\r"):
                self._stopped = True
                _stop_tool_spinner()
                self._real.write("\n")
            return self._real.write(s)

        def flush(self):
            return self._real.flush()

        def __getattr__(self, name):
            return getattr(self._real, name)

    _orig = sys.stdout
    sys.stdout = _DebateSpinnerWrapper(sys.stdout)
    try:
        run_query(prompt)
    finally:
        _stop_tool_spinner()
        sys.stdout = _orig


def _run_debate(dfile: str, nagents: int, rounds: int, debate_out: str, run_query) -> None:
    _spin_and_query(
        "\u2694\ufe0f  Assembling expert panel...",
        f"Read the file {dfile}. Then introduce the {nagents} expert debaters you will "
        "role-play, each with a distinct focus area chosen to best challenge each other "
        "(e.g. architecture, performance, security, UX, testing, maintainability). "
        "List their names and focus areas. Do NOT debate yet.",
        run_query,
    )
    for r in range(1, rounds + 1):
        for e in range(1, nagents + 1):
            phase = "opening argument" if r == 1 else f"round {r} response"
            _spin_and_query(
                random.choice([
                    f"\u2694\ufe0f  Round {r}/{rounds} \u2014 Expert {e} thinking...",
                    f"\U0001f4ac  Round {r}/{rounds} \u2014 Expert {e} formulating...",
                    f"\U0001f9e0  Round {r}/{rounds} \u2014 Expert {e} responding...",
                ]),
                f"Now speak as Expert {e}. Give your {phase}. "
                "Be specific, reference the file content, and directly address "
                "the previous arguments. Be concise (3-5 key points).",
                run_query,
            )
    _spin_and_query(
        "\U0001f4dc  Drafting final consensus...",
        "Based on this entire debate, write a final consensus that all experts agree on. "
        "List the top actionable changes ranked by impact. "
        "Then use the Write tool to save the complete debate transcript and this consensus "
        f"to: {debate_out}",
        run_query,
    )


def process_sentinel_result(result, state, config, run_query, track_ctrl_c) -> None:
    """Process a sentinel tuple returned by handle_slash, looping until resolved."""
    while isinstance(result, tuple):
        key = result[0]
        if key == "__voice__":
            _safe_run(result[1], run_query, track_ctrl_c)
            return
        if key == "__image__":
            _safe_run(result[1], run_query, track_ctrl_c)
            return
        if key == "__plan__":
            _safe_run(
                f"Please analyze the codebase and create a detailed implementation plan for: {result[1]}",
                run_query, track_ctrl_c,
            )
            return
        if key == "__ssj_passthrough__":
            slash_line = result[1]
            if slash_line.strip().lower() == "/ssj":
                result = handle_slash("/ssj", state, config)
                continue
            inner = handle_slash(slash_line, state, config)
            if isinstance(inner, tuple):
                result = inner
                continue
            return
        if key == "__ssj_cmd__":
            _, cmd_name, cmd_args = result
            inner = handle_slash(f"/{cmd_name} {cmd_args}".strip(), state, config)
            if isinstance(inner, tuple):
                result = ("__ssj_wrap__", inner)
                continue
            result = handle_slash("/ssj", state, config)
            continue
        if key == "__ssj_wrap__":
            result = result[1]
            from_ssj = True
        else:
            from_ssj = key == "__ssj_query__"

        if result[0] == "__worker__":
            _, worker_tasks = result
            for i, (_line_idx, task_text, prompt) in enumerate(worker_tasks):
                print(clr(f"\n  \u2500\u2500 Worker ({i+1}/{len(worker_tasks)}): {task_text} \u2500\u2500", "yellow"))
                try:
                    run_query(prompt)
                except KeyboardInterrupt:
                    track_ctrl_c()
                    print(clr("\n  (worker interrupted \u2014 remaining tasks skipped)", "yellow"))
                    break
            ok("Worker finished. Run /worker to check remaining tasks.")
            if from_ssj:
                result = handle_slash("/ssj", state, config)
                continue
            return

        if result[0] == "__ssj_debate__":
            _, dfile, nagents, rounds, debate_out = result
            try:
                _run_debate(dfile, nagents, rounds, debate_out, run_query)
                ok(f"Debate complete. Saved to {debate_out}")
            except KeyboardInterrupt:
                track_ctrl_c()
                _stop_tool_spinner()
                sys.stdout = sys.__stdout__
                print(clr("\n  (debate interrupted)", "yellow"))
            result = handle_slash("/ssj", state, config)
            continue

        if result[0] == "__ssj_query__":
            _safe_run(result[1], run_query, track_ctrl_c)
            result = handle_slash("/ssj", state, config)
            continue

        skill, skill_args = result
        info(f"Running skill: {skill.name}" + (f" [{skill.context}]" if skill.context == "fork" else ""))
        try:
            from bouzecode.backend.tools.skill import substitute_arguments
            rendered = substitute_arguments(skill.prompt, skill_args, skill.arguments)
            run_query(f"[Skill: {skill.name}]\n\n{rendered}")
        except KeyboardInterrupt:
            track_ctrl_c()
            print(clr("\n  (Ctrl+C detected \u2014 turn cancelled. Press Ctrl+C 3\u00d7 in 2s to force-quit.)", "yellow"))
        return


def _safe_run(prompt: str, run_query, track_ctrl_c) -> bool:
    try:
        run_query(prompt)
        return True
    except KeyboardInterrupt:
        track_ctrl_c()
        print(clr("\n  (Ctrl+C detected \u2014 turn cancelled. Press Ctrl+C 3\u00d7 in 2s to force-quit.)", "yellow"))
        return False
