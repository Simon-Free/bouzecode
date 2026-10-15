# [desc] Le garde-fou de santé API teste le fournisseur du modèle configuré, pas seulement Anthropic. [/desc]
"""Bug du 2026-09-23 : un serveur configuré sur DeepSeek (OpenRouter) sans variables
Anthropic affichait « ENV API KO » et refusait en 503 TOUT lancement d'agent, alors que ses
agents n'auraient jamais parlé à Anthropic. Le verdict suit désormais le fournisseur du modèle
configuré. Injection (pas de mock.patch) : env, sonde réseau et modèle sont passés au capture.
"""
from bouzecode.web_v2 import api_sanity

DEEPSEEK = "deepseek-v4.1-flash"


def _no_sleep(_seconds):
    pass


def _client():
    from bouzecode.web_v2.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _capture(env, ping, model=DEEPSEEK):
    api_sanity.reset_api_sanity()
    api_sanity.capture_api_sanity(env=env, ping=ping, sleep=_no_sleep, model=model)


def test_un_serveur_deepseek_sans_variables_anthropic_peut_lancer_des_agents():
    sondes = []
    _capture({"OPENROUTER_KEY": "sk-or-test"}, lambda url: sondes.append(url) or True)

    etat = _client().get("/api/env-sanity").get_json()

    assert etat["ok"] is True
    assert etat["provider_label"] == "OpenRouter"
    assert sondes and sondes[0].startswith("https://openrouter.ai/"), "c'est OpenRouter qu'on sonde"
    assert api_sanity.require_api_sanity() is None


def test_une_cle_openrouter_absente_est_dite_clairement():
    _capture({"ANTHROPIC_BASE_URL": "http://gateway", "ANTHROPIC_API_KEY": "k"}, lambda url: True)

    etat = _client().get("/api/env-sanity").get_json()

    assert etat["ok"] is False and etat["env_missing"] is True
    assert "OpenRouter" in etat["detail"] and "OPENROUTER_KEY" in etat["detail"]
    assert "ANTHROPIC" not in etat["detail"], "on ne réclame pas une clé que ce modèle n'utilise pas"
    refus = _client().post("/api/agents", json={"prompt": "fais un truc"})
    assert refus.status_code == 503
    assert "OpenRouter" in refus.get_json()["error"]["message"]


def test_openrouter_injoignable_parle_reseau_pas_configuration():
    _capture({"OPENROUTER_KEY": "sk-or-test"}, lambda url: False)

    etat = api_sanity.api_sanity_state()

    assert etat["ok"] is False and etat["env_missing"] is False
    assert "injoignable" in etat["detail"]


def test_un_modele_claude_garde_le_contrat_anthropic():
    _capture({"OPENROUTER_KEY": "sk-or-test"}, lambda url: True, model="claude-opus-5")

    etat = api_sanity.api_sanity_state()

    assert etat["ok"] is False
    assert "ANTHROPIC_BASE_URL" in etat["detail"]
