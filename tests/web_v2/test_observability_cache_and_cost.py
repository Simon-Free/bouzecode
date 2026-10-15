"""Points 1 et 2 du ticket 7fb5f816 : un taux de cache ne peut pas dépasser 100 %, et
l'input frais ne peut pas être facturé zéro.

Valeurs RÉELLES relevées en production (un tour d'agent) : api_input_tokens=12479,
api_cache_read=40180, api_cache_create=3682. Fonctions pures : aucun serveur, aucune
session, aucun mock.
"""
from __future__ import annotations

from bouzecode.backend.agent.providers.registry import calc_cost
from bouzecode.web_v2.services.sessions.analysis import _cache_hit_pct
from bouzecode.web_v2.services.sessions.costs import _cache_hit_pct as _costs_cache_hit_pct

# Le tour réel qui affichait 322 %.
REAL_INPUT = 12479
REAL_CACHE_READ = 40180
REAL_CACHE_CREATE = 3682


def test_cache_hit_pct_du_tour_reel_ne_depasse_pas_cent():
    """322 % affichés avant correction ; le prompt total est input + cache_read."""
    pct = _cache_hit_pct({"api_input_tokens": REAL_INPUT,
                          "api_cache_read": REAL_CACHE_READ})
    assert pct == round(100 * REAL_CACHE_READ / (REAL_INPUT + REAL_CACHE_READ))
    assert pct == 76
    assert 0 <= pct <= 100


def test_cache_hit_pct_jamais_impossible_sur_des_tours_tres_caches():
    """Les trois valeurs impossibles rapportées (322, 698, 1599 %) partagent la même cause."""
    cas = [(12479, 40180), (5000, 34900), (1200, 19188), (0, 0), (100, 0)]
    for inp, cr in cas:
        pct = _cache_hit_pct({"api_input_tokens": inp, "api_cache_read": cr})
        assert 0 <= pct <= 100, f"input={inp} cache_read={cr} -> {pct}%"


def test_cache_hit_pct_sans_cache_vaut_zero_et_tout_cache_vaut_cent():
    assert _cache_hit_pct({"api_input_tokens": 5000, "api_cache_read": 0}) == 0
    assert _cache_hit_pct({"api_input_tokens": 0, "api_cache_read": 4000}) == 100


def test_costs_cache_hit_pct_reste_coherent_avec_analysis():
    """Non-régression : `costs.py` était déjà juste, les deux vues doivent s'accorder."""
    assert _costs_cache_hit_pct(REAL_INPUT, REAL_CACHE_READ) == 76.3
    assert round(_costs_cache_hit_pct(REAL_INPUT, REAL_CACHE_READ)) == _cache_hit_pct(
        {"api_input_tokens": REAL_INPUT, "api_cache_read": REAL_CACHE_READ})


def test_calc_cost_facture_l_input_frais_du_tour_reel():
    """`in_tok` ne CONTIENT PAS `cache_read_tok` : le soustraire ramenait pure_input à 0."""
    out = 1000
    cout = calc_cost("claude-opus-5", REAL_INPUT, out,
                     cache_read_tok=REAL_CACHE_READ, cache_create_tok=REAL_CACHE_CREATE)
    ic, oc = 4.7, 23.33
    pure_input = REAL_INPUT - REAL_CACHE_CREATE  # 8797
    attendu = (pure_input * ic
               + REAL_CACHE_READ * ic * 0.1
               + REAL_CACHE_CREATE * ic * 1.25
               + out * oc) / 1_000_000
    assert cout == attendu


def test_calc_cost_croit_avec_l_input_frais():
    """Preuve indépendante de la table de prix : plus d'input frais => plus cher."""
    petit = calc_cost("claude-opus-5", 4000, 0,
                      cache_read_tok=REAL_CACHE_READ, cache_create_tok=REAL_CACHE_CREATE)
    grand = calc_cost("claude-opus-5", REAL_INPUT, 0,
                      cache_read_tok=REAL_CACHE_READ, cache_create_tok=REAL_CACHE_CREATE)
    assert grand > petit


def test_calc_cost_ne_facture_pas_l_ecriture_de_cache_deux_fois():
    """`cache_create_tok` est comprise dans `in_tok` et tarifée à part : une seule fois."""
    ic = 4.7
    seul_le_cache_create = calc_cost("claude-opus-5", REAL_CACHE_CREATE, 0,
                                     cache_read_tok=0,
                                     cache_create_tok=REAL_CACHE_CREATE)
    assert seul_le_cache_create == REAL_CACHE_CREATE * ic * 1.25 / 1_000_000


def test_un_modele_absent_de_la_table_se_voit():
    """Sans entrée dans COSTS, le coût est 0 : cela DOIT être signalable, pas silencieux."""
    from bouzecode.backend.agent.providers.registry import is_priced
    assert is_priced("claude-opus-5") is True
    # `glm-5.2` a un tarif EXPLICITE à (0.0, 0.0) en attendant confirmation : à l'écran
    # c'est le même mensonge qu'un modèle absent, donc il compte comme non tarifé.
    assert is_priced("glm-5.2") is False
    assert is_priced("modele-jamais-vu-9000") is False
    assert calc_cost("modele-jamais-vu-9000", 10_000, 10_000) == 0.0
