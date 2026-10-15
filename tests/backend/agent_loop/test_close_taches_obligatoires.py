"""La clôture DÉCLARE ce qui est fait et ce qui reste — sinon elle est refusée.

Ces tests exercent le chemin RÉEL : le validateur de clôture importé pour de vrai
et le handler du tool `FinalAnswer` tel que le registre l'appelle. Aucun mock, et
aucun appel réseau : tous les cas de refus rendent la main AVANT la porte LLM, et
le cas « listes vides = valide » se prouve sur la fonction déterministe pure.
"""

from bouzecode.backend.agent.close_validator import (
    missing_taches_fields,
    validate_close,
)
from bouzecode.backend.tools.registration import _final_answer


def _config() -> dict:
    """Profil de livraison minimal : récap exigé, session de premier niveau."""
    return {"require_recap": True, "recap_coding": False, "_depth": 0, "model": ""}


RECAP_OK = {"symptoms": "le bouton ne répond pas", "explanation": "l'écouteur manquait"}


def test_cloture_refusee_quand_les_deux_champs_sont_omis():
    accepted, feedback = validate_close("réponse complète", _config(), RECAP_OK)
    assert accepted is False
    assert "taches_terminees" in feedback
    assert "taches_restantes" in feedback
    #  Le message doit DIRE quoi fournir, pas seulement constater le manque.
    assert "[]" in feedback


def test_cloture_refusee_quand_un_seul_champ_est_fourni():
    accepted, feedback = validate_close(
        "réponse complète", _config(), RECAP_OK, taches_terminees=["j'ai corrigé le bouton"]
    )
    assert accepted is False
    assert "taches_restantes" in feedback
    assert "taches_terminees" not in feedback


def test_listes_vides_explicites_sont_valides():
    #  « rien ne reste » est une réponse VALIDE — mais elle doit être donnée.
    assert missing_taches_fields([], []) == []


def test_omission_distinguee_de_la_liste_vide():
    assert missing_taches_fields(None, None) == ["taches_terminees", "taches_restantes"]


def test_tache_restante_sans_rattachement_est_acceptee():
    #  Le rattachement est optionnel : l'agent ne connaît pas les ids de chantier, et un
    #  point sans chantier hérite de celui de la tâche qui l'a lancé (cloture_micros).
    #  L'exiger refusait en boucle des clôtures valides (DeepSeek, 2026-09-24).
    assert missing_taches_fields(["fait"], [{"titre": "reste à câbler l'onglet"}]) == []


def test_tache_restante_sans_titre_est_refusee():
    #  §10.3 : l'item porte `titre` (+ `corps` optionnel), plus un `texte` unique.
    issues = missing_taches_fields([], [{"macro_titre": "TO-DO list"}])
    assert issues == ["taches_restantes[0].titre"]


def test_declaration_complete_passe_la_porte_deterministe():
    restantes = [{"macro_titre": "TO-DO list", "titre": "brancher le bouton « abandonner »"}]
    assert missing_taches_fields(["schéma FinalAnswer étendu"], restantes) == []


def test_handler_reel_du_tool_refuse_la_cloture_non_declaree():
    config = _config()
    out = _final_answer("réponse complète", config, RECAP_OK)
    assert "CLÔTURE REFUSÉE" in out
    assert "taches_restantes" in out
    assert config["_final_answer_refused"] is True


def test_handler_reel_tolere_des_listes_serialisees_en_chaine_json():
    #  Certains modèles sérialisent les tableaux en chaîne JSON (cf. _coerce_recap) :
    #  ça ne doit PAS se transformer en refus en boucle.
    config = _config()
    out = _final_answer(
        "réponse complète",
        config,
        RECAP_OK,
        taches_terminees="[]",
        taches_restantes='[{"macro_titre": "TO-DO list", "titre": "brancher la page"}]',
    )
    assert "CLÔTURE REFUSÉE" not in out
    assert config.get("_final_answer_refused") is not True


#  --- Profil assistant de bureau : require_taches=False -------------------------


def _assistant_config() -> dict:
    """Profil bureau-assistant : pas de récap, déclarations de tâches facultatives."""
    return {"require_recap": False, "require_taches": False, "_depth": 0, "model": ""}


def test_assistant_cloture_acceptee_sans_declarations_de_taches():
    config = _assistant_config()
    out = _final_answer("C'est noté dans la TODO.", config, None)
    assert "CLÔTURE REFUSÉE" not in out
    assert config.get("_final_answer_refused") is not True
    assert validate_close("ok", _assistant_config()) == (True, "")


def test_profil_de_code_toujours_refuse_sans_declarations():
    config = {"require_recap": True, "recap_coding": True, "require_taches": True,
              "_depth": 0, "model": ""}
    ok, feedback = validate_close("réponse", config, RECAP_OK)
    assert ok is False
    assert "taches_restantes" in feedback and "taches_terminees" in feedback
    #  Sans la clé (profil par défaut), l'obligation reste aussi.
    ok, feedback = validate_close("réponse", _config(), RECAP_OK)
    assert ok is False and "taches_restantes" in feedback


def test_assistant_declarations_fournies_restent_validees_et_prises_en_compte():
    config = _assistant_config()
    #  Fournies mais mal formées (tâche sans titre) : toujours contrôlées.
    ok, feedback = validate_close(
        "ok", config, None, taches_terminees=[], taches_restantes=[{"corps": "x"}]
    )
    assert ok is False and "titre" in feedback
    #  Fournies et valides : acceptées.
    config = _assistant_config()
    out = _final_answer(
        "ok", config, None,
        taches_terminees=["chantier créé"],
        taches_restantes=[{"titre": "relancer le client"}],
    )
    assert "CLÔTURE REFUSÉE" not in out


def test_schema_final_answer_ne_rend_plus_les_taches_required():
    from bouzecode.backend.tools.schemas import TOOL_SCHEMAS
    schema = next(s for s in TOOL_SCHEMAS if s.get("name") == "FinalAnswer")
    params = schema.get("input_schema") or schema.get("parameters")
    assert "taches_restantes" not in params.get("required", [])
    for champ in ("taches_restantes", "taches_terminees"):
        assert champ not in params.get("required", [])
        assert "sauf pour le profil assistant" in params["properties"][champ]["description"]


def test_profil_bureau_assistant_declare_require_taches_false():
    from pathlib import Path

    import bouzecode.backend.profiles as profiles_pkg
    from bouzecode.backend.profiles.loader import load_profile_from_path

    path = Path(profiles_pkg.__file__).parent / "builtin" / "bureau-assistant.yaml"
    assert load_profile_from_path(path).require_taches is False
    #  Un profil sans la clé garde l'obligation (défaut True).
    autres = [p for p in path.parent.glob("*.yaml") if p.name != "bureau-assistant.yaml"]
    assert autres and all(load_profile_from_path(p).require_taches for p in autres
                          if "require_taches" not in p.read_text(encoding="utf-8"))
