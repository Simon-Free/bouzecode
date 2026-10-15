# [desc] testd : signaux du rapport, sans rien tuer — tests lents (phase d'appel > 5 s, `timeouts.slow_signal`) avec un indice, et relances automatiques neutralisées (`flaky`, `--reruns`, lignes RERUN) [/desc]
"""Mesuré le 2026-10-14 : un parcours navigateur chaud prend 0,6 à 1 s, une page 0,3 s, un test
hors navigateur 4 ms à 0,2 s. Au-delà de quelques secondes, c'est un démarrage par test (serveur,
navigateur), une attente fixe (`sleep`, délai Playwright de 30 s sur un élément absent) ou un
test qui devrait être rangé en lent : le rapport le DIT, sans tuer (la limite, cf. garde.limites,
s'en charge)."""
from __future__ import annotations

import re
from pathlib import Path

from ..run.split import evenements

SEUIL_LENT_S = 5.0
_LENTS_MONTRES = 10
_INDICE_DEMARRAGE = "démarrage par test ou attente fixe probable — un parcours navigateur chaud prend ~1 s"
_INDICE_LISTE_LENT = "désélectionné en lent ?"
_RERUN = re.compile(r"^.*\bRERUN\b", re.MULTILINE)


def seuil_lent(config: dict) -> float:
    """`timeouts.slow_signal` de tests.yaml, 5 s par défaut (0 : pas de signal)."""
    valeur = (config.get("timeouts") or {}).get("slow_signal")
    return SEUIL_LENT_S if valeur is None else float(valeur)


def _secondes(valeur: float) -> str:
    return f"{valeur:.1f}".replace(".", ",") + " s"


def section_lents(dossiers: list[Path], seuil: float, liste_lent) -> str:
    """Les tests dont la phase d'appel a dépassé `seuil`, les plus longs d'abord ;
    `liste_lent(nodeid)` : le test est-il sous `impacted.slow` ?"""
    if seuil <= 0:
        return ""
    appels = {e["id"]: e["c"] for e in evenements(dossiers) if e["e"] == "end" and "c" in e}
    lents = sorted(((d, n) for n, d in appels.items() if d > seuil), reverse=True)
    if not lents:
        return ""
    lignes = [f"[testd] tests lents (> {_secondes(seuil)}) :"]
    for duree, nodeid in lents[:_LENTS_MONTRES]:
        indice = _INDICE_LISTE_LENT if liste_lent(nodeid) else _INDICE_DEMARRAGE
        lignes.append(f"  {nodeid} — {_secondes(duree)} : {indice}")
    if len(lents) > _LENTS_MONTRES:
        lignes.append(f"  … et {len(lents) - _LENTS_MONTRES} autres")
    return "\n".join(lignes) + "\n"


def section_relances(dossiers: list[Path], sorties: list[Path]) -> str:
    """Relances automatiques coupées par `_bz_sans_relance`, nommées pour que l'auteur retire
    le marqueur ; des lignes RERUN dans la sortie disent qu'une relance a échappé au plugin."""
    marques, options = set(), set()
    for evenement in evenements(dossiers):
        if evenement["e"] == "flaky":
            marques.update(evenement["ids"])
        elif evenement["e"] == "relances":
            options.add(evenement["option"])
    vues = sum(len(_RERUN.findall(s.read_text(encoding="utf-8", errors="replace")))
               for s in sorties if s.exists())
    morceaux = []
    if marques:
        fichiers = sorted({n.split("::", 1)[0] for n in marques})
        morceaux.append(
            f"[testd] relances automatiques neutralisées : {len(marques)} tests marqués flaky "
            f"(un échec n'est joué qu'une fois) ; retirer le marqueur (posé par le test, sa "
            f"classe, son module ou un conftest) dans : {', '.join(fichiers)}\n")
    for option in sorted(options):
        morceaux.append(f"[testd] relances automatiques neutralisées : option `{option}` ignorée.\n")
    if vues:
        morceaux.append(f"[testd] {vues} lignes RERUN dans la sortie : une relance a échappé à "
                        f"la neutralisation (plugin de relance chargé sous un autre nom ?).\n")
    return "".join(morceaux)
