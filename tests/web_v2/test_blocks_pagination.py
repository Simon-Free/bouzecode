"""`GET /api/sessions/<key>/blocks` : page de fin (`tail`), pages plus anciennes (`before`),
HTML rendu une fois par message, et 304 sans décoder la session tant que rien n'a bougé.

Session « daily » réelle sur disque (DAILY_DIR redirigé), vrai endpoint via le test client."""
import json
import os

import pytest

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.services import message_view
from bouzecode.web_v2.services.sessions import blocs_rendus, store

N = 10


def _messages(n=N):
    out = []
    for i in range(n):
        out.append({"role": "user", "content": f"question {i}"} if i % 2 == 0
                   else {"role": "assistant", "content": f"réponse **{i}**"})
    return out


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "DAILY_DIR", tmp_path)
    blocs_rendus.oublier()
    day = tmp_path / "2026-07-06"
    day.mkdir()
    chemin = day / "session_blocs.json"
    chemin.write_text(json.dumps({"messages": _messages()}), encoding="utf-8")
    yield {"client": create_app().test_client(), "chemin": chemin,
           "url": "/api/sessions/daily/2026-07-06/session_blocs.json/blocks"}
    blocs_rendus.oublier()


def _idx(body):
    return [b["idx"] for b in body["blocks"]]


def _reecrire(chemin, messages):
    chemin.write_text(json.dumps({"messages": messages}), encoding="utf-8")
    st = chemin.stat()
    os.utime(chemin, ns=(st.st_atime_ns, st.st_mtime_ns + 5 * 10**9))


def test_sans_tail_reponse_complete_inchangee(env):
    body = env["client"].get(f"{env['url']}?after=0").get_json()
    assert body["total"] == N and _idx(body) == list(range(N)) and body["debut"] == 0
    assert _idx(env["client"].get(f"{env['url']}?after=7").get_json()) == [7, 8, 9]


def test_tail_puis_pages_precedentes_identiques_au_rendu_complet(env):
    client, url = env["client"], env["url"]
    complet = {b["idx"]: b["html"] for b in client.get(f"{url}?after=0").get_json()["blocks"]}
    fin = client.get(f"{url}?after=0&tail=3").get_json()
    assert fin["total"] == N and fin["debut"] == 7 and _idx(fin) == [7, 8, 9]
    avant = client.get(f"{url}?after=4&before=7").get_json()
    assert avant["debut"] == 4 and _idx(avant) == [4, 5, 6]
    for page in (fin, avant):
        assert all(b["html"] == complet[b["idx"]] for b in page["blocks"])
    # Le polling incrémental reprend après la fin, comme avant.
    assert _idx(client.get(f"{url}?after={fin['total']}").get_json()) == []


def test_etag_304_sans_decoder_la_session(env, monkeypatch):
    client, url = env["client"], env["url"]
    premiere = client.get(f"{url}?after=10")
    etag = premiere.headers["ETag"]
    lectures = []
    vraie = store.load_session_json
    monkeypatch.setattr(store, "load_session_json", lambda p: lectures.append(p) or vraie(p))
    revalidee = client.get(f"{url}?after=10", headers={"If-None-Match": etag})
    assert revalidee.status_code == 304 and lectures == []
    # Représentation compressée (ETag faible) : même verdict.
    assert client.get(f"{url}?after=10", headers={"If-None-Match": f"W/{etag}"}).status_code == 304
    _reecrire(env["chemin"], _messages(N + 1))
    apres = client.get(f"{url}?after=10", headers={"If-None-Match": etag})
    assert apres.status_code == 200 and _idx(apres.get_json()) == [10]
    assert apres.headers["ETag"] != etag


def test_message_rendu_une_fois_par_contenu(env, monkeypatch):
    client, url = env["client"], env["url"]
    rendus = []
    vrai = message_view.render_message
    monkeypatch.setattr(message_view, "render_message",
                        lambda m, context_url=None: rendus.append(m) or vrai(m, context_url=context_url))
    premier = client.get(f"{url}?after=0").get_json()
    assert client.get(f"{url}?after=0").get_json()["blocks"] == premier["blocks"]
    assert len(rendus) == N
    messages = _messages()
    messages[-1] = {"role": "assistant", "content": "réponse réécrite"}
    _reecrire(env["chemin"], messages)
    body = client.get(f"{url}?after=0").get_json()
    assert len(rendus) == N + 1
    assert "réponse réécrite" in body["blocks"][-1]["html"]


def test_memoire_du_rendu_bornee_en_octets(monkeypatch):
    """Au-delà du budget, les sessions les plus anciennes sortent ; celle qu'on sert reste."""
    monkeypatch.setattr(blocs_rendus, "_BUDGET_OCTETS", 3000)
    blocs_rendus.oublier()
    gros = {"role": "user", "content": "x" * 1200}
    for chemin in ("a", "b", "c"):
        blocs_rendus.rendre(chemin, 0, gros, None)
    assert list(blocs_rendus._memo) == ["b", "c"]
    blocs_rendus._BUDGET_OCTETS = 10
    blocs_rendus.rendre("d", 0, gros, None)
    assert list(blocs_rendus._memo) == ["d"]
    blocs_rendus.oublier()
