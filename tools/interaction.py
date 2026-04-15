# [desc] Provides user prompting, interactive input routing (terminal/Telegram), and a sleep timer utility. [/desc]
"""User interaction tools: questions, input, sleep timer."""
import threading

from tools.state import _is_in_tg_turn


class PausedForInput(Exception):
    """Raised when AskUserQuestion is invoked under web IPC.

    The agent loop catches this, persists the pending turn state (already-completed
    tool results + tool_calls still to run after the answer), and exits the
    subprocess. A later `--resume-pending` respawn fills in the answer and
    continues executing the remaining tool_calls.

    Fields `ask_tc_id`, `completed_results`, `pending_tcs` are populated by the
    agent loop (not by the tool itself, since the tool doesn't know them).
    """

    def __init__(
        self,
        question: str,
        options: list[dict] | None = None,
        allow_freetext: bool = True,
        ask_tc_id: str = "",
        completed_results: dict[str, str] | None = None,
        pending_tcs: list[dict] | None = None,
    ):
        super().__init__(f"Paused for user input: {question!r}")
        self.question = question
        self.options = options or []
        self.allow_freetext = allow_freetext
        self.ask_tc_id = ask_tc_id
        self.completed_results = completed_results or {}
        self.pending_tcs = pending_tcs or []


def is_web_ipc_active() -> bool:
    """True when the subprocess runs under BouzéGUI (IPC dir set via env)."""
    from web import ipc
    return ipc.from_env() is not None


def _ask_user_question_via_web_ipc(
    question: str,
    options: list[dict] | None,
    allow_freetext: bool,
) -> str | None:
    """Safety net: if reached under web IPC (the agent loop normally pre-empts
    AskUserQuestion before execution), raise PausedForInput to unwind the turn.
    Returns None in CLI mode so the caller falls through to terminal input."""
    if not is_web_ipc_active():
        return None
    raise PausedForInput(
        question=question, options=options, allow_freetext=allow_freetext,
    )


def _ask_user_question(
    question: str,
    options: list[dict] | None = None,
    allow_freetext: bool = True,
    config: dict | None = None,
) -> str:
    web_answer = _ask_user_question_via_web_ipc(question, options, allow_freetext)
    if web_answer is not None:
        return web_answer

    try:
        from ui.spinner import _stop_tool_spinner
        _stop_tool_spinner()
    except Exception:
        pass

    print()
    print("\033[1;35m\u2753 Question from assistant:\033[0m")
    print(f"   {question}")

    options = options or []
    raw = ""

    if options:
        print()
        for i, opt in enumerate(options, 1):
            label = opt.get("label", "")
            desc  = opt.get("description", "")
            line  = f"  [{i}] {label}"
            if desc:
                line += f" \u2014 {desc}"
            print(line)
        if allow_freetext:
            print("  [0] Type a custom answer")
        print()

        while True:
            raw = ask_input_interactive("Your choice (number or text): ", config or {}).strip()
            if not raw:
                break
            if raw.isdigit():
                idx = int(raw)
                if 1 <= idx <= len(options):
                    raw = options[idx - 1]["label"]
                    break
                elif idx == 0 and allow_freetext:
                    raw = ask_input_interactive("Your answer: ", config or {}).strip()
                    break
                else:
                    print(f"Invalid option: {idx}")
                    raw = ""
                    continue
            elif allow_freetext:
                break
    else:
        print()
        raw = ask_input_interactive("Your answer: ", config or {}).strip()

    try:
        from ui.spinner import _start_tool_spinner
        _start_tool_spinner()
    except Exception:
        pass

    return raw or "(no answer)"


def ask_input_interactive(prompt: str, config: dict, menu_text: str = None) -> str:
    """Prompt the user for input, routing to Telegram if in a Telegram turn."""
    is_tg = _is_in_tg_turn(config)
    if is_tg and "_tg_send_callback" in config:
        token = config.get("telegram_token")
        chat_id = config.get("telegram_chat_id")
        import re
        clean_prompt = re.sub(r'\x1b\[[0-9;]*m', '', prompt).strip()

        payload = ""
        if menu_text:
            clean_menu = re.sub(r'\x1b\[[0-9;]*m', '', menu_text).strip()
            payload += f"{clean_menu}\n\n"
        payload += f"\u2753 *Input Required*\n{clean_prompt}"

        config["_tg_send_callback"](token, chat_id, payload)

        evt = threading.Event()
        config["_tg_input_event"] = evt
        evt.wait()

        text = config.pop("_tg_input_value", "").strip()
        config.pop("_tg_input_event", None)
        return text
    else:
        try:
            return input(prompt)
        except (KeyboardInterrupt, EOFError):
            print()
            return ""


def drain_pending_questions(config: dict) -> bool:
    """Legacy no-op. Questions are now handled inline by _ask_user_question."""
    return False


def _sleeptimer(seconds: int, config: dict) -> str:
    cb = config.get("_run_query_callback")
    if not cb:
        return "Error: Internal callback missing, bouzecode did not provide _run_query_callback"

    def worker():
        import time
        time.sleep(seconds)
        cb("(System Automated Event): The timer has finished. Please wake up, perform any pending monitoring checks and report to the user now.")

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return f"Timer successfully scheduled for {seconds} seconds. You can output your final thoughts and end your turn. You will be automatically awakened."
