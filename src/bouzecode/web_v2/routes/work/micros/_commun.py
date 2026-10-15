# [desc] Outils des routes du Bureau : erreur à la forme unique, refus d'un geste sérialisé, chantier ou tâche ou 404. [/desc]
from __future__ import annotations

from ....services.work import micros as service
from ..._errors import erreur

def _fail(message: str, status: int = 400, code: str = "requete_invalide"):
    """Forme unique des erreurs (spec ticketing §9) : `routes/_errors.erreur`."""
    return erreur(code, message, status)


def _refus(refus):
    return erreur(refus.code, refus.message, refus.status, **refus.details)


def _macro_or_404(macro_id: str):
    macro = service.get_macro(macro_id)
    if macro is None:
        return None, _fail(f"chantier {macro_id} inconnu", 404, "chantier_inconnu")
    return macro, None


def _micro_or_404(micro_id: str):
    micro = service.get_micro(micro_id)
    if micro is None:
        return None, _fail(f"tâche {micro_id} inconnue", 404, "tache_inconnue")
    return micro, None

