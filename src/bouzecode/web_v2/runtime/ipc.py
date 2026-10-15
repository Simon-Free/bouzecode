"""File-based IPC between bouzeui and the bouzecode agent subprocess.

Layout in <ipc_dir>/:
  state.json     — agent status + optional awaiting-input payload
  followup.txt   — HÉRITÉ : tour suivant pour un process de l'ANCIEN code (sans drapeau
                   `boite` dans son état) ; l'agent le lit et l'efface. Un fichier unique,
                   écrasé par un 2e message arrivé avant lecture : le 1er était perdu.
  answer.txt     — UI writes answer to AskUserQuestion; tool reads & deletes
  cancel.flag    — UI touches to request turn cancellation; agent reads & deletes
  inbox/<ns>-<id>.txt — LA file des messages vers l'agent (un fichier par message), qu'il
                   joue son tour ou attende oisif : il les relève TOUS, dans l'ordre, à sa
                   prochaine frontière de tour (après le lot d'outils en cours) ou, oisif,
                   comme tour suivant. Lu = fichier disparu.

Statuses:
  running          — agent actively processing a turn
  awaiting_input   — AskUserQuestion is blocked waiting for answer.txt
  idle             — final answer delivered, waiting for its inbox (or followup.txt)
  finished         — process is exiting

state.json payload: ``{status, updated_at, turn, ...extra}``. ``updated_at`` (epoch, written
by every ``write_state``) is the agent's HEARTBEAT — a "running" whose ``updated_at`` is ten
minutes old says something a bare "running" cannot. ``tools`` carries the tool names of the
batch currently executing (see ``dag._announce_activity``): during tool execution it is the
ONLY live trace of what the agent is doing, the partial stream having already been cleared
and the session not yet saved. Both are surfaced by ``store.agent_status``.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

STATUS_RUNNING = "running"
STATUS_AWAITING_INPUT = "awaiting_input"
STATUS_IDLE = "idle"
STATUS_FINISHED = "finished"

# Les deux statuts suivants sont les SEULS écrits par le SERVEUR et non par l'agent.
# Un agent ne peut pas écrire « je suis mort » : quand le serveur le tue, il meurt avant
# d'avoir pu corriger son state.json, qui reste figé sur `running` avec un pid périmé.
# Tout observateur croise alors « l'IPC dit running » + « le process n'existe plus » et
# conclut à une mort en plein tour — alors que c'est l'état transitoire NORMAL d'une
# relance (mesure du 2026-08-25 : 4 alertes « MORT SANS CLOTURE », 4 faux positifs).
# Le serveur SAIT qu'il va tuer : il estampille donc AVANT la mise à mort. Ces statuts
# veulent dire « le process a disparu, c'est VOULU, ne déclenche pas d'alerte ».
# Ils portent en plus `killed_by="server"` et `origin` ("kill" | "interrupt").
STATUS_KILLED_BY_SERVER = "killed_by_server"   # POST /api/agents/<id>/stop : arrêt explicite
STATUS_INTERRUPTED_BY_SERVER = "interrupted_by_server"  # escalade de /interrupt : process tué,
# session INTACTE, le /continue suivant la reprend (respawn à froid au lieu du réveil à chaud).
# Si la mise à mort est REFUSÉE par l'OS (AccessDenied), l'appelant restaure l'état d'avant :
# un agent marqué mort alors qu'il tourne encore serait invisible pour la supervision.

ENV_IPC_DIR = "BOUZECODE_WEB_IPC_DIR"

# Drapeau écrit dans CHAQUE état par un process qui relève sa boîte quand il est oisif.
# Un process lancé avec l'ancien code ne l'écrit pas : il ne sonde que followup.txt, et le
# serveur continue de le lui écrire (`runner._push_followup`).
DRAPEAU_BOITE = "boite"


@dataclass
class IPCPaths:
    root: Path

    @property
    def state(self) -> Path:
        return self.root / "state.json"

    @property
    def followup(self) -> Path:
        return self.root / "followup.txt"

    @property
    def answer(self) -> Path:
        return self.root / "answer.txt"

    @property
    def cancel(self) -> Path:
        return self.root / "cancel.flag"

    @property
    def inbox(self) -> Path:
        return self.root / "inbox"


def from_dir(path: str | os.PathLike) -> IPCPaths:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return IPCPaths(p)


def from_env() -> IPCPaths | None:
    raw = os.environ.get(ENV_IPC_DIR)
    return from_dir(raw) if raw else None


def write_state(paths: IPCPaths, status: str, **extra) -> None:
    """Best-effort : sous Windows, replace échoue (WinError 5) si le serveur lit
    state.json au même instant — vu en prod 2026-06-10, un WritePlan a tué tout
    un run d'agent. Quelques retries puis abandon silencieux : l'état est
    purement consultatif et sera réécrit au prochain changement."""
    payload = {"status": status, "updated_at": time.time(), DRAPEAU_BOITE: 1, **extra}
    tmp = paths.state.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    for attempt in range(5):
        try:
            tmp.replace(paths.state)
            return
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))
    try:
        tmp.unlink()
    except OSError:
        pass


def lit_sa_boite(paths: IPCPaths) -> bool:
    """Le process de ce dossier relève-t-il sa boîte (code actuel) ou seulement followup.txt ?"""
    return bool(read_state(paths).get(DRAPEAU_BOITE))


def read_state(paths: IPCPaths) -> dict:
    if not paths.state.exists():
        return {"status": "unknown"}
    try:
        return json.loads(paths.state.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "unknown"}


def pop_text(path: Path) -> str | None:
    """Read and delete a file atomically. Returns content, or None if missing."""
    if not path.exists():
        return None
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        path.unlink()
    except OSError:
        pass
    return content


def ecrire_followup_herite(paths: IPCPaths, texte: str) -> None:
    """Côté serveur, pour un process de l'ANCIEN code seulement : followup.txt écrit d'un bloc
    (jamais lu à moitié). Sous Windows le remplacement échoue tant que l'agent lit l'ancien
    fichier : quelques essais."""
    tmp = paths.followup.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(texte, encoding="utf-8")
    for tentative in range(10):
        try:
            tmp.replace(paths.followup)
            return
        except PermissionError:
            time.sleep(0.05 * (tentative + 1))
    tmp.unlink(missing_ok=True)
    raise PermissionError(f"followup.txt verrouillé : {paths.followup}")


def is_cancelled(paths: IPCPaths) -> bool:
    return paths.cancel.exists()


def consume_cancel(paths: IPCPaths) -> bool:
    if not paths.cancel.exists():
        return False
    try:
        paths.cancel.unlink()
    except FileNotFoundError:
        pass
    return True


# ------------------------------------------------------------------ boîte aux lettres
#
# TOUS les messages vers l'agent passent par sa boîte, pendant son tour comme quand il attend
# oisif. followup.txt, fichier unique, perdait un message : deux messages poussés avant que
# l'agent ne relève le premier (relance humaine + réveil automatique du manager, deux messages
# tapés coup sur coup), le second ÉCRASAIT le premier.
#
# Ici UN fichier par message, sans verrou et sans jamais renommer un fichier ouvert (Windows) :
#  * dépôt : écrit sous un nom temporaire (fichier fermé), puis renommé d'un bloc vers un nom
#    NEUF — l'agent ne voit jamais un message à moitié écrit ;
#  * prise : celui qui le RENOMME le premier le possède (l'agent pour le lire, le serveur pour
#    le reprendre) ; l'autre voit FileNotFoundError. Un rename est atomique sous POSIX comme
#    sous NTFS, ce qui fait office de verrou entre process ;
#  * ordre : le nom commence par un compteur en nanosecondes STRICTEMENT croissant dans le
#    process (l'horloge Windows avance par pas de 1 à 16 ms), comparé en nombre.

_verrou_ordre = threading.Lock()
_dernier_ns = 0


def _horodatage() -> int:
    global _dernier_ns
    with _verrou_ordre:
        _dernier_ns = max(time.time_ns(), _dernier_ns + 1)
        return _dernier_ns


def deposer_message(paths: IPCPaths, message_id: str, texte: str) -> Path:
    """Côté serveur : dépose `texte` dans la boîte de l'agent (écriture atomique)."""
    paths.inbox.mkdir(parents=True, exist_ok=True)
    nom = f"{_horodatage()}-{message_id}"
    cible = paths.inbox / f"{nom}.txt"
    tmp = paths.inbox / f".{nom}.{os.getpid()}.tmp"
    tmp.write_text(texte, encoding="utf-8")
    tmp.replace(cible)
    return cible


