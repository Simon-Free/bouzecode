# [desc] Digest de réveil du manager : chaque enfant arrive avec la PREUVE qui permet de trancher sans redemander. [/desc]
"""Ce que le manager reçoit quand ses enfants ont fini.

L'ancienne version ne rendait qu'UNE ligne par enfant (`- Ticket <id> « <titre> » : <issue>`)
plus, parfois, un `VERDICT:` entre parenthèses. Un manager ne pouvait donc RIEN décider :
il redemandait le détail par `MessageAgent` — et cette ré-instruction ne changeait pas
`wake.children_signature`, donc son réveil ne revenait jamais (cas mesuré le 2026-07-29 sur
le manager 0123456789ab : « le digest ne me donne pas la cause racine, et je viens de lui
redemander le détail par message », puis 54 minutes de sommeil).

Chaque enfant arrive maintenant avec DE QUOI TRANCHER :
  * enfant en ÉCHEC / PLANTÉ  → la RAISON (close_reason de la session, dernier mot de
    l'agent, fichiers en péril, erreur de provisionnement) ;
  * enfant LIVRÉ              → de quoi JUGER (branche + head commité, nombre de tours
    clos, extrait du rapport final).

COÛT — deux invariants, tenus par construction :
  1. le digest n'est construit QU'AU RÉVEIL (`process_wakes`), jamais au tick du watchdog :
     `wake.children_signature`/`ticket_terminal` restent purs, donc `wake.tick()` sur un
     projet sans rien à réconcilier continue de ne rouvrir AUCUNE session
     (test_wake_watchdog_idle_cost) ;
  2. UNE seule lecture d'agent + UNE seule lecture de session PAR ENFANT (le run le plus
     récent), quel que soit le nombre de champs qu'on en tire. L'ancienne version payait
     déjà exactement ça pour les enfants livrés (`_verdict_line`) et n'en tirait qu'une
     ligne ; on tire tout d'une seule ouverture.

TAILLE — le digest est réinjecté dans le contexte du manager à CHAQUE réveil, et son
contexte est fini. Bornes explicites ci-dessous."""
from __future__ import annotations

import re
from pathlib import Path

from ...runtime import runner
from ..sessions import store
from . import tickets as tickets_svc

# Un rapport de FinalAnswer est écrit CONCLUSION D'ABORD (contrat du harnais : la réponse,
# pas le journal) → on garde la TÊTE. 600 caractères ≈ 150 jetons : un manager supervise en
# pratique 3 à 10 enfants, soit ≤ 1500 jetons de rapports par réveil — le prix d'un seul
# aller-retour `MessageAgent` qu'on évite, et un ordre de grandeur sous le contexte manager.
_REPORT_CHARS = 600
# Un agent PLANTÉ s'est arrêté en plein milieu : l'information est à la FIN (message d'erreur,
# phrase coupée) → on garde la QUEUE, et plus courte : c'est un indice, pas un rapport.
_LAST_WORD_CHARS = 300

_THINKING_RE = re.compile(r"<thinking>.*?</thinking>", re.DOTALL | re.IGNORECASE)


def newest_run(ticket: dict) -> dict | None:
    """Le run le PLUS RÉCENT du ticket (`add_run` insère en tête). C'est lui qui porte
    l'information fraîche : le rapport d'un validateur spawné après coup prime sur celui du
    codeur, et un enfant relancé prime sur sa passe précédente."""
    return next((r for r in ticket.get("runs") or [] if isinstance(r, dict)), None)


def run_turns(ticket: dict) -> int:
    """Nombre de TOURS clos par l'enfant, tous runs confondus (compteur `turns` posé par
    `tickets.mark_run_completed`, PUR à lire). Sert au digest ET à la signature de réveil."""
    return sum(int(r.get("turns") or 0)
               for r in ticket.get("runs") or [] if isinstance(r, dict))


def read_run_evidence(run: dict | None) -> dict[str, str]:
    """UNE ouverture d'agent + UNE ouverture de session, et tout ce qu'on peut en tirer.

    Renvoie {close_reason, report, last_text} — vides si l'agent ou la session est
    indisponible (agent purgé, session jamais écrite) : le digest doit se dégrader, jamais
    échouer, sinon un enfant illisible priverait le manager de TOUS les autres."""
    empty = {"close_reason": "", "report": "", "last_text": ""}
    if not run or not run.get("agent_id"):
        return empty
    agent = runner.load_agent(run["agent_id"])
    if agent is None or not getattr(agent, "session_path", ""):
        return empty
    data = store.load_session_json(Path(agent.session_path)) or {}
    messages = data.get("messages") or []
    return {
        "close_reason": str(data.get("close_reason") or ""),
        "report": tickets_svc.extract_final_answer(messages),
        "last_text": _last_assistant_text(messages),
    }


