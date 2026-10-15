# [desc] testd : limite de durée d'un test — adaptative (max(10 s, 5 × sa durée habituelle), plafonnée à 30 s hors navigateur / 60 s navigateur), défaut de sa catégorie s'il n'a jamais été mesuré, au moins 300 s s'il est lent ; `timeouts.per_test` / `per_test_browser` la fixent, 0 coupe [/desc]
"""Mesuré le 2026-10-14 : un parcours navigateur chaud tient en ~1 s, un test hors navigateur en
4 ms à 0,2 s ; le test légitime le plus long vu (un exercice complet dans un navigateur) en ~4 s.
Une limite fixe de 30 s (60 s navigateur) laissait donc un test d'une seconde bloqué une demi-
minute. Un test déjà mesuré reçoit `FACTEUR` fois sa durée habituelle (médiane des dernières
mesures, cf. budget.recentes), au moins `PLANCHER_S`, jamais plus que sa catégorie ; un test
inconnu garde la limite de sa catégorie le temps d'être mesuré. Une limite écrite dans
tests.yaml est prise telle quelle (pas d'adaptation)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

LIMITE_COURTE_S = 30
LIMITE_NAVIGATEUR_S = 60
LIMITE_LENTE_S = 300
PLANCHER_S = 10
FACTEUR = 5


def _secondes(valeur: float) -> str:
    """1,8 s : virgule décimale, comme le reste du rapport."""
    return f"{valeur:.1f}".replace(".", ",").replace(",0", "") + " s"


@dataclass(frozen=True)
class Limites:
    courte: int = LIMITE_COURTE_S          # test hors navigateur
    navigateur: int = LIMITE_NAVIGATEUR_S  # test navigateur
    lents: tuple[str, ...] = ()            # motifs `impacted.slow`, relatifs à `racine`
    racine: str = ""
    adaptative: bool = True                # False : limite fixée dans tests.yaml
    habituelles: dict = field(default_factory=dict)  # {nodeid: durée habituelle (s)}

    def pour(self, nodeid: str, navigateur: bool, marque_lent: bool, cwd: str) -> int:
        """Limite du test (0 : aucune)."""
        return self.motivee(nodeid, navigateur, marque_lent, cwd)[0]

    def motivee(self, nodeid: str, navigateur: bool, marque_lent: bool,
                cwd: str) -> tuple[int, str]:
        """(limite, pourquoi) — le pourquoi va tel quel dans le rapport d'un test tué."""
        base = self.navigateur if navigateur else self.courte
        cle = "timeouts.per_test_browser" if navigateur else "timeouts.per_test"
        if base <= 0:
            return 0, f"`{cle}: 0`"
        if marque_lent or self.liste_lent(nodeid, cwd):
            limite = max(base, LIMITE_LENTE_S)
            return limite, f"limite {limite} s : test lent (`impacted.slow` ou marqueur `slow`)"
        habituelle = self.habituelles.get(nodeid)
        if not self.adaptative:
            return base, f"limite {base} s, `{cle}` de .bouzecode/tests.yaml"
        if habituelle is None:
            return base, (f"limite {base} s, défaut des tests {'navigateur' if navigateur else 'hors navigateur'} "
                          f"(jamais mesuré)")
        voulue = max(PLANCHER_S, FACTEUR * habituelle)
        if voulue >= base:
            return base, (f"limite {base} s, plafond des tests "
                          f"{'navigateur' if navigateur else 'hors navigateur'} "
                          f"({FACTEUR} × {_secondes(habituelle)} habituel le dépasse)")
        limite = int(-(-voulue // 1))  # arrondi au-dessus
        plancher = f", plancher {PLANCHER_S} s" if voulue == PLANCHER_S else ""
        return limite, f"limite {limite} s = {FACTEUR} × {_secondes(habituelle)} habituel{plancher}"

    def vidage(self, navigateur: bool) -> int:
        """`faulthandler_timeout` d'un sous-run (une valeur par process) : la plus petite limite
        qui peut s'y appliquer — un sous-run hors navigateur peut contenir des tests navigateur
        quand la collecte a échoué. Limites adaptatives : le plancher, pour que la pile d'un test
        tué à 10 s soit déjà dans la sortie (un test légitime de plus de 10 s n'y ajoute qu'un
        vidage, sans être tué)."""
        candidates = [self.navigateur] if navigateur else [self.courte, self.navigateur]
        plus_petite = min((c for c in candidates if c > 0), default=0)
        if plus_petite and self.adaptative and self.habituelles:
            return min(plus_petite, PLANCHER_S)
        return plus_petite

    def liste_lent(self, nodeid: str, cwd: str) -> bool:
        if not self.lents:
            return False
        #  Import tardif, comme job.py : `bouzecode.backend.tools` enregistre tous les outils.
        from ...tools.ops.tests_config import correspond
        fichier = nodeid.split("::", 1)[0].replace("\\", "/")
        chemins = {fichier}
        if self.racine:
            chemins.add(Path(os.path.relpath(Path(cwd) / fichier, self.racine)).as_posix())
        return any(correspond(motif, chemin) or chemin.startswith(motif.rstrip("/") + "/")
                   for motif in self.lents for chemin in chemins)


def limites_de(config: dict, habituelles: dict | None = None) -> Limites:
    """`timeouts.per_test` remplace les deux limites, `timeouts.per_test_browser` celle des
    tests navigateur, et l'une ou l'autre coupe l'adaptation ; `impacted.slow` désigne les
    tests lents ; `habituelles` : durée habituelle de chaque test déjà mesuré."""
    delais = config.get("timeouts") or {}
    par_test, navigateur = delais.get("per_test"), delais.get("per_test_browser")
    courte = LIMITE_COURTE_S if par_test is None else int(par_test)
    if navigateur is None:
        navigateur = LIMITE_NAVIGATEUR_S if par_test is None else par_test
    lents = (config.get("impacted") or {}).get("slow") or ()
    explicite = par_test is not None or delais.get("per_test_browser") is not None
    return Limites(courte, int(navigateur), tuple(lents), str(config.get("_racine") or ""),
                   not explicite, dict(habituelles or {}))