def _ordre_de_depot(chemin: Path) -> tuple[int, str]:
    prefixe = chemin.name.split("-", 1)[0]
    return (int(prefixe) if prefixe.isdigit() else 0, chemin.name)


def _en_boite(paths: IPCPaths) -> list[Path]:
    if not paths.inbox.is_dir():
        return []
    return sorted(paths.inbox.glob("*.txt"), key=_ordre_de_depot)


def message_en_boite(paths: IPCPaths, message_id: str) -> bool:
    """Le message `message_id` attend-il encore d'être lu ?"""
    return any(p.stem.endswith(f"-{message_id}") for p in _en_boite(paths))


def a_du_courrier(paths: IPCPaths) -> bool:
    return bool(_en_boite(paths))


class _Occupe(Exception):
    """Le message existe mais n'a pas pu être pris (Windows : ouvert par un autre process)."""


def _prendre(chemin: Path, suffixe: str) -> str | None:
    """Renomme puis lit et efface : None si quelqu'un l'a pris avant nous, `_Occupe` si le
    renommage a échoué pour une autre raison (le message reste en place, à reprendre)."""
    pris = chemin.with_suffix(suffixe)
    try:
        chemin.replace(pris)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise _Occupe() from exc
    #  Il est à nous : personne d'autre ne connaît ce nom. Une lecture refusée un instant
    #  (antivirus) est retentée ; un échec définitif le laisse sur disque plutôt que l'effacer.
    for tentative in range(5):
        try:
            texte = pris.read_text(encoding="utf-8")
            break
        except OSError:
            time.sleep(0.05 * (tentative + 1))
    else:
        return None
    try:
        pris.unlink()
    except OSError:
        pass
    return texte


