# [desc] Provides user prompting, interactive terminal input, and a sleep timer utility. [/desc]
"""User interaction tools: questions, input, sleep timer."""
import threading


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
        is_plan_validation: bool = False,
    ):
        super().__init__(f"Paused for user input: {question!r}")
        self.question = question
        self.options = options or []
        self.allow_freetext = allow_freetext
        self.ask_tc_id = ask_tc_id
        self.completed_results = completed_results or {}
        self.pending_tcs = pending_tcs or []
        self.is_plan_validation = is_plan_validation


class DeferredChecks(Exception):
    """Raised at FinalAnswer when the context has a non-empty deferred_queue.

    Sibling of PausedForInput. The agent loop catches this, persists the
    deferred checks (the final answer + the list of commands to run after
    close) to disk, and exits the subprocess. The web runner then drains the
    checks; on failure it respawns the agent via `--resume-deferred`.
    """

    def __init__(self, answer: str, checks: list[dict] | None = None):
        super().__init__(f"Deferred checks pending: {len(checks or [])} command(s)")
        self.answer = answer
        self.checks = checks or []


#  Une réponse livrée AVANT ses vérifications différées le DIT, et le verdict prend la place
#  de l'avis quand il arrive (web : drain du runner ; TUI : fil de fond). Sessions a5536ec2 et
#  3f364511 : rapport « tests verts » livré pendant que la suite complète n'avait pas tourné,
#  la seule trace étant « suite déférée à la fermeture » en fin de section.
ANNONCE_DIFFEREE = "⏳ VÉRIFICATION NON FAITE"
_SEPARATEUR = "\n\n---\n"


def annonce_verifications_differees(checks: list[dict]) -> str:
    """L'avis ajouté à la réponse livrée : ce qui n'a PAS encore été vérifié, et quand."""
    commandes = "\n".join(f"- `{c.get('command', '')}`" for c in checks)
    return (f"{_SEPARATEUR}{ANNONCE_DIFFEREE} au moment de cette réponse : "
            f"{len(checks)} vérification(s) différée(s) tournent APRÈS la clôture :\n"
            f"{commandes}\n"
            "Leur verdict remplacera cet avis à son arrivée ; d'ici là, rien de ce qu'elles "
            "doivent confirmer n'est acquis.")


def remplacer_annonce(texte: str, verdict: str) -> str:
    """Le verdict à la place de l'avis « non faite » (ajouté en fin s'il n'y en a pas)."""
    marque = _SEPARATEUR + ANNONCE_DIFFEREE
    base = texte.split(marque, 1)[0] if marque in texte else texte.rstrip()
    return f"{base}{_SEPARATEUR}{verdict}"


def is_web_ipc_active() -> bool:
    """True when the subprocess runs under bouzeui (IPC dir set via env)."""
    from bouzecode.web_v2.runtime import ipc
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
    # Sous-agent du TUI : la question attend dans SA ligne de la barre, l'utilisateur y répond
    # depuis sa vue — jamais un second `input()` qui disputerait le clavier au REPL.
    poser_dans_la_barre = (config or {}).get("_tui_question")
    if poser_dans_la_barre is not None:
        reponse = poser_dans_la_barre(question, options, allow_freetext)
        from ..context_manager.methodology import append_ask_user_question_to_methodology
        from ..context_manager.state import resolve_context_state
        append_ask_user_question_to_methodology(resolve_context_state(config), question, reponse)
        return reponse
    if personne_pour_repondre(config or {}):
        return _sans_humain(question, config or {})

    from bouzecode.ui.spinner import _stop_tool_spinner
    from bouzecode.ui.terminal_title import set_terminal_status
    _stop_tool_spinner()
    set_terminal_status("question")

    print()
    print("\033[1;35m\u2753 Question from assistant:\033[0m")
    print(f"   {question}")

    options = options or []
    # Tolerate options the model emitted as bare strings instead of {label, description}
    # objects (the web path JSON-normalizes; this is the CLI equivalent).
    options = [{"label": o} if isinstance(o, str) else o for o in options]
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

    from bouzecode.ui.spinner import _start_tool_spinner
    _start_tool_spinner()
    set_terminal_status("running")

    final_answer = raw or "(no answer)"
    from ..context_manager.methodology import append_ask_user_question_to_methodology
    from ..context_manager.state import resolve_context_state
    append_ask_user_question_to_methodology(
        resolve_context_state(config or {}), question, final_answer,
    )
    return final_answer


#  Session 9d81964e (2026-10-06) : le parent `-p` sans console recevait « No Windows console
#  found » ; ses enfants `-p` dans un onglet de terminal attendaient une saisie que personne ne
#  ferait (bloqués des heures, cf. py-spy). Un run `-p` ne pose JAMAIS de question.
REPONSE_SANS_HUMAIN = (
    "Pas d'humain disponible (exécution non interactive) : personne ne répondra. Décide "
    "toi-même l'option la plus raisonnable, note l'hypothèse retenue dans Methodology, et "
    "signale-la dans FinalAnswer (taches_restantes : « hypothèse à valider : … »).")


def personne_pour_repondre(config: dict) -> bool:
    """Run `-p` (non interactif) ou sans console : aucune saisie possible."""
    return bool(config.get("_non_interactif")) or not _stdin_est_une_console()


def _stdin_est_une_console() -> bool:
    """Sous Windows, `isatty()` est vrai aussi pour NUL : seul GetConsoleMode dit si une
    vraie console est attachée (c'est ce qui manquait à prompt_toolkit le 2026-10-06)."""
    import sys
    stdin = sys.stdin
    if stdin is None or not stdin.isatty():
        return False
    if sys.platform != "win32":
        return True
    import ctypes
    import msvcrt
    mode = ctypes.c_uint32()
    poignee = msvcrt.get_osfhandle(stdin.fileno())
    return bool(ctypes.windll.kernel32.GetConsoleMode(poignee, ctypes.byref(mode)))


def _sans_humain(question: str, config: dict) -> str:
    from ..context_manager.methodology import append_ask_user_question_to_methodology
    from ..context_manager.state import resolve_context_state
    append_ask_user_question_to_methodology(
        resolve_context_state(config), question, "(sans réponse : run non interactif)")
    return REPONSE_SANS_HUMAIN


def ask_input_interactive(prompt: str, config: dict, menu_text: str = None) -> str:
    """Prompt the user for input on the console."""
    from bouzecode.ui.paste_input import read_answer_with_paste_blocks
    try:
        return read_answer_with_paste_blocks(prompt)
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
