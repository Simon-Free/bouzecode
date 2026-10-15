# [desc] Lecture de l'AGENDA Outlook de l'humain (Graph calendarView, lecture seule), fenetre bornee, reponse qui dit sa couverture. [/desc]
"""L'agenda de l'humain, pour l'assistant du Bureau.

Meme contrat que `ms_activite.rapport_mails` : la fenetre est decidee ICI (le script ne
calcule rien), le plafond `top` est expose et la reponse DIT quand il a coupe (`tronque`,
`avertissement`), pour que l'assistant n'annonce jamais une semaine qu'il n'a pas lue.

Deux sens :
* `a_venir` (defaut) : de minuit UTC aujourd'hui a maintenant + fenetre — « qu'ai-je
  cette semaine ? », creneaux libres avant de proposer une reunion ;
* `passe` : de maintenant - fenetre a maintenant — « qu'ai-je eu comme reunions ? », a
  croiser avec la TODO (une reunion tenue laisse souvent des actions).

Le cache par jour de `ActiviteTransport` s'applique (action `agenda`, champ `start`) : un
jour REVOLU se fige, aujourd'hui et le futur sont toujours relus.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .ms_activite import FENETRES, ActiviteTransport

TOP_EVENEMENTS = 100
SENS = ("a_venir", "passe")


def _iso(instant: datetime) -> str:
    return instant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def bornes(fenetre: str, sens: str, maintenant: datetime | None = None) -> tuple[str, str]:
    """(debut, fin) ISO UTC de la vue. `ValueError` sur une fenetre ou un sens inconnus :
    refuser vaut mieux que lire une periode que personne n'a demandee."""
    if fenetre not in FENETRES:
        raise ValueError(f"fenetre inconnue : {fenetre!r} (attendu : {', '.join(sorted(FENETRES))})")
    if sens not in SENS:
        raise ValueError(f"sens inconnu : {sens!r} (attendu : {', '.join(SENS)})")
    reference = (maintenant or datetime.now(timezone.utc)).astimezone(timezone.utc)
    duree = timedelta(days=FENETRES[fenetre])
    if sens == "passe":
        return _iso(reference - duree), _iso(reference)
    minuit = reference.replace(hour=0, minute=0, second=0, microsecond=0)
    return _iso(minuit), _iso(reference + duree)


def _resume(evenement: dict) -> dict:
    """La forme rendue a l'assistant : de quoi parler du rendez-vous et y renvoyer."""
    garde = ("id", "subject", "start", "end", "location", "organizer", "join_url",
             "web_link", "show_as")
    vue = {cle: evenement.get(cle) for cle in garde if evenement.get(cle)}
    if evenement.get("cancelled"):
        vue["annule"] = True
    if evenement.get("all_day"):
        vue["journee_entiere"] = True
    return vue


def rapport_agenda(fenetre: str = "7j", sens: str = "a_venir", top: int = TOP_EVENEMENTS,
                   transport: ActiviteTransport | None = None,
                   maintenant: datetime | None = None) -> dict:
    """Les evenements de la fenetre, du plus tot au plus tard, avec leur couverture."""
    debut, fin = bornes(fenetre, sens, maintenant)
    canal = transport or ActiviteTransport(maintenant=maintenant)
    brut = canal.agenda_brut(debut, fin, top=top)
    evenements = sorted(brut["evenements"], key=lambda e: str(e.get("start") or ""))
    tronque = bool(brut.get("has_more")) or len(evenements) >= top
    rapport = {"ok": True, "fenetre": fenetre, "sens": sens, "debut": debut, "fin": fin,
               "plafond": top, "total": len(evenements), "tronque": tronque,
               "avertissement": "", "evenements": [_resume(e) for e in evenements]}
    if tronque:
        dernier = str(evenements[-1].get("start") or "") if evenements else debut
        rapport["avertissement"] = (
            f"COUVERTURE INCOMPLETE : plafond de {top} evenements atteint, tu ne tiens que "
            f"jusqu'au {dernier}. Rappelle Agenda avec un `top` plus grand avant de dire "
            f"qu'un creneau est libre ou qu'il n'y a rien d'autre.")
    return rapport
