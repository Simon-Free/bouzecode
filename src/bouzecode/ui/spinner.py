# [desc] Animated terminal spinner with randomized status phrases for tool and debate operations. [/desc]
import sys
import threading
from .ansi import clr
from .barre_agents.rendu import EFFACER_BLOC, bloc_pied, effacement

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
    "\U0001f406 bouzecode mode engaged...",
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

# Progression de l'outil en cours de main (pytest n/N) : remplace la phrase tant qu'elle est
# posee. Videe a chaque changement d'etape (nouvel outil, fin d'outil, arret).
_spinner_progression = ""

# Ce qu'il faut écrire pour reprendre la ligne courante : retour chariot, on couvre la
# frame la plus longue avec des espaces, retour chariot. Même séquence qu'à l'arrêt.
_ERASE_LINE = "\r" + " " * 50 + "\r"

# Le flux où le spinner dessine sa ligne vivante, capturé AU DÉMARRAGE, donc toujours le
# vrai stdout et jamais le proxy : sinon chaque frame déclencherait son propre effacement.
_spinner_out = None


class _SpinnerAwareStream:
    """Laisse passer une ligne de log sans la coller à la ligne du spinner.

    Le spinner tient une ligne VIVANTE : il écrit `\\r` + frame, sans newline, et la
    réécrit dix fois par seconde. Les logs du backend, eux, sortent en texte plein
    terminé par `\\n` — et sur un autre flux (`[map] miss ...` et
    `SymbolMap: ... — N lignes` partent sur stderr, le spinner sur stdout). Aucun des
    deux ne sait que l'autre existe, alors sur un terminal les deux atterrissent sur la
    MÊME ligne physique et on lit
    `⠙ 🤔 Who is Barry Allen?...   [map] miss    SymbolMap work — ...`.

    C'est le modèle `tqdm.write` : le texte ne traverse pas le spinner, il l'ÉCARTE.
    Avant de laisser passer une écriture qui n'est pas une frame, on efface la ligne
    courante ; le tick suivant (100 ms) redessine le spinner SOUS la ligne de log, qui
    reste intacte. Tout se fait sous `_spinner_lock`, sinon une frame pourrait se glisser
    entre l'effacement et le texte.

    Les frames commencent par `\\r` : elles sont reconnues et passent telles quelles, ce
    qui évite un effacement récursif.

    L'effacement est INCONDITIONNEL : c'est l'installation du proxy qui est conditionnelle.
    Seul `_start_tool_spinner` le pose et `_stop_tool_spinner` le retire, donc son existence
    prouve déjà qu'un spinner tourne — retester l'état du thread ici dupliquerait cet
    invariant et rendrait la classe intestable seule. Un log non interactif (le web, où ces
    trames `\\r` sont filtrées) ne voit jamais ce proxy : aucun spinner n'y est démarré.
    """

    def __init__(self, real, erase_to):
        self._real = real
        self._erase_to = erase_to

    def write(self, s):
        if not s or s.startswith("\r"):
            return self._real.write(s)
        with _spinner_lock:
            try:
                self._erase_to.write(effacement(_ERASE_LINE))
                self._erase_to.flush()
            except (ValueError, OSError):
                # Flux fermé sous nos pieds : on écrit quand même le texte demandé.
                pass
            return self._real.write(s)

    def flush(self):
        return self._real.flush()

    def __getattr__(self, name):
        # `isatty`, `encoding`, `fileno`... : tout le reste appartient au vrai flux.
        return getattr(self._real, name)


def _install_spinner_proxies(erase_to) -> None:
    """Un seul point d'insertion pour TOUS les émetteurs de logs.

    On ne câble pas le backend sur le spinner : les lignes viennent de plusieurs modules
    (journal, progress, et n'importe quel `print`), et un couplage UI -> backend serait à
    refaire à chaque nouvel émetteur. On enveloppe les deux flux, une fois.
    """
    if not isinstance(sys.stdout, _SpinnerAwareStream):
        sys.stdout = _SpinnerAwareStream(sys.stdout, erase_to)
    if not isinstance(sys.stderr, _SpinnerAwareStream):
        sys.stderr = _SpinnerAwareStream(sys.stderr, erase_to)


def _remove_spinner_proxies() -> None:
    if isinstance(sys.stdout, _SpinnerAwareStream):
        sys.stdout = sys.stdout._real
    if isinstance(sys.stderr, _SpinnerAwareStream):
        sys.stderr = sys.stderr._real

def _run_tool_spinner():
    chars = "\u280b\u2819\u2839\u2838\u283c\u2834\u2826\u2827\u2807\u280f"
    out = _spinner_out if _spinner_out is not None else sys.stdout
    i = 0
    while not _tool_spinner_stop.is_set():
        # La frame s'écrit SOUS le lock : un log qui passe au même instant efface la ligne
        # et écrit son texte sans qu'une frame vienne s'intercaler au milieu.
        with _spinner_lock:
            #  \x1b[K : la progression change de longueur, sa fin precedente ne doit pas rester.
            texte = (clr(_spinner_progression, "cyan") + "\x1b[K" if _spinner_progression
                     else clr(_spinner_phrase, "dim"))
            frame = chars[i % len(chars)]
            try:
                pied = bloc_pied()  # barre des sous-agents SOUS la ligne ("" sans sous-agent)
                debut = EFFACER_BLOC if pied else "\r"
                out.write(f"{debut}  {frame} {texte}   {pied}")
                out.flush()
            except (ValueError, OSError):
                return
        i += 1
        _tool_spinner_stop.wait(0.1)

def _start_tool_spinner():
    global _tool_spinner_thread, _spinner_out
    if _tool_spinner_thread and _tool_spinner_thread.is_alive():
        return
    import random
    with _spinner_lock:
        global _spinner_phrase, _spinner_progression
        _spinner_phrase = random.choice(_TOOL_SPINNER_PHRASES)
        _spinner_progression = ""
    # Capturé avant l'enveloppe : le spinner écrit sur le vrai flux.
    _spinner_out = sys.stdout
    _install_spinner_proxies(_spinner_out)
    _tool_spinner_stop.clear()
    _tool_spinner_thread = threading.Thread(target=_run_tool_spinner, daemon=True)
    _tool_spinner_thread.start()

def _change_spinner_phrase():
    import random
    with _spinner_lock:
        global _spinner_phrase, _spinner_progression
        _spinner_phrase = random.choice(_TOOL_SPINNER_PHRASES)
        _spinner_progression = ""


def afficher_progression(texte: str) -> bool:
    """La progression d'un outil de main dans la ligne vivante du spinner, a la place de sa
    phrase : une barre ecrite a cote serait ecrasee a chaque frame. False sans spinner."""
    global _spinner_progression
    if not (_tool_spinner_thread and _tool_spinner_thread.is_alive()):
        return False
    with _spinner_lock:
        _spinner_progression = texte
    return True


def _stop_tool_spinner():
    global _tool_spinner_thread, _spinner_out, _spinner_progression
    if not _tool_spinner_thread:
        return
    _tool_spinner_stop.set()
    _tool_spinner_thread.join(timeout=1)
    _tool_spinner_thread = None
    _spinner_progression = ""
    out = _spinner_out if _spinner_out is not None else sys.stdout
    # Les proxies partent AVANT l'effacement : plus de spinner, donc plus rien à écarter.
    _remove_spinner_proxies()
    _spinner_out = None
    out.write(effacement(_ERASE_LINE))
    out.flush()
