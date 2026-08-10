# [desc] Tests du verdict env API web_v2 : env absente vs base_url injoignable, retries, re-sonde à chaud, gardes 503 des spawns. [/desc]
"""Deux bugs verrouillés ici.

13:44 : serveur relancé hors bouzeui.ps1 -> os.environ sans ANTHROPIC_BASE_URL/clef ->
tous les agents meurent en silence. Le verdict doit etre KO et les spawns refuses.

27/07 : un hoquet reseau au boot a fige un KO MENSONGER pour toute la vie du process
(la passerelle repondait en 0,39 s), bandeau rouge + 503 sur tous les spawns, sans autre
remede qu'un redemarrage inutile. Le verdict doit donc retenter, puis se re-sonder.

Aucun mock.patch : capture_api_sanity(env=, ping=, sleep=) prend l'env, la sonde reseau
et le backoff par injection de dependance.
"""
from bouzecode.web_v2 import api_sanity

ENV_OK = {"ANTHROPIC_BASE_URL": "https://gateway.example.com", "ANTHROPIC_API_KEY": "k"}


def _no_sleep(_seconds):
    """Neutralise le backoff : les tests ne doivent pas attendre le reseau."""


def _ping_failing_n_times(failures):
    """Sonde qui echoue `failures` fois puis repond, comme un DNS froid qui se reveille."""
    state = {"calls": 0}

    def ping(_url):
        state["calls"] += 1
        return state["calls"] > failures

    ping.state = state
    return ping


def _capture(env, ping):
    api_sanity.reset_api_sanity()
    api_sanity.capture_api_sanity(env=env, ping=ping, sleep=_no_sleep)


def test_env_absente_donne_un_ko_qui_dit_de_relancer():
    _capture({}, lambda url: True)

    state = api_sanity.api_sanity_state()

    assert state["ok"] is False
    assert state["env_missing"] is True
    assert state["base_url_present"] is False
    assert "variables d'environnement API absentes" in state["detail"]
    assert "ANTHROPIC_BASE_URL" in state["detail"]
    assert "bouzeui.ps1" in state["detail"]


def test_base_url_injoignable_donne_un_ko_distinct_de_lenv_absente():
    """Vars presentes mais base_url injoignable : le message parle reseau, pas env."""
    _capture(ENV_OK, lambda url: False)

    state = api_sanity.api_sanity_state()

    assert state["ok"] is False
    assert state["env_missing"] is False
    assert state["base_url_present"] is True and state["key_present"] is True
    assert "injoignable" in state["detail"]
    assert "tentative" in state["detail"]
    assert "variables d'environnement" not in state["detail"]


def test_une_sonde_qui_echoue_puis_repond_donne_un_verdict_ok():
    """LE bug du 27/07 : deux echecs a froid ne doivent plus condamner le serveur."""
    ping = _ping_failing_n_times(2)

    _capture(ENV_OK, ping)

    assert api_sanity.api_sanity_state()["ok"] is True
    assert ping.state["calls"] == 3


def test_une_sonde_qui_leve_toujours_ne_casse_pas_le_boot():
    def _boom(_url):
        raise RuntimeError("proxy down")

    _capture(ENV_OK, _boom)

    state = api_sanity.api_sanity_state()
    assert state["ok"] is False
    assert "injoignable" in state["detail"]


def test_env_ok_et_joignable_donne_un_verdict_ok():
    _capture(ENV_OK, lambda url: True)

    assert api_sanity.api_sanity_state()["ok"] is True


def _app():
    from bouzecode.web_v2.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    return app


def _client():
    return _app().test_client()


def test_endpoint_env_sanity_reflete_le_verdict():
    _capture({}, lambda url: True)

    resp = _client().get("/api/env-sanity")

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is False


def test_le_bouton_reverifier_repare_un_ko_transitoire_sans_redemarrage():
    """POST /api/env-sanity/recheck : le reseau est revenu, le verdict repasse OK."""
    network = {"up": False}
    _capture(ENV_OK, lambda url: network["up"])
    client = _client()
    assert client.get("/api/env-sanity").get_json()["ok"] is False

    network["up"] = True
    resp = client.post("/api/env-sanity/recheck")

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    # Et l'etat servi ensuite reste OK : aucun redemarrage n'a eu lieu.
    assert client.get("/api/env-sanity").get_json()["ok"] is True


def test_le_verdict_ko_se_re_sonde_tout_seul_quand_le_cooldown_est_passe():
    """Sans clic ni redemarrage : un KO vieux est re-teste a la prochaine lecture."""
    network = {"up": False}
    _capture(ENV_OK, lambda url: network["up"])
    assert api_sanity.api_sanity_state()["ok"] is False

    network["up"] = True
    api_sanity.LAST_CHECK_AT = 0.0  # le cooldown est ecoule

    assert api_sanity.api_sanity_state()["ok"] is True


def test_un_verdict_ok_ne_declenche_aucune_sonde_supplementaire():
    ping = _ping_failing_n_times(0)
    _capture(ENV_OK, ping)
    calls_apres_boot = ping.state["calls"]

    api_sanity.LAST_CHECK_AT = 0.0
    api_sanity.api_sanity_state()
    api_sanity.require_api_sanity()

    assert ping.state["calls"] == calls_apres_boot


def test_require_api_sanity_refuse_le_spawn_en_503_et_le_laisse_passer_sinon():
    """Le garde lui-meme : (reponse, 503) quand KO, None quand OK."""
    _capture({}, lambda url: True)
    app = _app()

    with app.app_context():
        response, status = api_sanity.require_api_sanity()
        assert status == 503
        assert "bouzeui.ps1" in response.get_json()["error"]

        _capture(ENV_OK, lambda url: True)
        assert api_sanity.require_api_sanity() is None


def test_le_503_dun_reseau_injoignable_propose_reverifier_pas_un_redemarrage():
    _capture(ENV_OK, lambda url: False)

    with _app().app_context():
        response, status = api_sanity.require_api_sanity()

    assert status == 503
    assert "Revérifier" in response.get_json()["error"]


def test_un_spawn_repasse_des_que_le_reseau_revient_sans_redemarrage():
    """Le 503 des spawns disparait tout seul quand le reseau revient, serveur inchange."""
    network = {"up": False}
    _capture(ENV_OK, lambda url: network["up"])
    client = _client()
    assert client.post("/api/dispatch", json={"prompt": "fais un truc"}).status_code == 503

    network["up"] = True
    api_sanity.LAST_CHECK_AT = 0.0  # le cooldown est ecoule

    # prompt vide -> 400 : on a franchi le garde sans lancer d'agent.
    assert client.post("/api/dispatch", json={"prompt": ""}).status_code != 503


def test_dispatch_repond_503_quand_lenv_est_ko():
    _capture({}, lambda url: True)

    resp = _client().post("/api/dispatch", json={"prompt": "fais un truc"})

    assert resp.status_code == 503
    assert "bouzeui.ps1" in resp.get_json()["error"]


def test_agent_launch_repond_503_quand_lenv_est_ko():
    _capture({}, lambda url: True)

    resp = _client().post("/api/agents/launch", json={"prompt": "fais un truc"})

    assert resp.status_code == 503
    assert "bouzeui.ps1" in resp.get_json()["error"]


def test_dispatch_nest_pas_bloque_quand_le_verdict_est_ok():
    """Verdict OK -> le garde 503 ne se declenche pas (prompt vide -> 400, pas 503)."""
    _capture(ENV_OK, lambda url: True)

    resp = _client().post("/api/dispatch", json={"prompt": ""})

    assert resp.status_code != 503