def relever_messages(paths: IPCPaths) -> list[str]:
    """Côté agent : relève les messages en attente, dans l'ordre de dépôt. Un message
    momentanément impossible à prendre arrête la relève : ceux d'après attendront la
    prochaine, au lieu de passer devant lui."""
    textes: list[str] = []
    for chemin in _en_boite(paths):
        try:
            texte = _prendre(chemin, ".lu")
        except _Occupe:
            break
        if texte is not None:
            textes.append(texte)
    return textes


def reprendre_message(paths: IPCPaths, message_id: str) -> bool:
    """Côté serveur : retire un message pas encore lu. False s'il a déjà été lu."""
    for chemin in _en_boite(paths):
        if chemin.stem.endswith(f"-{message_id}"):
            try:
                return _prendre(chemin, ".repris") is not None
            except _Occupe:
                return False
    return False


def run_agent_event_loop(initial_prompt, run_query, paths: IPCPaths,
                         keep_warm: bool = True, ttl_seconds: float = 900.0,
                         poll_interval: float = 0.5) -> None:
    """Execute a turn, then (if keep_warm) stay resident in a warm idle loop.

    Warm path: after a clean finish, instead of exiting (cold respawn on the next
    follow-up), the process writes `idle` and polls its inbox (and the legacy
    `followup.txt`). When a
    follow-up arrives it is consumed IN-PROCESS (context stays in RAM → zero
    cold-start). The loop exits (→ FINISHED) on cancel or after `ttl_seconds` of
    inactivity. Paused turns (AskUserQuestion / plan validation) return early and
    are kept warm by repl._resume_paused_warm instead. keep_warm=False restores
    the legacy single-turn behavior (write FINISHED and exit)."""
    def _run_one(prompt) -> str:
        """Run one turn. Returns 'awaiting' (paused), 'finished', or 'error' (already wrote FINISHED + must re-raise)."""
        _existing = read_state(paths)
        write_state(paths, STATUS_RUNNING, turn=_existing.get("turn", 1))
        try:
            run_query(prompt)
        except KeyboardInterrupt:
            return "awaiting"  # graceful stop, don't clobber state
        except Exception:
            # Fatal error (e.g. provider connection exhausted): do NOT leave the IPC
            # stuck on 'running' — write FINISHED so web_v2 stops treating the agent
            # as alive, then re-raise so the process exits non-zero. The disk session
            # carries close_reason='api_error' (persisted by run_query), which is what
            # the runner/web_v2 use to distinguish this from a graceful finish.
            current = read_state(paths)
            write_state(paths, STATUS_FINISHED, turn=current.get("turn", 1))
            raise
        current = read_state(paths)
        if current.get("status") in ("awaiting_plan_validation", "awaiting_input"):
            return "awaiting"
        return "finished"

    if _run_one(initial_prompt) == "awaiting":
        return  # WritePlan / AskUserQuestion a posé un état d'attente : on le laisse.
    if not keep_warm:
        # Tour unique : ne pas écraser un FINISHED déjà écrit par _ipc_finish_cb (vrai tour +
        # close_reason) par un FINISHED nu.
        current = read_state(paths)
        if current.get("status") not in ("awaiting_plan_validation", "awaiting_input", STATUS_FINISHED):
            write_state(paths, STATUS_FINISHED, turn=current.get("turn", 1))
        return
    # Boucle chaude : résident, on attend le tour suivant dans la boîte (ou followup.txt).
    while True:
        prompt = _wait_for_followup(paths, ttl_seconds, poll_interval)
        if prompt is None or _run_one(prompt) == "awaiting":
            return


