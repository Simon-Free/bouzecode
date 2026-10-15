# [desc] Replays the real FinalAnswer calls of the 2026-09-25 DeepSeek sessions through the « parcours vérifiés » gate: false positives must pass, real gaps must still be refused. [/desc]
"""Rejeu des clôtures RÉELLES de l'essai du 2026-09-25 (agents DeepSeek, portail des énigmes).

La porte des parcours y a produit 9 faux positifs sur 10 refus. Les sessions sont figées en
fixtures compactes (`fixtures/parcours_reels/*.json.gz` : appels, résultats, première demande,
et le contenu des scripts /tmp qu'une recette lançait) ; chaque cas rejoue `manques()` sur le
journal tel qu'il était au moment de la FinalAnswer (son propre résultat exclu).

Numérotation : `tN` = N-ième message assistant de la session, `msg` = indice dans `messages`.
"""
from __future__ import annotations

import gzip
import json
from functools import lru_cache
from pathlib import Path

import pytest

from bouzecode.backend.agent import close_parcours as cp

FIXTURES = Path(__file__).parent / "fixtures" / "parcours_reels"


@lru_cache(maxsize=None)
def _session(nom: str) -> dict:
    with gzip.open(FIXTURES / f"{nom}.json.gz", "rt", encoding="utf-8") as fichier:
        return json.load(fichier)


def _cloture(nom: str, indice: int) -> tuple[object, list]:
    """(parcours déclarés, journal) au moment de la FinalAnswer `messages[indice]`."""
    messages = _session(nom)["messages"]
    final = next(tc for tc in messages[indice]["tool_calls"] if tc["name"] == "FinalAnswer")
    fin = indice + 1
    while fin < len(messages) and messages[fin].get("role") != "assistant":
        fin += 1
    journal = messages[:indice + 1] + [m for m in messages[indice + 1:fin]
                                       if m.get("tool_call_id") != final["id"]]
    return final["input"].get("parcours_verifies"), journal


@pytest.fixture(autouse=True)
def _scripts_de_la_session(monkeypatch):
    """Les recettes lançaient des scripts /tmp (smoke.js…) : on sert leur contenu figé."""
    def lire(chemin: str) -> str | None:
        for session in ("6bafe9cd5ee7", "625883f162f2", "62a7742e950e"):
            contenu = _session(session)["fichiers"].get(chemin)
            if contenu is not None:
                return contenu
        return None
    monkeypatch.setattr(cp, "_lire_script", lire)
    monkeypatch.setattr(cp, "_ecriture_hors_depot_racines", lambda: ())


def _manques(nom: str, indice: int) -> list[str]:
    parcours, journal = _cloture(nom, indice)
    delegue = not str(_session(nom)["parent"] or "").startswith("dispatcher:")
    return cp.manques(parcours, journal, delegue=delegue)


# Faux positifs de l'essai (refus réels, ou refus que la porte actuelle produirait) : 0 refus.
FAUX_POSITIFS = [
    ("6bafe9cd5ee7", 182, "t36 : `python3 scraper/kangourou.py …` réellement lancé"),
    ("6bafe9cd5ee7", 315, "t63 : scraper relancé + étoile cliquée (« cliquer » dans le parcours)"),
    ("6bafe9cd5ee7", 322, "t65 : « choix conservés après rechargement », geste prouvé ailleurs"),
    ("6bafe9cd5ee7", 601, "t114 : seuls des scripts Playwright /tmp écrits après le navigateur"),
    ("6bafe9cd5ee7", 672, "t128 : « curl -s -o /dev/null -w '%{http_code}' sur http://… »"),
    ("6bafe9cd5ee7", 710, "t136 : curl dans `$(…)`, serveur en sous-shell, ImageQuestion"),
    ("6bafe9cd5ee7", 741, "t140 : recette silencieuse `bash /tmp/pe-pw/all.sh 8802`"),
    ("6bafe9cd5ee7", 767, "t142 : clôture livrée"),
    ("6bafe9cd5ee7", 786, "t143 : clôture livrée"),
    ("625883f162f2", 375, "t77 : enfant sans interface"),
    ("625883f162f2", 382, "t79 : enfant sans interface"),
    ("625883f162f2", 390, "t81 : enfant sans interface"),
    ("625883f162f2", 401, "t83 : enfant sans interface"),
    ("62a7742e950e", 177, "t41 (msg 177) : « compteur conservé, énigme acceptée » = état, pas geste"),
]


@pytest.mark.parametrize("nom, indice, cas", FAUX_POSITIFS, ids=[c[2][:4] + f"-{c[1]}"
                                                               for c in FAUX_POSITIFS])
def test_les_faux_positifs_de_l_essai_passent(nom, indice, cas):
    assert _manques(nom, indice) == [], cas


# L'enfant 625883f1 est délégué (exempté) : ses preuves doivent AUSSI être reconnues une à une,
# comme si la porte s'appliquait (c'est le cas s'il écrit un jour un fichier d'interface).
PREUVES_ENFANT = [(375, 0), (382, 0), (382, 1), (390, 3), (401, 1), (401, 2)]


@pytest.mark.parametrize("indice, rang", PREUVES_ENFANT)
def test_les_preuves_textuelles_de_l_enfant_sont_reconnues(indice, rang):
    parcours, journal = _cloture("625883f162f2", indice)
    probleme, _ = cp._verifier(rang, cp._liste(parcours)[rang], cp.journal(journal))
    assert probleme == ""


def test_un_curl_jamais_lance_reste_refuse():
    """t39 : `curl http://localhost:8765/api/enigmes` n'a tourné qu'APRÈS cette clôture."""
    problemes = _manques("6bafe9cd5ee7", 195)
    assert len(problemes) == 1
    assert "curl http://localhost:8765/api/enigmes" in problemes[0]
    assert "JAMAIS" in problemes[0]


@pytest.mark.parametrize("indice, rang", [(187, 2), (200, 4), (309, 5)])
def test_modifier_tous_les_elements_ne_se_prouve_pas_par_un_regard(indice, rang):
    """t37, t40, t61 : « Modifier tous les éléments » prouvé par un instantané / un script qui
    lit le formulaire. Le formulaire d'édition n'a JAMAIS été joué dans la session (aucun
    fill, aucun script qui agit). À t61, le refus réel portait sur autre chose (le scraper
    `python3 scraper/kangourou.py …`, désormais reconnu) : seul ce vrai manque reste."""
    problemes = _manques("6bafe9cd5ee7", indice)
    assert len(problemes) == 1
    assert problemes[0].startswith(f"parcours_verifies[{rang}]")
    assert "AGIT" in problemes[0]
