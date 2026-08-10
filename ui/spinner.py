# [desc] Animated terminal spinner with randomized status phrases for tool and debate operations. [/desc]
import sys
import threading
from ui.ansi import clr

_TOOL_SPINNER_PHRASES = [
    "\u26a1 Rewriting light speed...",
    "\U0001f3c1 Winning a race against light...",
    "\U0001f914 Who is Barry Allen?...",
    "\U0001f406 Outrunning the compiler...",
    "\U0001f4a8 Leaving electrons behind...",
    "\U0001f30d Orbiting the codebase...",
    "\u23f1\ufe0f Breaking the sound barrier...",
    "\U0001f525 Faster than a hot reload...",
    "\U0001f680 Terminal velocity reached...",
    "\U0001f43e Claw marks on the stack...",
    "\U0001f3ce\ufe0f Shifting to 6th gear...",
    "\u26a1 Speed force activated...",
    "\U0001f32a\ufe0f Blitzing through the AST...",
    "\U0001f4ab Bending spacetime...",
    "\U0001f406 bouz\u00e9code mode engaged...",
]

_DEBATE_SPINNER_PHRASES = [
    "\u2694\ufe0f  Experts taking their positions...",
    "\U0001f9e0  Experts formulating arguments...",
    "\U0001f5e3\ufe0f  Debate in progress...",
    "\u2696\ufe0f  Weighing the evidence...",
    "\U0001f4a1  Building counter-arguments...",
    "\U0001f525  Debate heating up...",
    "\U0001f4dc  Drafting the consensus...",
    "\U0001f3af  Finding common ground...",
]

_tool_spinner_thread = None
_tool_spinner_stop = threading.Event()

_spinner_phrase = ""
_spinner_lock = threading.Lock()

def _run_tool_spinner():
    chars = "\u280b\u2819\u2839\u2838\u283c\u2834\u2826\u2827\u2807\u280f"
    i = 0
    while not _tool_spinner_stop.is_set():
        with _spinner_lock:
            phrase = _spinner_phrase
        frame = chars[i % len(chars)]
        sys.stdout.write(f"\r  {frame} {clr(phrase, 'dim')}   ")
        sys.stdout.flush()
        i += 1
        _tool_spinner_stop.wait(0.1)

def _start_tool_spinner():
    global _tool_spinner_thread
    if _tool_spinner_thread and _tool_spinner_thread.is_alive():
        return
    import random
    with _spinner_lock:
        global _spinner_phrase
        _spinner_phrase = random.choice(_TOOL_SPINNER_PHRASES)
    _tool_spinner_stop.clear()
    _tool_spinner_thread = threading.Thread(target=_run_tool_spinner, daemon=True)
    _tool_spinner_thread.start()

def _change_spinner_phrase():
    import random
    with _spinner_lock:
        global _spinner_phrase
        _spinner_phrase = random.choice(_TOOL_SPINNER_PHRASES)

def _stop_tool_spinner():
    global _tool_spinner_thread
    if not _tool_spinner_thread:
        return
    _tool_spinner_stop.set()
    _tool_spinner_thread.join(timeout=1)
    _tool_spinner_thread = None
    sys.stdout.write(f"\r{' ' * 50}\r")
    sys.stdout.flush()
