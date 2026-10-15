# [desc] Attente d'un enfant web par son parent : sondage réveillable (courrier, interruption) et verdict rendu sans jamais faire passer une attente cassée pour un dispatch raté. [/desc]
"""Le parent qui dispatche un ticket en mode pause se bloque ici jusqu'au verdict de l'enfant.
La relecture des enfants elle-même est dans `enfants.attendre_web` / `enfants.attendre_ticket`."""
from __future__ import annotations


_WAIT_POLL_INTERVAL = 10   # s entre deux sondages du ticket enfant
_WAIT_TIMEOUT = 1800       # s (30 min) avant de rendre la main sans verdict


class AttenteInterrompue(Exception):
    """Le parent qui attendait son enfant est réveillé : un message lui est arrivé (ou on
    l'interrompt). L'enfant, lui, continue."""


def _dormir(sleep, reveil) -> bool:
    """Attend un intervalle de sondage ; True si `reveil()` a sonné entre-temps."""
    if reveil is None:
        sleep(_WAIT_POLL_INTERVAL)
        return False
    for _ in range(int(_WAIT_POLL_INTERVAL / 0.5)):
        if reveil():
            return True
        sleep(0.5)
    return bool(reveil())


def _reveil(config: dict):
    """Ce qui réveille un parent bloqué sur son enfant : du courrier ou une interruption."""
    sondes = [config.get(cle) for cle in ("_inbox_peek", "_cancel_peek") if config.get(cle)]
    return (lambda: any(sonde() for sonde in sondes)) if sondes else None


def _wait_for_child(wait_verdict, ticket_id: str, project_slug: str,
                    head: str, config: dict) -> str:
    """Bloque sur l'enfant et rend son verdict. Si c'est l'ATTENTE qui échoue, le retour
    annonce d'abord que le TICKET EXISTE : une attente cassée n'est PAS un dispatch raté.
    Un manager qui croit son dispatch raté redispatche → tickets EN DOUBLE (c'est le faux
    négatif du 2026-07-27, miroir exact du faux succès corrigé le matin même). Le retour ne
    porte donc JAMAIS le préfixe `Error:`, réservé au cas « aucun enfant n'a été créé »."""
    try:
        verdict = wait_verdict(ticket_id, project_slug)
    except AttenteInterrompue:
        config["_bg_agent_launched"] = True
        return (f"{head}\nAttente INTERROMPUE : un message t'est arrivé (il suit ce résultat). "
                f"L'enfant {ticket_id} continue EN FOND ; tu seras ré-invoqué avec son verdict "
                f"quand il aura terminé. Ne le redispatche pas.")
    except Exception as exc:  # noqa: BLE001 — 404/refus réseau/JSON illisible : même issue
        # L'enfant EST en vol : on pose le drapeau comme en mode fond pour que le
        # turn-protocol laisse le tour ouvert au lieu de pousser vers FinalAnswer.
        config["_bg_agent_launched"] = True
        return (
            f"{head}\n"
            f"⚠ LE TICKET EXISTE ET SON AGENT TOURNE — seule l'ATTENTE a échoué "
            f"({type(exc).__name__}: {exc}). NE REDISPATCHE PAS ce travail, tu créerais un "
            f"ticket EN DOUBLE. Tu seras ré-invoqué automatiquement avec le verdict de "
            f"l'enfant quand il aura terminé ; d'ici là tu peux suivre son état avec "
            f"Fleet(action='list') ou le ré-instruire avec MessageAgent(ticket_id="
            f"'{ticket_id}')."
        )
    return f"{head}\nVerdict de l'enfant :\n{verdict}"


def _attente_de_mes_enfants(config: dict):
    """Attendre un enfant = le relire comme CheckAgentResult et les garde-fous le relisent."""
    from . import enfants
    return lambda ticket_id, _slug: enfants.attendre_web(ticket_id, config)
