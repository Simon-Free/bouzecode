# [desc] Agent-builder API (global): catalogue + CRUD profils ~/.bouzecode + installation de plugins depuis GitLab; le YAML écrit doit être relu par le vrai loader bouzecode. [/desc]
"""Créer, relire et supprimer ses propres agents et skills depuis l'atelier.

L'atelier (« agent builder ») laisse l'utilisateur composer un agent : un nom, des
outils, des skills, des hooks, un bout de prompt. Ce qu'il enregistre part dans son
dossier global et doit être relu tel quel par bouzecode ailleurs — un profil qui ne
se recharge pas ne sert à rien.

Tout est isolé dans un CONFIG_DIR temporaire : aucun test ne touche le vrai
~/.bouzecode, et rien n'est simulé.
"""
import pytest


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    from bouzecode.backend.core import config, paths
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)          # clean cwd: no project .bouzecode interference
    paths.register_extra_dirs([])    # reset in-memory extra-dir registry
    yield
    paths.register_extra_dirs([])


@pytest.fixture()
def client():
    from bouzecode.web_v2.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_catalog_lists_real_tools_skills_hooks(client):
    """L'atelier propose les vrais outils et hooks de bouzecode, en signalant ceux en lecture seule."""
    data = client.get("/api/builder/catalog").get_json()
    tool_names = {t["name"] for t in data["tools"]}
    assert {"Read", "Write", "Bash"} <= tool_names
    assert any(t["name"] == "Read" and t["read_only"] for t in data["tools"])
    assert {h["name"] for h in data["hooks"]} == {"test_enforcement", "enforcement", "loop_detection"}


def _write_global_skill(tmp_path, name: str) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(exist_ok=True)
    (skills_dir / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: d\n---\ncorps.", encoding="utf-8")


def test_save_is_global_and_loadable_by_bouzecode(client, tmp_path):
    """Un agent enregistré apparaît dans la liste ET se recharge tel quel depuis n'importe quel projet."""
    _write_global_skill(tmp_path, "refactoring")
    body = {
        "name": "code-reviewer", "tools": ["Read", "Grep"], "skills": ["refactoring"],
        "hooks": ["test_enforcement", "no-loop_detection"], "model": "claude-opus-4-8",
        "system_prompt_extra": "Tu es un relecteur adverse.",
    }
    saved = client.post("/api/profiles", json=body).get_json()
    assert saved["name"] == "code-reviewer"

    listed = client.get("/api/profiles").get_json()["profiles"]
    assert [p["name"] for p in listed] == ["code-reviewer"]

    # written to the global dir, and resolvable everywhere via discovery
    from bouzecode.backend.profiles import load_profile_from_path, load_user_profiles
    prof = load_profile_from_path(tmp_path / "profiles" / "code-reviewer.yaml")
    assert prof.tools == ["Read", "Grep"] and prof.hooks == ["test_enforcement", "no-loop_detection"]
    assert "code-reviewer" in load_user_profiles()


def test_invalid_name_and_hook_filtering(client):
    """Un nom d'agent invalide est refusé, et les hooks connus (activés ou désactivés) sont acceptés."""
    assert client.post("/api/profiles", json={"name": "Bad Name!"}).status_code == 400
    saved = client.post("/api/profiles", json={
        "name": "p1", "hooks": ["enforcement", "no-test_enforcement"]}).get_json()
    assert saved["hooks"] == ["enforcement", "no-test_enforcement"]


def test_delete_profile(client):
    """Supprimer un agent le fait disparaître : le relire renvoie introuvable."""
    client.post("/api/profiles", json={"name": "tmp1", "tools": ["Read"]})
    assert client.delete("/api/profiles/tmp1").get_json() == {"ok": True}
    assert client.get("/api/profiles/tmp1").status_code == 404


def test_plugin_from_gitlab_missing_input_rejected(client):
    """Demander l'installation d'un plugin sans rien préciser est refusé."""
    assert client.post("/api/plugins/from-gitlab", json={}).status_code == 400


def test_plugin_from_gitlab_bad_input_rejected(client):
    """Une source de plugin qui n'est ni une URL ni un dossier est refusée avant tout clone."""
    # Neither a URL nor an existing git folder → clear 400, no clone / pip attempted.
    resp = client.post("/api/plugins/from-gitlab", json={"input": "not-a-url-not-a-dir"})
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_preview_returns_full_prompt_with_custom_part(client, tmp_path):
    """L'aperçu montre le prompt complet de l'agent, texte perso et skills sélectionnées incluses."""
    # a global skill whose body must show up preloaded in the previewed prompt
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "myskill.md").write_text(
        "---\nname: myskill\ndescription: d\n---\nSKILL-PRELOAD-MARKER", encoding="utf-8")

    data = client.post("/api/builder/preview", json={
        "system_prompt_extra": "MARQUEUR-PROMPT-99", "tools": ["Read"],
        "hooks": ["enforcement"], "skills": ["myskill"],
    }).get_json()
    assert "MARQUEUR-PROMPT-99" in data["system_prompt"]
    assert data["custom_marker"] in data["system_prompt"]
    # skills selected → preloaded into the prompt text
    assert "SKILL-PRELOAD-MARKER" in data["system_prompt"]
    # tools/hooks are runtime-only, returned separately (not inlined in the prompt)
    assert data["runtime"]["tools"] == ["Read"]
    assert data["runtime"]["hooks"] == ["enforcement"]


