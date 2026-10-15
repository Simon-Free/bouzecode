# [desc] Le message qui réveille un manager : le bloc de preuve de chaque enfant, ses enfants mort-nés ou bloqués sur une question, et le rappel qu'aucune suite n'est automatique. [/desc]
"""Extrait de `wake_parents.py` : `digest_du_manager`, texte pur construit sur les prédicats de
`wake` (lus sur `ticket.state`) et les blocs de `wake_digest`. Ré-exporté par `wake_parents`."""
from __future__ import annotations

from . import wake_digest


def digest_du_manager(child_tickets: list[dict]) -> str:
    """Le message qui réveille un manager : chaque enfant avec sa PREUVE (`wake_digest`)."""
    from . import wake  # import différé : wake importe ce module (via wake_parents)
    launched = [t for t in sorted(child_tickets, key=lambda t: t["id"])
                if wake.child_counts_for_wake(t)]
    awaiting = [t for t in launched if wake.child_blocked_on_question(t)]
    stillborn = [t for t in launched if wake.launch_failed(t)]
    lines = [
        "Tous tes enfants ont fini leur tour. Digest de leurs issues :",
        "(Rappel : cette relance automatique est le protocole normal — tu avais correctement "
        "clos ton tour en attente. Clore n'abandonne jamais la mission ; le système te réveille "
        "à chaque fin d'enfant. Après avoir traité ce digest, re-clos ton tour : tu seras à "
        "nouveau réveillé si nécessaire. Ne boucle jamais sur Fleet(list)/Methodology pour surveiller.)",
        "",
    ]
    for t in launched:
        lines += wake_digest.child_block(t, delivered=wake.work_delivered(t))
    lines.append("")
    if stillborn:
        lines += [
            f"⛔ Enfant(s) dont le LANCEMENT A ÉCHOUÉ : {', '.join(t['id'] for t in stillborn)}. "
            "Aucun agent n'a démarré, AUCUN travail n'a été fait — leur tâche n'a pas commencé, "
            "ne la considère jamais comme faite.",
            "À TOI de décider pour chacun : le relancer (POST /api/projects/<slug>/tickets/<id>/runs), "
            "redispatcher la tâche autrement (autre isolation), ou ESCALADER à l'utilisateur si "
            "le motif se répète. Aucune reprise automatique n'aura lieu.", ""]
    if awaiting:
        lines += [
            f"⛔ Enfant(s) BLOQUÉ(S) sur une QUESTION en attente de réponse : "
            f"{', '.join(t['id'] for t in awaiting)}.",
            "Pour CHACUN : soit tu peux TRANCHER seul → réponds-lui via "
            "MessageAgent(ticket_id=<id>, text=<ta réponse>) ; soit tu ne peux PAS trancher "
            "seul → ESCALADE la question à l'utilisateur via AskUserQuestion. Tu ne codes "
            "JAMAIS toi-même et tu ne laisses AUCUN enfant bloqué sans réponse.", ""]
    lines += [
        "AUCUNE suite automatique n'est déclenchée : un travail livré n'est ni testé, ni "
        "relu, ni mergé tant que TU ne le demandes pas. À toi de décider, pour chaque "
        "enfant livré : le relancer avec des objections (MessageAgent), intégrer sa branche, "
        "ou, si tu doutes de la livraison, relire toi-même le diff ou lancer un sous-agent de "
        "relecture en lecture seule (Agent, isolation shared).",
        "Synthétise ensuite. Si un enfant est en échec ou CRASHED, redispatche un Agent pour "
        "la seule tâche en échec (avec le contexte de l'échec) puis re-termine ton tour.",
    ]
    return "\n".join(lines)