def _finish(paths: IPCPaths) -> None:
    """Fin du process chaud (TTL, annulation), longtemps APRÈS la fin de son dernier tour :
    `updated_at` prend l'heure de maintenant, donc la fin du tour est gardée à part
    (`fin_de_tour`) : c'est l'heure réelle de la dernière réponse de l'agent."""
    current = read_state(paths)
    extra = {}
    if current.get("status") == STATUS_IDLE:
        extra["fin_de_tour"] = current.get("fin_de_tour") or current.get("updated_at")
    write_state(paths, STATUS_FINISHED, turn=current.get("turn", 1), **extra)


def _wait_for_followup(paths: IPCPaths, ttl_seconds: float, poll_interval: float):
    """Écrit `idle` puis sonde sa boîte (et followup.txt, hérité) ; None (et FINISHED écrit)
    sur annulation ou après `ttl_seconds` d'inactivité. Tous les messages en attente forment
    UN tour, dans l'ordre de dépôt."""
    current = read_state(paths)
    write_state(paths, STATUS_IDLE, turn=current.get("turn", 1))
    last_activity = time.monotonic()
    while True:
        if is_cancelled(paths) or consume_cancel(paths):
            _finish(paths)
            return None
        herite = pop_text(paths.followup)
        courrier = ([herite] if herite is not None else []) + relever_messages(paths)
        if courrier:
            return "\n\n".join(courrier)
        if time.monotonic() - last_activity > ttl_seconds:
            _finish(paths)
            return None
        time.sleep(poll_interval)
