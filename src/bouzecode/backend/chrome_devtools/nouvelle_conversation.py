# [desc] Remet le navigateur dans l'état d'un démarrage quand une NOUVELLE conversation commence (/clear) : Chrome arrêté, outils mcp__chrome-devtools__* retirés s'ils n'étaient là que par activation. [/desc]
"""`/clear` et les outils navigateur.

Session 2fa7d817 (2026-10-07) : l'agent active chrome-devtools au tour 12, l'utilisateur fait
`/clear`, et la session suivante (d407d73d), qui n'ouvre jamais le navigateur, relit à chacun
de ses 27 appels les 30 outils du manifeste (≈ 13 k tokens, préfixe 32,4 k au lieu de 20 k).
Le registre d'outils est global au process : `/clear` vidait la conversation, jamais lui.

Une nouvelle conversation repart donc comme un process neuf :
  - les outils ne restent déclarés que si la capacité est posée pour le process
    (`BOUZECODE_ENABLE_CHROME_DEVTOOLS=1`, `--enable-chrome-devtools`) — c'est ce qu'un
    démarrage aurait déclaré ; sinon ils sont retirés, et `EnableChromeDevtools` les remet ;
  - le Chrome de la conversation close est ARRÊTÉ. Il ne sert plus : ses onglets et sa
    session appartiennent à la conversation d'avant, et le premier outil utilisé en rallume
    un (démarrage paresseux). Le garder, c'est un Chrome + un `npx` résidents pour rien —
    et les outils retirés, plus rien ne permettrait de l'arrêter avant la fin du process ;
  - les options (fenêtre visible, profil persistant) reviennent au défaut. Le profil reste
    sur le disque : le redemander avec `profile=` retrouve la session ouverte.

La reprise d'une session (`reprendre_les_outils_de_la_session`) n'est pas concernée : elle
relit `outils_navigateur` du JSON de la session reprise, que `/clear` a enregistré AVANT de
repartir de zéro.
"""
from __future__ import annotations

import os
import threading

from . import launcher


def _chromes_de_la_conversation_close(appelant: int) -> list[int]:
    """Les transports à arrêter : celui de l'appelant, et ceux des fils déjà terminés.

    Un lot parallèle exécute ses outils dans des fils jetables : le Chrome qu'un tel fil a
    allumé n'est plus joignable par personne, il est orphelin. Ceux des fils VIVANTS (un
    sous-agent encore au travail) ne sont pas touchés."""
    fils_vivants = {fil.ident for fil in threading.enumerate()}
    return [ident for ident in launcher._TRANSPORTS
            if ident == appelant or ident not in fils_vivants]


def repartir_sans_navigateur() -> str:
    """Nouvelle conversation : Chrome arrêté, outils navigateur ramenés à l'état de démarrage.

    Rend ce qui a été fait, ou "" quand il n'y avait rien à défaire."""
    with launcher._lock:
        appelant = threading.get_ident()
        launcher._OPTIONS.pop(appelant, None)
        arretes = sum(launcher._teardown_ident(ident)
                      for ident in _chromes_de_la_conversation_close(appelant))
        capacite_declaree = os.environ.get("BOUZECODE_ENABLE_CHROME_DEVTOOLS") == "1"
        retires = 0
        if not capacite_declaree and not launcher._any_active():
            retires = launcher._unregister_shared_tools()
        if not (arretes or retires):
            return ""
        return f"chrome-devtools : {arretes} Chrome arrêté(s), {retires} outil(s) retiré(s)."
