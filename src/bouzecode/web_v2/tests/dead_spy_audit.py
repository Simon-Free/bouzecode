# [desc] Plugin pytest OPT-IN : recense les monkeypatch.setattr JAMAIS invoqués (espions morts). [/desc]
"""Chasse aux ESPIONS MORTS — un `monkeypatch.setattr` que le test n'atteint jamais.

Un remplacement jamais appelé dans un test qui passe est un signal, pas une preuve. Deux
causes le produisent, et ce sont les deux qui fabriquent des tests VERTS ET VIDES :

  * l'espion est branché au MAUVAIS ENDROIT. `tickets.py` est une façade qui ré-exporte
    `_persistence` : patcher `tickets._tickets_lock` ne touche rien, car `_mutate` résout
    le nom dans `_persistence`. Le test croyait neutraliser le verrou ; il ne l'a jamais
    fait, et son assertion « aucune mutation perdue » était vraie grâce au verrou qu'il
    pensait avoir retiré. Même piège, même façade, sur `_upsert_one` (test_crash_markers).
  * la production n'emprunte PLUS ce chemin. Le compteur reste alors à zéro pour toujours
    et l'assertion `== []` ne peut structurellement plus tomber.

Un espion mort est LÉGITIME dans deux cas courants, à écarter à la lecture : la
neutralisation défensive (on coupe un accès réseau/disque qui ne doit pas partir) et le
chemin négatif dont un test JUMEAU prouve, par une assertion positive, que l'espion tire.

Usage (jamais actif par défaut : il remplace la fixture `monkeypatch`) ::

    .venv/Scripts/python.exe -m pytest <chemins> -p bouzecode.web_v2.tests.dead_spy_audit -q

Le rapport est écrit dans `temp_dead_spies.txt` à la racine du dépôt, une ligne par couple
(test, cible). Le lire ainsi : pour chaque ligne, ouvrir le test et se demander « sur quoi
porte l'assertion ? ». Si elle porte sur l'enregistrement de cet espion, MUTER — casser
délibérément la propriété — et regarder si le test tombe. S'il reste vert, il est vide.

Ne PAS le laisser branché dans la suite normale : la fixture `monkeypatch` redéfinie ici
est function-scoped et ne convient pas aux fixtures de portée supérieure.
"""
from __future__ import annotations

import functools

import pytest

# (nodeid::cible, compteur d'appels) armés pendant la session
_ARMES: list[tuple[str, list[int]]] = []
# (nodeid, cible) des espions jamais appelés par un test qui a RÉUSSI
MORTS: list[tuple[str, str]] = []


@pytest.fixture()
def monkeypatch(request):
    """Remplace la fixture pytest : chaque valeur CALLABLE posée est enveloppée d'un compteur."""
    from _pytest.monkeypatch import MonkeyPatch

    patcheur = MonkeyPatch()
    poser = patcheur.setattr

    def poser_en_comptant(cible, nom=..., valeur=..., raising=True):
        if not callable(valeur) or not isinstance(nom, str) or isinstance(cible, str):
            return poser(cible, nom, valeur, raising=raising)
        appels: list[int] = []

        @functools.wraps(valeur)
        def enveloppe(*args, **kwargs):
            appels.append(1)
            return valeur(*args, **kwargs)

        module = getattr(cible, "__name__", cible)
        _ARMES.append((f"{request.node.nodeid}\t{module}.{nom}", appels))
        return poser(cible, nom, enveloppe, raising=raising)

    patcheur.setattr = poser_en_comptant
    yield patcheur
    patcheur.undo()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    resultat = yield
    rapport = resultat.get_result()
    if rapport.when != "call" or rapport.outcome != "passed":
        return
    prefixe = item.nodeid + "\t"
    for etiquette, appels in _ARMES:
        if etiquette.startswith(prefixe) and not appels:
            MORTS.append((item.nodeid, etiquette.split("\t", 1)[1]))


def pytest_sessionfinish(session, exitstatus):
    if not MORTS:
        return
    lignes = sorted({f"{nodeid} -> {cible}" for nodeid, cible in MORTS})
    destination = session.config.rootpath / "temp_dead_spies.txt"
    destination.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    print(f"\n[dead-spy-audit] {len(lignes)} espion(s) jamais invoqué(s) -> {destination}")
