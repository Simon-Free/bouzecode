# [desc] Contrats HTTP de la page Profils : jamais d'écrasement silencieux (409), jamais de perte silencieuse d'une sélection introuvable, jamais un 200 pour un échec (422/502). [/desc]
"""Ce que la page Profils (SPEC §6, R4) exige du serveur, prouvé au client Flask.

Tout est isolé dans un CONFIG_DIR temporaire (profils et skills globaux) : aucun test ne
touche le vrai ~/.bouzecode. Le catalogue distant est remplacé par monkeypatch — aucun
appel réseau ni git.
"""
from __future__ import annotations

import pytest
import yaml


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    from bouzecode.backend.core import config, paths
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    paths.register_extra_dirs([])
    yield
    paths.register_extra_dirs([])


@pytest.fixture()
def client():
    from bouzecode.web_v2.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _write_profile(tmp_path, name, **fields):
    d = tmp_path / "profiles"
    d.mkdir(exist_ok=True)
    (d / f"{name}.yaml").write_text(yaml.safe_dump({"name": name, **fields}), encoding="utf-8")


# ---------------------------------------------------------------- profils


def test_creer_un_profil_sous_un_nom_pris_est_refuse_en_409_sans_ecraser(client, tmp_path):
    """« Nouveau profil » sous un nom déjà pris : 409, et l'original reste intact."""
    assert client.post("/api/profiles", json={"name": "reviewer", "system_prompt_extra": "original"}).status_code == 200
    resp = client.post("/api/profiles", json={"name": "reviewer", "system_prompt_extra": "écrasé", "create": True})
    assert resp.status_code == 409
    assert "existe déjà" in resp.get_json()["error"]["message"]
    assert client.get("/api/profiles/reviewer").get_json()["system_prompt_extra"] == "original"


def test_enregistrer_un_profil_existant_sans_create_le_met_a_jour(client):
    client.post("/api/profiles", json={"name": "reviewer", "system_prompt_extra": "v1"})
    assert client.post("/api/profiles", json={"name": "reviewer", "system_prompt_extra": "v2"}).status_code == 200
    assert client.get("/api/profiles/reviewer").get_json()["system_prompt_extra"] == "v2"


def test_un_outil_introuvable_deja_porte_par_le_profil_est_conserve(client, tmp_path):
    """Un plugin retiré laisse ses outils « introuvables » dans le profil : les réenregistrer
    ne doit NI les refuser NI les perdre (bug D3), et la réponse les signale."""
    _write_profile(tmp_path, "vieux", tools=["Read", "OutilDisparu"], skills=["skill-disparue"])
    resp = client.post("/api/profiles", json={
        "name": "vieux", "tools": ["Read", "OutilDisparu"], "skills": ["skill-disparue"],
        "system_prompt_extra": "v2"})
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["missing"] == {"tools": ["OutilDisparu"], "skills": ["skill-disparue"]}
    saved = client.get("/api/profiles/vieux").get_json()
    assert "OutilDisparu" in saved["tools"] and saved["skills"] == ["skill-disparue"]


def test_un_outil_inconnu_NOUVEAU_reste_refuse(client, tmp_path):
    """La tolérance ne vaut que pour ce que le profil portait déjà : une faute de frappe reste refusée."""
    _write_profile(tmp_path, "vieux", tools=["Read", "OutilDisparu"])
    resp = client.post("/api/profiles", json={"name": "vieux", "tools": ["Read", "OutilDisparu", "Teleport"]})
    assert resp.status_code == 400
    assert "Teleport" in resp.get_json()["error"]["message"]


def test_dupliquer_un_profil_conserve_ses_selections_introuvables(client, tmp_path):
    """« Dupliquer » (based_on) : la copie garde les sélections introuvables de l'original."""
    _write_profile(tmp_path, "origine", tools=["Read", "OutilDisparu"])
    resp = client.post("/api/profiles", json={
        "name": "origine-copie", "tools": ["Read", "OutilDisparu"], "create": True, "based_on": "origine"})
    assert resp.status_code == 200, resp.get_json()
    assert "OutilDisparu" in client.get("/api/profiles/origine-copie").get_json()["tools"]


def test_la_liste_des_profils_signale_les_selections_introuvables(client, tmp_path):
    _write_profile(tmp_path, "vieux", tools=["Read", "OutilDisparu"])
    agents = {a["name"]: a for a in client.get("/api/builder/agents").get_json()["agents"]}
    assert agents["vieux"]["missing"]["tools"] == ["OutilDisparu"]
    client.post("/api/profiles", json={"name": "propre", "tools": ["Read"]})
    agents = {a["name"]: a for a in client.get("/api/builder/agents").get_json()["agents"]}
    assert agents["propre"]["missing"] == {"tools": [], "skills": []}


