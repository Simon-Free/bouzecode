# [desc] Rendu texte de la barre des agents du TUI : repliee sans sous-agent, une ligne par agent facon Claude Code (icone d'etat, type, description, conso, duree), petits-enfants indentes, selection et aide en mode liste. [/desc]
from __future__ import annotations

from types import SimpleNamespace

from bouzecode.backend.agent.state import AgentState
from bouzecode.backend.multi_agent.en_process.fiche import ERREUR, FINI, QUESTION, FicheAgent
from bouzecode.backend.multi_agent.en_process.registre import RegistreAgents
from bouzecode.ui.barre_agents import rendu
from bouzecode.ui.barre_agents.clavier import Navigation

T0 = 1_000_000.0


def _state(entree=0, sortie=0, cache=0):
    s = AgentState()
    s.total_input_tokens, s.total_output_tokens, s.total_cache_read_tokens = entree, sortie, cache
    return s


def _registre():
    registre = RegistreAgents()
    registre.declarer_principal(_state(), "claude-opus-5")
    return registre


def _fiche(id_, description, **champs):
    champs.setdefault("state", _state())
    champs.setdefault("profondeur", 1)
    return FicheAgent(id=id_, description=description, debut=T0, tache=SimpleNamespace(
        _cancel_flag=False), **champs)


def test_sans_sous_agent_la_barre_est_repliee():
    assert rendu.texte(_registre(), Navigation()) == ""


def test_une_ligne_par_agent_comme_claude_code():
    registre = _registre()
    registre.ajouter(_fiche("a", "Rundeck remote run + Playwright", modele="claude-opus-5",
                            state=_state(12_300, 1_200, 8_000)))
    texte = rendu.texte(registre, Navigation(), largeur=120, maintenant=T0 + 63)
    principal, enfant = texte.splitlines()
    assert principal == "  ● main"
    assert enfant.startswith("  ◯ ▶ general-purpose  Rundeck remote run + Playwright")
    assert "in 20.3k · fresh 12.3k · c-read 8.0k · out 1.2k ·" in enfant and enfant.endswith("$  1m 3s")
    assert "c-write" not in enfant  # nul : omis pour garder la ligne courte


def test_l_etat_se_lit_sans_couleur_et_les_petits_enfants_sont_indentes():
    registre = _registre()
    registre.ajouter(_fiche("a", "alpha", etat=QUESTION))
    registre.ajouter(_fiche("a1", "alpha.1", parent_id="a", profondeur=2, etat=FINI, fin=T0 + 5))
    registre.ajouter(_fiche("b", "beta", etat=ERREUR, fin=T0 + 2))
    lignes = rendu.texte(registre, Navigation(), maintenant=T0 + 99).splitlines()
    assert lignes[1].startswith("  ◯ ? general-purpose  alpha")
    assert lignes[2].strip() == "── historique (2) ──"
    assert lignes[3].startswith("    ◯ ✓ general-purpose  alpha.1") and lignes[3].endswith("5s")
    assert lignes[4].startswith("  ◯ ✗ general-purpose  beta")


def test_la_vue_courante_est_pleine_et_la_selection_marquee_avec_l_aide():
    registre = _registre()
    registre.ajouter(_fiche("a", "alpha"))
    registre.ajouter(_fiche("b", "beta"))
    nav = Navigation()
    nav.entrer_focus([f.id for f in registre.arbre()])
    nav.descendre([f.id for f in registre.arbre()])
    lignes = rendu.texte(registre, nav, maintenant=T0).splitlines()
    assert lignes[0] == "  ● main"
    assert lignes[2].startswith("❯ ◯ ▶ general-purpose  beta")
    assert lignes[-1].strip() == rendu.AIDE_FOCUS
    nav.valider([f.id for f in registre.arbre()])
    lignes = rendu.texte(registre, nav, maintenant=T0).splitlines()
    assert lignes[0] == "  ◯ main" and lignes[2].startswith("  ● ▶")
    assert lignes[-1].strip() == rendu.AIDE_VUE


def test_une_alerte_signaler_et_l_outil_en_cours_figurent_sur_la_ligne():
    registre = _registre()
    registre.ajouter(_fiche("a", "alpha", activite="Bash"))
    registre.signaler("a", "alerte", "proxy 407")
    ligne = rendu.texte(registre, Navigation(), largeur=140, maintenant=T0).splitlines()[1]
    assert "alpha [Bash]  ⚑ [alerte] proxy 407" in ligne


def test_une_ligne_trop_large_defile_tete_fixe_jusqu_a_montrer_la_fin_puis_revient():
    registre = _registre()
    registre.ajouter(_fiche("a", "x" * 300, state=_state(12_300, 1_200, 8_000), fin=T0))

    def a(instant):
        return rendu.texte(registre, Navigation(), largeur=80, maintenant=instant).splitlines()[1]

    tete = "  ◯ ▶ general-purpose  "
    cycle = [a(T0 + k / 4) for k in range(400)]   # 100 s echantillonnees toutes les 0.25 s
    assert all(len(x) <= 80 and x.startswith(tete) for x in cycle)
    assert "…" not in "".join(cycle)              # plus de troncature : la ligne defile
    debut = [x for x in cycle if x == tete + "x" * (80 - len(tete))]
    fin = [x for x in cycle if x.endswith("in 20.3k · fresh 12.3k · c-read 8.0k · out 1.2k · ? $  0s")]
    assert debut and fin and len(set(cycle)) > 10