def _last_assistant_text(messages: list) -> str:
    """Dernier texte livré par l'agent, THINKING retiré. C'est le « dernier mot » d'un agent
    mort sans rapport : sans lui, un enfant planté n'apporte au manager qu'une étiquette."""
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        content = message.get("content")
        if isinstance(content, str):
            text = _THINKING_RE.sub("", content).strip()
            if text:
                return text
    return ""


def _head(text: str, limit: int) -> str:
    """Tête bornée, sur une seule ligne, avec la coupe ANNONCÉE : un extrait muet ferait
    croire au manager qu'il a tout lu."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    return f"{flat[:limit]}… [coupé : {len(flat)} caractères au total]"


def _tail(text: str, limit: int) -> str:
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    return f"[…début coupé : {len(flat)} caractères au total] {flat[-limit:]}"


def verdict_line(report: str) -> str:
    """La ligne 'VERDICT: …' d'un rapport, "" s'il n'y en a pas. Elle vit à la FIN du
    rapport (contrat des validateurs) donc la tête bornée ne la contient pas : on l'extrait
    séparément pour ne jamais la perdre à la coupe."""
    for raw in report.splitlines():
        stripped = raw.strip()
        if stripped.upper().startswith("VERDICT:"):
            return stripped
    return ""


def _delivery_line(ticket: dict) -> str:
    """De quoi JUGER une livraison SANS ouvrir quoi que ce soit : où est le code (branche +
    head commité par la récolte), et combien de tours l'enfant a clos (un enfant ré-instruit
    qui a re-livré affiche 2, 3… — c'est la preuve visible qu'il a retravaillé)."""
    meta = ticket.get("worktree") if isinstance(ticket.get("worktree"), dict) else {}
    branch = str(meta.get("branch") or "")
    head = str(meta.get("delivered_head") or "")[:12]
    where = f"branche {branch}" if branch else "dépôt principal (ticket partagé)"
    if head:
        where += f" @ {head}"
    return f"    LIVRAISON : {where} — {run_turns(ticket)} tour(s) clos."


def _reason_lines(ticket: dict, evidence: dict[str, str]) -> list[str]:
    """La RAISON réelle d'un enfant qui n'a pas livré : pourquoi son tour s'est arrêté
    (`close_reason` stampé par la boucle), ce qu'il disait juste avant de mourir, et les
    fichiers qu'il laisse en péril. Sans ça le manager n'a qu'une étiquette et redemande."""
    lines: list[str] = []
    if evidence["close_reason"]:
        lines.append(f"    ⛔ RAISON (clôture de la boucle) : {evidence['close_reason']}")
    if evidence["last_text"]:
        lines.append(f"    DERNIER MOT DE L'AGENT : {_tail(evidence['last_text'], _LAST_WORD_CHARS)}")
    peril = ticket.get("uncommitted")
    if isinstance(peril, list) and peril:
        lines.append(f"    ⛔ TRAVAIL NON COMMITÉ (perdu si le worktree est nettoyé) : "
                     f"{', '.join(str(f) for f in peril[:10])}")
    if not lines:
        lines.append("    (aucune trace exploitable : ni rapport, ni close_reason, ni "
                     "session lisible — l'agent n'a rien laissé.)")
    return lines


def child_block(ticket: dict, delivered: bool) -> list[str]:
    """Le bloc d'UN enfant : sa ligne d'issue, puis la matière pour décider. UNE seule
    ouverture de session (`read_run_evidence`), quel que soit le nombre de lignes produites."""
    from . import wake  # import différé : wake importe ce module (issue/étiquettes)
    lines = [f"- Ticket {ticket['id']} « {ticket['title']} » : {wake.ticket_outcome(ticket)}"]
    if wake.launch_failed(ticket):
        return lines  # aucun agent n'a démarré : l'erreur est DÉJÀ dans l'étiquette d'issue
    evidence = read_run_evidence(newest_run(ticket))
    verdict = verdict_line(evidence["report"])
    if verdict:
        lines[0] += f" ({verdict})"
    if delivered:
        lines.append(_delivery_line(ticket))
    else:
        lines += _reason_lines(ticket, evidence)
    if evidence["report"]:
        lines.append(f"    RAPPORT DE L'AGENT : {_head(evidence['report'], _REPORT_CHARS)}")
    return lines