def test_skill_create_get_list_delete(client, tmp_path):
    """Une skill écrite dans l'atelier est enregistrée, relisible, listée modifiable, puis supprimable."""
    content = "---\nname: my-skill\ndescription: une skill de test\n---\n\n# my-skill\ncorps."
    saved = client.post("/api/skills", json={"name": "my-skill", "content": content}).get_json()
    assert saved["name"] == "my-skill"
    assert (tmp_path / "skills" / "my-skill.md").is_file()

    listed = {s["name"]: s for s in client.get("/api/skills").get_json()["skills"]}
    assert listed["my-skill"]["editable"]

    got = client.get("/api/skills/my-skill").get_json()
    assert "corps." in got["content"] and got["editable"]

    assert client.delete("/api/skills/my-skill").get_json() == {"ok": True}
    assert not (tmp_path / "skills" / "my-skill.md").exists()


def test_skill_new_template_and_invalid_name(client):
    """Une nouvelle skill part d'un modèle prérempli ; un nom invalide ou un corps vide sont refusés."""
    tpl = client.get("/api/skills/cool-skill?new=1").get_json()
    assert "cool-skill" in tpl["content"] and tpl["editable"]
    assert client.post("/api/skills", json={"name": "Bad Name", "content": "x"}).status_code == 400
    assert client.post("/api/skills", json={"name": "ok-name", "content": ""}).status_code == 400


_SKILL_WITH_TABLE_UNCLOSED = """\
---
name: tabled
description: une skill avec un tableau
Instructions AVANT le tableau.

| Colonne | Sens |
|---------|------|
| a       | b    |

Instructions APRES le tableau.
"""


def test_skill_with_unclosed_frontmatter_is_refused(client, tmp_path):
    """Enregistrer une skill dont le frontmatter n'est pas refermé est refusé, pas enregistré amputé."""
    resp = client.post("/api/skills", json={"name": "tabled",
                                            "content": _SKILL_WITH_TABLE_UNCLOSED})

    assert resp.status_code == 400
    assert "---" in resp.get_json()["error"]
    assert not (tmp_path / "skills" / "tabled.md").exists()


def test_skill_without_description_is_refused(client, tmp_path):
    """Une skill sans description est refusée : sans elle, l'agent ne saura jamais quand la charger."""
    resp = client.post("/api/skills", json={
        "name": "muette", "content": "---\nname: muette\ndescription:\n---\ncorps."})

    assert resp.status_code == 400
    assert "description" in resp.get_json()["error"]
    assert not (tmp_path / "skills" / "muette.md").exists()


def test_skill_without_frontmatter_at_all_is_refused(client):
    """Un simple texte markdown sans frontmatter n'est pas une skill : refusé."""
    resp = client.post("/api/skills", json={"name": "nue", "content": "# nue\njuste du texte"})

    assert resp.status_code == 400
    assert "frontmatter" in resp.get_json()["error"]


def test_profile_with_unknown_tool_skill_or_hook_is_refused(client, tmp_path):
    """Un agent qui réclame un outil, une skill ou un hook inexistant est refusé, pas enregistré diminué."""
    for payload, expected in [
        ({"name": "a1", "tools": ["Read", "Teleport"]}, "Teleport"),
        ({"name": "a2", "skills": ["skill-fantome"]}, "skill-fantome"),
        ({"name": "a3", "hooks": ["made_up"]}, "made_up"),
    ]:
        resp = client.post("/api/profiles", json=payload)
        assert resp.status_code == 400
        assert expected in resp.get_json()["error"]
        assert not (tmp_path / "profiles" / f"{payload['name']}.yaml").exists()


def test_agent_import_with_broken_yaml_is_refused(client):
    """Importer un agent dont le YAML ne parse pas renvoie une erreur claire, pas une erreur serveur."""
    resp = client.post("/api/agents/import", json={"yaml": "name: [oups\n  - pas: du yaml"})

    assert resp.status_code == 400
    assert "YAML" in resp.get_json()["error"]


def test_builder_agents_lists_profiles_and_system_agents(client):
    """La liste des agents distingue ceux que l'utilisateur peut modifier de ceux du système."""
    client.post("/api/profiles", json={"name": "mine", "tools": ["Read"], "system_prompt_extra": "x"})
    agents = client.get("/api/builder/agents").get_json()["agents"]
    by_name = {a["name"]: a for a in agents}
    # the global profile we just saved is editable
    assert by_name["mine"]["kind"] == "profil" and by_name["mine"]["editable"]
    # system builtins appear, read-only, with full fields for cloning
    assert by_name["meta-agent"]["kind"] == "système" and not by_name["meta-agent"]["editable"]
    assert "creating-agents" in by_name["meta-agent"]["system_prompt_extra"]
    # general-purpose is now a first-class system agent (no longer hidden)
    assert by_name["general-purpose"]["kind"] == "système"
    assert {"general-purpose", "meta-agent", "manager"} <= set(by_name)