def test_une_ligne_qui_tient_ne_bouge_pas():
    registre = _registre()
    registre.ajouter(_fiche("a", "alpha", state=_state(12_300, 1_200, 8_000), fin=T0 + 5))
    assert len({rendu.texte(registre, Navigation(), largeur=120, maintenant=T0 + k / 4)
                for k in range(40)}) == 1


def test_durees_et_tokens_compacts():
    assert [rendu.duree(s) for s in (5, 63, 3725)] == ["5s", "1m 3s", "1h 2m"]
    assert [rendu.compacter(n) for n in (950, 12_345, 2_500_000)] == ["950", "12.3k", "2.5M"]


def _compter_appel(state, usage_brut: dict) -> None:
    """Un appel LLM passe par la VRAIE chaine : normalisation du backend OpenAI-compatible
    (`_usage_tokens`), tour assistant, puis comptabilite de la boucle (`_account_llm_call`)."""
    from bouzecode.backend.agent.loop import _account_llm_call
    from bouzecode.backend.agent.loop_context import LoopContext
    from bouzecode.backend.agent.providers.backends.openrouter_stream import _usage_tokens
    from bouzecode.backend.agent.providers.types import AssistantTurn
    state.turn_count += 1
    ctx = LoopContext()
    ctx.assistant_turn = AssistantTurn("ok", [], *_usage_tokens(usage_brut))
    _account_llm_call(state, {"model": "claude-opus-5"}, ctx)


def test_la_conso_decompose_fresh_cache_lu_cache_ecrit_et_sortie_sur_toute_la_vie():
    state = AgentState()
    #  Tour 1, a froid (convention Anthropic : input_tokens EXCLUT le cache) : 900 frais,
    #  16 000 ecrits au cache. Tour 2, a chaud (convention OpenAI : prompt_tokens INCLUT le
    #  cache lu) : 18 000 au total dont 16 000 lus, 1 500 ecrits, donc 500 frais.
    _compter_appel(state, {"input_tokens": 900, "cache_creation_input_tokens": 16_000,
                           "cache_read_input_tokens": 0, "output_tokens": 700})
    _compter_appel(state, {"prompt_tokens": 18_000, "completion_tokens": 300,
                           "prompt_tokens_details": {"cached_tokens": 16_000},
                           "cache_creation_input_tokens": 1_500})
    fiche = _fiche("a", "alpha", modele="claude-opus-5", state=state)
    assert fiche.tokens() == {"entree": 900 + 16_000 + 500 + 1_500, "sortie": 1_000,
                              "cache_lu": 16_000, "cache_ecrit": 17_500}
    attendu = "in 34.9k · fresh 1.4k · c-read 16.0k · c-write 17.5k · out 1.0k · "
    assert attendu in rendu.conso(fiche)  # apres `cache now` (etat courant, teste plus bas)
    assert rendu.conso(fiche).endswith(f"{fiche.cout():.2f} $")


def test_sans_cache_la_ligne_ne_montre_que_in_fresh_et_out():
    fiche = _fiche("a", "alpha", state=_state(entree=2_000, sortie=150))
    assert rendu.conso(fiche) == "in 2.0k · fresh 2.0k · out 150 · ? $"


def _deux_appels():
    """Tour 1 a froid : 16 000 ecrits. Tour 2 a chaud : 16 000 relus + 1 500 ecrits."""
    state = AgentState()
    _compter_appel(state, {"input_tokens": 900, "cache_creation_input_tokens": 16_000,
                           "cache_read_input_tokens": 0, "output_tokens": 700})
    _compter_appel(state, {"prompt_tokens": 18_000, "completion_tokens": 300,
                           "prompt_tokens_details": {"cached_tokens": 16_000},
                           "cache_creation_input_tokens": 1_500})
    return _fiche("a", "alpha", modele="claude-opus-5", state=state)


def test_cache_now_vaut_cache_lu_plus_cache_ecrit_du_dernier_appel_seul():
    fiche = _deux_appels()
    maintenant = fiche.cache_courant().horodatage + 10
    #  17.5k = 16 000 lus + 1 500 ecrits au tour 2 ; PAS le cumul (16.0k lus + 17.5k ecrits).
    assert rendu.conso(fiche, maintenant).startswith("cache now 17.5k · in 34.9k · fresh 1.4k · c-read 16.0k")
    ligne = rendu.texte(_registre_avec(fiche), Navigation(), largeur=140,
                        maintenant=maintenant).splitlines()[1]
    assert "alpha" in ligne and "cache now 17.5k · in 34.9k · fresh" in ligne


def _registre_avec(fiche):
    registre = _registre()
    registre.ajouter(fiche)
    return registre


def test_cache_now_passe_le_ttl_est_signale_expire_sans_etre_cache():
    fiche = _deux_appels()
    une_heure_apres = fiche.cache_courant().horodatage + 3600
    assert rendu.conso(fiche, une_heure_apres).startswith("cache now 17.5k (expiré) · in 34.9k · fresh 1.4k")


def test_sans_appel_avec_cache_cache_now_est_omis():
    fiche = _fiche("a", "alpha", state=_state(entree=2_000, sortie=150))
    assert rendu.cache_now(fiche, T0) == "" and fiche.cache_courant() is None
