# [desc] Mode d'ATTENTE de l'outil Agent (le mode PAR DÉFAUT) : le manager sonde la VRAIE
# route ticket, s'arrête quand l'enfant a rendu la main, et — si l'attente casse — apprend
# que son TICKET EXISTE au lieu de croire son dispatch raté et d'en créer un DOUBLON. [/desc]
"""Zéro réseau, zéro mock : `get_json` / `sleep` / `now` sont les seams du module."""
from __future__ import annotations

from flask import Flask

from bouzecode.backend.multi_agent import tools


def _poller(pages):
    """Getter HTTP factice : sert `pages` l'une après l'autre et note les URL sondées."""
    urls: list[str] = []

    def get_json(url):
        urls.append(url)
        return pages[min(len(urls) - 1, len(pages) - 1)]

    get_json.urls = urls
    return get_json


def _fake_clock():
    """Horloge injectable : `sleep` avance le temps, la boucle finit donc en déterministe."""
    elapsed = {"s": 0.0}
    return (lambda: elapsed["s"]), (lambda seconds: elapsed.__setitem__("s", elapsed["s"] + seconds))


CRASHED_CHILD = {"id": "t1", "crashed": True,
                 "runs": [{"agent_id": "agent-inexistant-pour-le-test", "kind": "work"}]}
MERGED_CHILD = {
    "id": "t1", "worktree": {"state": "integrated"},
    "runs": [
        {"agent_id": "agent-inexistant-pour-le-test", "kind": "work"},
        {"agent_id": "autre-agent-inexistant", "kind": "validate",
         "verdict": "VERDICT: OK — tests verts"},
    ],
}
STILL_LAUNCHING = {"id": "t1", "launching": True, "runs": []}


# ---- L'URL sondée est une route qui EXISTE ---------------------------------

def test_the_polled_url_is_the_real_ticket_route():
    """L'attente sonde /api/tickets/<slug>/<id> — la route inexistante /api/ticket/<id>
    répondait 404 et transformait tout dispatch réussi en échec."""
    now, sleep = _fake_clock()
    get_json = _poller([CRASHED_CHILD])

    tools._default_web_wait_verdict("t1", "mon-projet",
                                    get_json=get_json, sleep=sleep, now=now)

    assert get_json.urls == ["http://127.0.0.1:5056/api/tickets/mon-projet/t1"]


def test_that_url_resolves_to_the_ticket_detail_endpoint():
    """Non-régression du bug du jour : l'URL sondée matche bien une route enregistrée."""
    from bouzecode.web_v2.routes.work.tickets import tickets_bp
    app = Flask(__name__)
    app.register_blueprint(tickets_bp)

    path = tools._TICKET_DETAIL_URL.format(slug="mon-projet", ticket_id="t1")
    endpoint, args = app.url_map.bind("127.0.0.1").match(path.split("5056", 1)[1])

    assert endpoint == "tickets_api.api_ticket_detail"
    assert args == {"slug": "mon-projet", "ticket_id": "t1"}


# ---- Fin d'attente et lecture du verdict -----------------------------------

def test_a_child_that_gave_the_hand_back_ends_the_wait():
    """Un enfant planté n'a plus rien à jouer : l'attente s'arrête et l'issue est rendue."""
    now, sleep = _fake_clock()
    get_json = _poller([CRASHED_CHILD])

    report = tools._default_web_wait_verdict("t1", "p", get_json=get_json, sleep=sleep, now=now)

    assert len(get_json.urls) == 1
    assert "CRASHED" in report


def test_the_verdict_is_read_on_the_runs_not_on_the_ticket():
    """Le verdict vit sur ticket["runs"][*]["verdict"] — le ticket n'a jamais eu ce champ."""
    now, sleep = _fake_clock()
    get_json = _poller([MERGED_CHILD])

    report = tools._default_web_wait_verdict("t1", "p", get_json=get_json, sleep=sleep, now=now)

    assert "VERDICT: OK — tests verts" in report


def test_a_child_still_working_does_not_stop_the_loop():
    """Tant que l'enfant tourne, on continue de sonder — jusqu'au délai maximum."""
    now, sleep = _fake_clock()
    get_json = _poller([STILL_LAUNCHING])

    report = tools._default_web_wait_verdict("t1", "p", get_json=get_json, sleep=sleep,
                                             now=now, timeout=60)

    assert len(get_json.urls) > 1
    assert "EXISTE" in report and "ne le redispatche pas" in report


def test_the_loop_stops_as_soon_as_the_child_gives_the_hand_back():
    """Deux tours d'attente puis l'enfant rend la main : la boucle s'arrête là."""
    now, sleep = _fake_clock()
    get_json = _poller([STILL_LAUNCHING, STILL_LAUNCHING, CRASHED_CHILD])

    report = tools._default_web_wait_verdict("t1", "p", get_json=get_json, sleep=sleep, now=now)

    assert len(get_json.urls) == 3
    assert "CRASHED" in report