def test_les_garde_fous_annoncent_leur_valeur_par_defaut(client):
    """« Par défaut » n'est jamais un mystère : chaque garde-fou dit ce qu'il vaut sans réglage."""
    hooks = client.get("/api/builder/catalog").get_json()["hooks"]
    assert all(isinstance(h.get("default"), bool) and h.get("label") for h in hooks)


# ---------------------------------------------------------------- skills


def _skill(name, desc="d"):
    return f"---\nname: {name}\ndescription: {desc}\n---\n\n# {name}\n"


def test_creer_une_skill_sous_un_nom_existant_est_refuse_en_409(client, tmp_path):
    """« Nouvelle skill » sous un nom déjà pris : 409, l'existante n'est pas écrasée (bug D4)."""
    assert client.post("/api/skills", json={"name": "ma-skill", "content": _skill("ma-skill", "originale")}).status_code == 200
    resp = client.post("/api/skills", json={"name": "ma-skill", "content": _skill("ma-skill", "écrasée"), "create": True})
    assert resp.status_code == 409
    assert "existe déjà" in resp.get_json()["error"]["message"]
    assert "originale" in (tmp_path / "skills" / "ma-skill.md").read_text(encoding="utf-8")


def test_modifier_une_skill_existante_sans_create_reste_permis(client, tmp_path):
    client.post("/api/skills", json={"name": "ma-skill", "content": _skill("ma-skill", "v1")})
    assert client.post("/api/skills", json={"name": "ma-skill", "content": _skill("ma-skill", "v2")}).status_code == 200
    assert "v2" in (tmp_path / "skills" / "ma-skill.md").read_text(encoding="utf-8")


def test_une_skill_a_nom_compose_se_lit(client):
    """Les skills de plugin ont des noms composés (« bouzecode/agent-loop ») : la lecture
    ne doit pas répondre 404 parce que le nom contient une barre."""
    skills = client.get("/api/skills").get_json()["skills"]
    composed = [s["name"] for s in skills if "/" in s["name"]]
    if not composed:
        pytest.skip("aucune skill à nom composé dans cet environnement")
    resp = client.get(f"/api/skills/{composed[0]}")
    assert resp.status_code == 200
    assert resp.get_json()["name"] == composed[0]


# ---------------------------------------------------------------- catalogue d'agents


def test_installer_un_agent_inconnu_est_une_erreur_http(client, monkeypatch):
    """Un échec d'installation n'est plus un 200 {ok:false} : 422 avec un message lisible."""
    from bouzecode.web_v2.services import agent_catalog
    monkeypatch.setattr(agent_catalog.catalog, "list_catalog_profiles", lambda: {})
    resp = client.post("/api/agents/install", json={"name": "fantome"})
    assert resp.status_code == 422
    body = resp.get_json()
    assert "fantome" in body["error"]["message"]


def test_rafraichir_le_catalogue_en_echec_repond_502_avec_la_vue_en_cache(client, monkeypatch):
    """Le catalogue distant injoignable : 502 (jamais un faux succès) + la vue en cache dans le corps."""
    from bouzecode.web_v2.services import agent_catalog

    def _boom(force=False):
        raise RuntimeError("git clone failed: réseau")
    monkeypatch.setattr(agent_catalog.catalog, "refresh_catalog", _boom)
    monkeypatch.setattr(agent_catalog.catalog, "installed_and_available", lambda: ({}, {}))
    resp = client.post("/api/agents/catalog/refresh")
    assert resp.status_code == 502
    body = resp.get_json()
    assert "réseau" in body["error"]["message"]
    vue = body["error"]["details"]  # la vue en cache, que l'UI continue d'afficher
    assert vue["installed"] == [] and vue["available"] == []


def test_une_skill_integree_sans_fichier_s_ouvre_avec_son_contenu(client):
    """Les skills intégrées n'ont pas de fichier (« <builtin> ») : l'éditeur recevait un texte
    VIDE, et « Enregistrer une copie globale » aurait écrit une skill vide. Le contenu est
    reconstruit (en-tête + corps), et il passe la validation d'enregistrement."""
    skills = client.get("/api/skills").get_json()["skills"]
    builtin = [s["name"] for s in skills if s["source"] == "builtin" and "/" not in s["name"]]
    if not builtin:
        pytest.skip("aucune skill intégrée dans cet environnement")
    body = client.get(f"/api/skills/{builtin[0]}").get_json()
    assert body["content"].startswith("---\nname: ")
    assert len(body["content"]) > 100
    from bouzecode.web_v2.services.skills import frontmatter_problem
    assert frontmatter_problem(body["content"]) == ""
