# [desc] Background Bash process registry: launch detached, poll output, kill. [/desc]
"""Run Bash commands detached so a long/persistent process (Flask server, watcher,
build) doesn't block the turn. A reader thread drains stdout into a buffer so the
OS pipe never fills; BashOutput returns the output produced since the last poll."""
import contextlib
import os
import subprocess
import sys
import threading

from ...core.dossier_agent import courant

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
        _build_popen_command, _get_env_with_user_vars, _substitute_scratch_paths,
        spill_or_refuse_inline_python,
    )
    command, note = spill_or_refuse_inline_python(command)
    if not command:
        return note
    # Write(temp=True) promises the logical scratch path works in shell commands;
    # that promise must hold in background too (an agent once slept 240 s on a
    # `No such file or directory` because only the foreground path substituted).
    command = _substitute_scratch_paths(command)
    popen_cmd, shell, temp_path = _build_popen_command(command)
    kwargs = dict(
        shell=shell, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8",
        errors="replace", cwd=courant(), env=marquer_env(_get_env_with_user_vars()),
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


def _decoded_new(entry) -> str:
    """New output since the last poll, with PowerShell's CLIXML envelope decoded.

    A background job's secondary streams come back serialized as `#< CLIXML`
    + `<Objs>`; returned raw, the useful error drowns in XML with `_x000D__x000A_`
    escapes and no grep-based supervision can match it.
    """
    from .shell_search import decode_clixml_stream
    return decode_clixml_stream(_read_new(entry)).strip()


def bash_output(bash_id: str, kill: bool = False, wait_s: int = 0,
                until_exit: bool = False, cancelled=None) -> str:
    """Return [status] + output since the last poll. kill=True stops the process.
    wait_s > 0 (or until_exit) first waits for new output / exit — see bash_bg_wait."""
    from .bash_bg_wait import borne_attente, wait_for_activity
    from .truncation import truncate_tool_output
    entry = _bg_procs.get(bash_id)
    if entry is None:
        return f"Error: unknown bash_id={bash_id!r} (already finished and cleared?)."
    proc = entry["proc"]
    wait_s = borne_attente(wait_s, until_exit)
    wait_note = None
    if wait_s and not kill:
        wait_note = wait_for_activity(entry, wait_s, until_exit, cancelled)
    if kill:
        from .shell_search import _kill_proc_tree
        if proc.poll() is None:
            _kill_proc_tree(proc.pid)
            proc.wait()
        entry["thread"].join(timeout=2)
        body = _decoded_new(entry) or "(no output)"
        _finalize(bash_id, entry)
        return truncate_tool_output(f"[killed] bash_id={bash_id}\n{body}", "Bash")
    rc = proc.poll()
    if rc is not None:
        entry["thread"].join(timeout=2)
    body = _decoded_new(entry) or "(no new output)"
    if rc is None:
        status = f"[running] bash_id={bash_id}" + (f" ({wait_note})" if wait_note else "")
        return truncate_tool_output(f"{status}\n{body}", "Bash")
    _finalize(bash_id, entry)
    return truncate_tool_output(f"[exited code={rc}] bash_id={bash_id}\n{body}", "Bash")


# --------------------------------------------------------------- processus laissés derrière
#  Cas réel (2026-09-25) : `python3 server.py --port 8010 &`, lancé par un Bash d'agent,
#  tournait encore 3 h après, dans un worktree supprimé. Deux fuites : le `&` d'un Bash au
#  premier plan survit à son shell (même session, reparenté), et un agent tué par SIGTERM ne
#  rattrape jamais ses `background=true` (`start_new_session` les détache de lui).
#  Tout processus lancé par l'outil Bash porte donc MARQUEUR = le jeton de l'agent : c'est
#  par lui, et seulement par lui, qu'on les retrouve — jamais un shell de l'utilisateur, jamais
#  le serveur MCP chrome-devtools (lancé hors Bash), jamais l'agent lui-même.
MARQUEUR = "BOUZECODE_BASH_AGENT"
_jeton: str = ""
#  Un Bash a-t-il été lancé depuis le dernier balayage ? Balayer = lire l'environnement de
#  CHAQUE processus du poste (~1 000 ici) : 0,4 à 0,8 s. Sans Bash lancé depuis, tout ce que
#  les Bash précédents avaient laissé a déjà été arrêté par ce balayage-là.
_bash_depuis_le_balayage = False


def jeton_agent() -> str:
    """Identité de CE processus agent : pid + date de naissance (un pid se recycle)."""
    global _jeton
    if not _jeton:
        import psutil
        _jeton = f"{os.getpid()}-{int(psutil.Process().create_time())}"
    return _jeton


def marquer_env(env: dict) -> dict:
    """Pose le marqueur dans l'environnement d'une commande Bash (premier plan ou fond)."""
    global _bash_depuis_le_balayage
    env[MARQUEUR] = jeton_agent()
    _bash_depuis_le_balayage = True
    return env


def _epargnes() -> set[int]:
    import psutil
    pids = {os.getpid()}
    with contextlib.suppress(psutil.Error):
        pids.update(p.pid for p in psutil.Process().parents())
    return pids


#: Processus dont l'environnement est ILLISIBLE pour de bon. Un renderer Chrome/Edge sandboxé
#: rend ERROR_PARTIAL_COPY à chaque lecture : psutil réessaie ~1 s avant de conclure
#: AccessDenied, et chaque balayage repayait cette seconde pour CHAQUE renderer (mesuré : 7 à
#: 15 s par balayage avec un navigateur ouvert, à chaque fauche de worktree). Un refus d'accès
#: ne se lève pas pendant la vie d'un processus : on ne le redemande plus. On garde les
#: `psutil.Process` eux-mêmes : leur égalité vaut (pid, date de naissance), ce qui protège
#: d'un pid recyclé — sans demander `create_time()`, dont le repli lent coûte ~45 ms par
#: processus système refusé (236 refusés = 10 s, mesuré).
_illisibles: set = set()

#: Lectures d'environnement menées de front : les attentes de psutil sur les illisibles
#: (des `sleep`) se recouvrent au lieu de s'additionner au premier balayage.
_LECTEURS = 16


def _lire_environ(proc) -> tuple[dict | None, bool]:
    """(environnement, illisible pour de bon ?) ; (None, False) si le processus a disparu."""
    import psutil
    try:
        return proc.environ(), False
    except psutil.AccessDenied:
        return None, True
    except (psutil.Error, OSError):
        return None, False


def _marques(retenir) -> list:
    """Processus marqués (lancés par un Bash d'agent) que `retenir(env, proc)` désigne."""
    import psutil
    from concurrent.futures import ThreadPoolExecutor
    global _illisibles
    deja_illisibles, a_lire = set(), []
    for proc in psutil.process_iter(["pid"]):
        if proc in _illisibles:
            deja_illisibles.add(proc)
        else:
            a_lire.append(proc)
    with ThreadPoolExecutor(max_workers=_LECTEURS) as lecteurs:
        lectures = list(lecteurs.map(_lire_environ, a_lire))
    trouves, illisibles = [], set(deja_illisibles)
    for proc, (env, illisible) in zip(a_lire, lectures):
        if illisible:
            illisibles.add(proc)
        if env and env.get(MARQUEUR) and retenir(env, proc):
            trouves.append(proc)
    _illisibles = illisibles  # seuls les vivants : l'ensemble ne grossit pas sans fin
    if not trouves:
        return trouves
    #  Ancêtres calculés seulement s'il y a un candidat : `parents()` relit la table des
    #  processus à chaque niveau (~0,25 s pour 9 ancêtres).
    epargnes = _epargnes()
    return [proc for proc in trouves if proc.pid not in epargnes]


def _arreter(procs: list) -> list[int]:
    """SIGTERM, puis SIGKILL pour ce qui résiste. Rend les pids arrêtés."""
    import psutil
    for proc in procs:
        with contextlib.suppress(psutil.Error):
            proc.terminate()
    _, vivants = psutil.wait_procs(procs, timeout=3)
    for proc in vivants:
        with contextlib.suppress(psutil.Error):
            proc.kill()
    psutil.wait_procs(vivants, timeout=3)
    return sorted(proc.pid for proc in procs)


def arreter_processus_lances() -> list[int]:
    """Clôture de l'agent : arrête tout ce que SES Bash ont lancé et qui tourne encore
    (`background=true` comme `cmd &`). Rend les pids arrêtés.

    Balaie seulement si un Bash a été lancé depuis le balayage précédent : un processus qui
    enchaîne les clôtures (agent chaud, worker de tests) ne relit plus l'environnement de tout
    le poste à chacune — 0,8 s par clôture, pour rien, dès qu'un seul Bash avait tourné."""
    global _bash_depuis_le_balayage
    pids: list[int] = []
    if _bash_depuis_le_balayage:
        _bash_depuis_le_balayage = False  # avant le scan : un Bash lancé pendant réarme
        jeton = _jeton
        pids = _arreter(_marques(lambda env, _proc: env.get(MARQUEUR) == jeton))
    with _bg_lock:
        entrees = list(_bg_procs.items())
    for bash_id, entry in entrees:
        if entry["proc"].poll() is not None:
            _finalize(bash_id, entry)
    return pids


def _dans(chemin: str, racine: str) -> bool:
    chemin = chemin.removesuffix(" (deleted)")
    try:
        return os.path.commonpath([os.path.normcase(os.path.abspath(chemin)),
                                   os.path.normcase(os.path.abspath(racine))]) \
            == os.path.normcase(os.path.abspath(racine))
    except ValueError:  # lecteurs différents (Windows)
        return False


def _cwd(proc) -> str:
    import psutil
    try:
        return proc.cwd()
    except (psutil.Error, OSError):
        return ""


def arreter_processus_du_worktree(worktree: str) -> list[int]:
    """Filet serveur, quand un worktree est supprimé ou récolté : les processus lancés par un
    Bash d'agent qui y vivent encore (cwd dedans, ou worktree déclaré) sont arrêtés."""
    if not worktree:
        return []

    def _vit_dedans(env: dict, proc) -> bool:
        declare = env.get("BOUZECODE_WORKTREE_ROOT", "")
        cwd = _cwd(proc)
        return bool(declare and _dans(declare, worktree)) or bool(cwd and _dans(cwd, worktree))

    return _arreter(_marques(_vit_dedans))
