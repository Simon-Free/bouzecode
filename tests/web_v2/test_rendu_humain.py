"""Rendu HUMAIN d'une tâche : mêmes exigences que la clôture FinalAnswer d'un agent.

POST /api/micros/<id>/rendu valide avec `close_validator` (6 sections, recap, tâches) et
vérifie les commits avec git ; un rendu accepté fait passer la tâche « À vérifier »
(statut `a_relire`) avec le même récap qu'un agent."""
import subprocess

import pytest

from tests.web_v2.test_payload_leger import ctx  # noqa: F401 — fixture réutilisée

ANSWER = "\n".join(f"## {i}. Section {i}\ntexte" for i in range(1, 7))


def _git(depot, *args):
    return subprocess.run(["git", "-C", str(depot), *args], capture_output=True,
                          text=True, check=True).stdout.strip()


@pytest.fixture
def depot(tmp_path, monkeypatch):
    """Un dépôt git local avec un commit sur `main`, branché comme dépôt de la tâche."""
    d = tmp_path / "depot"
    d.mkdir()
    _git(d, "init", "-q", "-b", "main")
    _git(d, "config", "user.email", "t@t")
    _git(d, "config", "user.name", "t")
    (d / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(d, "add", "a.py")
    _git(d, "commit", "-q", "-m", "init")
    from bouzecode.web_v2.services.work import rendu_humain, taches_actions
    monkeypatch.setattr(taches_actions, "resoudre_depot", lambda micro, demande: "demo")
    monkeypatch.setattr(rendu_humain, "_chemin_depot", lambda slug: str(d))
    return _git(d, "rev-parse", "HEAD")


def _manquants(reponse):
    return ((reponse.get_json() or {}).get("error") or {}).get("details", {}).get("manquants") or []


def _rendu(sha, **surcharge):
    corps = {
        "answer": ANSWER,
        "recap": {"symptoms": "le bouton ne marche pas", "explanation": "handler absent",
                  "changes": [{"file": "a.py", "summary": "ajoute x"}]},
        "tests_detail": {"nombre": 2, "niveau": "unitaire", "verts": True,
                         "chemin": "tests/test_a.py"},
        "commits": [{"sha": sha, "branche": "main"}],
        "taches_terminees": ["corriger le bouton"],
        "taches_restantes": [],
        "auteur": "dev",
    }
    corps.update(surcharge)
    return corps


@pytest.mark.parametrize("champ", ["answer", "recap", "tests_detail", "commits",
                                   "taches_terminees", "taches_restantes"])
def test_champ_obligatoire_manquant_400(ctx, depot, champ):  # noqa: F811
    client, _macro, micro_id = ctx
    corps = _rendu(depot)
    corps.pop(champ)
    r = client.post(f"/api/micros/{micro_id}/rendu", json=corps)
    assert r.status_code == 400, r.data
    charge = r.get_json()
    assert _manquants(r), charge


def test_answer_sans_les_six_sections_400(ctx, depot):  # noqa: F811
    client, _macro, micro_id = ctx
    r = client.post(f"/api/micros/{micro_id}/rendu", json=_rendu(depot, answer="## 1. seul"))
    assert r.status_code == 400
    assert any("## 6." in m for m in _manquants(r))


def test_commit_inexistant_refuse(ctx, depot):  # noqa: F811
    client, _macro, micro_id = ctx
    r = client.post(f"/api/micros/{micro_id}/rendu",
                    json=_rendu(depot, commits=[{"sha": "deadbeef" * 5, "branche": "main"}]))
    assert r.status_code == 400, r.data
    assert r.get_json()["error"]["code"] == "commit_inconnu"


def test_rendu_valide_passe_a_verifier_avec_recap(ctx, depot):  # noqa: F811
    client, _macro, micro_id = ctx
    r = client.post(f"/api/micros/{micro_id}/rendu", json=_rendu(depot))
    assert r.status_code == 201, r.data
    assert r.get_json()["ticket_id"]
    relu = client.get(f"/api/micros/{micro_id}/rendu").get_json()["rendu"]
    assert relu["auteur"] == "dev"
    assert relu["commits"][0]["verifie"] is True
    assert relu["recap"]["tests"]  # composé depuis tests_detail
    detail = client.get(f"/api/lignes/{micro_id}")
    assert detail.status_code == 200, detail.data
    ligne = detail.get_json()["ligne"]
    assert ligne["statut_ui"] == "a_relire", ligne.get("statut_ui")
    assert "corriger le bouton" in detail.get_data(as_text=True)  # récap « fait » comme un agent
