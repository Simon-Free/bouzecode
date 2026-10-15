# [desc] Politique du pool chaud : dates réelles en UTC, activité inconnue = on n'évince pas, travail en cours immunisé, règle motivée. [/desc]
"""Décision d'éviction, logique pure (aucun process) : les quatre défauts du 2026-09-29.

* `max()` sur des CHAÎNES : `"2026-09-29T08:12:34Z"` (spawn, UTC) battait
  `"2026-09-29 10:58:52"` (sauvegarde de session, heure locale) parce que 'T' > ' ' : une
  conversation lancée depuis plus de 15 min était évincée ~15 s après CHAQUE tour.
* une date absente valait « infiniment vieux » (epoch) : première victime du TTL et du LRU.
* un agent qui avait encore du travail (ticket ouvert, tour clos sur un refus) était tué.
* aucune trace de la règle qui avait joué.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from bouzecode.web_v2.runtime import warmpool

MAINTENANT = datetime.now(timezone.utc).replace(microsecond=0)


def _noeud(agent_id, activite, *, parent="dispatcher:manual", travail=False, state="idle"):
    return {"agent_id": agent_id, "parent": parent, "state": state, "warm": True,
            "last_activity": activite, "travail_en_cours": travail}


def _il_y_a(minutes: float) -> datetime:
    return MAINTENANT - timedelta(minutes=minutes)


def test_la_sauvegarde_locale_recente_l_emporte_sur_un_spawn_utc_ancien():
    """Reproduction de c4e9964adb48 : spawn il y a 47 min (UTC, 'Z'), dernier tour sauvegardé
    il y a 30 s (heure LOCALE naïve, séparateur espace)."""
    #  Instant FIXE : le piège n'existe que si les dates locale et UTC coïncident (entre minuit
    #  local et minuit UTC, « maintenant » faisait échouer la précondition, pas le code).
    maintenant = datetime(2026, 9, 29, 10, 59, 22, tzinfo=timezone.utc)
    spawn = (maintenant - timedelta(minutes=47)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    sauvegarde = (maintenant.astimezone() - timedelta(seconds=30)).strftime("%Y-%m-%d %H:%M:%S")
    assert max(spawn, sauvegarde) == spawn, "le piège : la comparaison de chaînes prend le spawn"

    derniere = warmpool.latest_instant([spawn, "", sauvegarde])
    assert 29 <= (maintenant - derniere).total_seconds() <= 32
    assert warmpool.decide_evictions([_noeud("conversation", derniere.isoformat())],
                                     maintenant, max_pool=8) == []


def test_parse_instant_normalise_tout_en_utc():
    local = datetime(2026, 9, 29, 10, 58, 52)
    assert warmpool.parse_instant("2026-09-29 10:58:52") == local.astimezone(timezone.utc)
    assert warmpool.parse_instant("2026-09-29T08:12:34Z") == datetime(
        2026, 9, 29, 8, 12, 34, tzinfo=timezone.utc)
    assert warmpool.parse_instant(0) is None
    assert warmpool.parse_instant(1790672332.0).tzinfo == timezone.utc
    for illisible in ("", None, "hier", "2026-13-45"):
        assert warmpool.parse_instant(illisible) is None


def test_activite_inconnue_n_est_jamais_evincee():
    """Ni par le TTL, ni par le LRU, même pool plein (max 0)."""
    noeuds = [_noeud("sans-date", ""), _noeud("illisible", "pas une date")]
    assert warmpool.decide_evictions(noeuds, MAINTENANT, max_pool=0) == []


def test_le_lru_prend_le_plus_ancien_connu():
    noeuds = [_noeud("recent", _il_y_a(1).isoformat()), _noeud("ancien", _il_y_a(5).isoformat()),
              _noeud("inconnu", "")]
    motifs = warmpool.decide_evictions_motivees(noeuds, MAINTENANT, max_pool=2)
    assert list(motifs) == ["ancien"]
    assert motifs["ancien"]["regle"] == warmpool.REGLE_LRU
    assert motifs["ancien"]["pool"] == 3 and motifs["ancien"]["max_pool"] == 2


def test_un_agent_qui_a_encore_du_travail_n_est_jamais_evince():
    """Même vieux de 2 h, même sous-agent inactif, même pool plein."""
    noeuds = [_noeud("racine-refus", _il_y_a(120).isoformat(), travail=True),
              _noeud("enfant-refus", _il_y_a(1).isoformat(), parent="manager0001", travail=True)]
    assert warmpool.decide_evictions(noeuds, MAINTENANT, max_pool=0) == []


def test_le_motif_dit_la_regle_et_les_dates_comparees():
    vieux = _noeud("racine", _il_y_a(20).isoformat())
    enfant = _noeud("enfant", _il_y_a(1).isoformat(), parent="manager0001")
    motifs = warmpool.decide_evictions_motivees([vieux, enfant], MAINTENANT, max_pool=8)
    assert motifs["racine"]["regle"] == warmpool.REGLE_TTL
    assert motifs["racine"]["age_s"] == 1200.0 and motifs["racine"]["ttl_s"] == 900
    assert motifs["racine"]["derniere_activite"] == _il_y_a(20).isoformat()
    assert motifs["enfant"]["regle"] == warmpool.REGLE_SOUS_AGENT
