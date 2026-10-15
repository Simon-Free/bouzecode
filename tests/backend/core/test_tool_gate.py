# [desc] hook pré-exécution config['_tool_gate'] fourni par l'hôte (Demo) : autorisation, refus rendu au modèle, échec fermé, pas de contournement par la mémoire anti-répétition. [/desc]
"""L'application hôte doit pouvoir contrôler chaque appel d'outil AVANT exécution, sur le
chemin unique `tool_registry.execute_tool` (boucle d'agent, DAG, sous-agents)."""
from __future__ import annotations

import pytest

from bouzecode.backend.core import tool_registry as reg

_APPELS: list = []


def _outil(name: str, read_only: bool = False) -> reg.ToolDef:
    return reg.ToolDef(
        name=name,
        schema={"name": name, "description": "outil de test",
                "input_schema": {"type": "object", "properties": {"x": {"type": "string"}},
                                 "required": ["x"]}},
        func=lambda params, config: _APPELS.append((name, params["x"])) or f"ok:{params['x']}",
        read_only=read_only,
    )


@pytest.fixture(autouse=True)
def _outils():
    _APPELS.clear()
    reg.push_local_overlay()
    for name in ("Bash", "Read", "ZzLecture"):
        reg.register_tool(_outil(name, read_only=(name in ("Read", "ZzLecture"))))
    yield
    reg.pop_local_overlay()


def test_sans_hook_rien_ne_change():
    assert reg.execute_tool("Bash", {"x": "ls"}, {}) == "ok:ls"


def test_tool_gate_autorise_ou_refuse():
    vus = []

    def gate(name, params, config):
        vus.append((name, dict(params)))
        return "commande interdite" if name == "Bash" else None

    config = {reg.TOOL_GATE_KEY: gate}
    assert reg.execute_tool("Read", {"x": "f"}, config) == "ok:f"
    refus = reg.execute_tool("Bash", {"x": "rm -rf /"}, config)
    assert refus.startswith("Error") and "commande interdite" in refus
    assert _APPELS == [("Read", "f")]
    assert vus == [("Read", {"x": "f"}), ("Bash", {"x": "rm -rf /"})]


def test_tool_gate_en_erreur_echoue_ferme():
    def gate(name, params, config):
        raise RuntimeError("politique illisible")

    refus = reg.execute_tool("Read", {"x": "f"}, {reg.TOOL_GATE_KEY: gate})
    assert "refusé par le point de contrôle" in refus and "RuntimeError" in refus
    # Le détail de la politique reste dans le journal serveur, jamais rendu au modèle.
    assert "politique illisible" not in refus
    assert _APPELS == []


def test_tool_gate_non_contourne_par_la_memoire_anti_repetition():
    config: dict = {}
    assert reg.execute_tool("ZzLecture", {"x": "a"}, config) == "ok:a"
    config[reg.TOOL_GATE_KEY] = lambda name, params, cfg: "lecture coupée"
    assert "lecture coupée" in reg.execute_tool("ZzLecture", {"x": "a"}, config)


def test_chemin_de_la_boucle_d_agent_passe_par_le_hook():
    """`tools.execute_tool` (appelé par le DAG de la boucle d'agent) transmet la config
    au registre : le hook de l'hôte y est donc appliqué."""
    from bouzecode.backend.tools import execute_tool as execute_depuis_la_boucle

    reg.register_tool(_outil("ZzEcriture"))
    config = {reg.TOOL_GATE_KEY: lambda name, params, cfg: "écriture refusée par l'hôte"}
    resultat = execute_depuis_la_boucle("ZzEcriture", {"x": "a"}, config=config)
    assert "écriture refusée par l'hôte" in resultat
    assert _APPELS == []


# --------------- sous-agents : le point de contrôle doit suivre ---------------

class _FakeTask:
    status = "done"
    result = "ok"
    worktree_branch = ""
    worktree_path = ""
    name = "x"
    id = "t1"


@pytest.fixture
def sous_agent_en_process(monkeypatch):
    """`_agent_tool` sur la voie en process, avec un gestionnaire qui capture la config."""
    from bouzecode.backend.multi_agent import enfants, gestionnaire, outil_agent
    from bouzecode.backend.tools import interaction

    captured: dict = {}

    class _Mgr:
        def spawn(self, prompt, cfg, system_prompt, **kw):
            captured["cfg"] = cfg
            return _FakeTask()

        def wait(self, *a, **k):
            return None

    monkeypatch.setattr(gestionnaire, "get_agent_manager", lambda: _Mgr())
    monkeypatch.setattr(outil_agent, "_is_terminal_mode", lambda: False)
    monkeypatch.setattr(interaction, "is_web_ipc_active", lambda: False)
    monkeypatch.setattr(enfants, "noter_enfant_local", lambda *a, **k: None)
    return outil_agent, captured


def test_le_hook_suit_le_sous_agent_en_process(sous_agent_en_process):
    outil_agent, captured = sous_agent_en_process

    def gate(name, params, config):
        return "Bash interdit par l'hôte" if name == "Bash" else None

    outil_agent._agent_tool({"prompt": "lance Bash"}, {reg.TOOL_GATE_KEY: gate, "_depth": 0, "model": "m"})
    cfg_enfant = captured["cfg"]
    assert cfg_enfant.get(reg.TOOL_GATE_KEY) is gate
    assert "_depth" not in cfg_enfant  # les autres clés privées restent filtrées
    # Un appel d'outil du sous-agent (même chemin execute_tool) est donc contrôlé.
    assert "Bash interdit par l'hôte" in reg.execute_tool("Bash", {"x": "id"}, cfg_enfant)
    assert _APPELS == []


def test_sous_agent_hors_process_refuse_quand_un_hook_est_pose(monkeypatch):
    from bouzecode.backend.multi_agent import lancement_terminal, lancement_web, outil_agent
    from bouzecode.backend.tools import interaction

    lance = []
    monkeypatch.setattr(lancement_web, "_spawn_web_ticket_agent",
                        lambda p, c: lance.append("web") or "ok")
    monkeypatch.setattr(outil_agent, "_is_terminal_mode", lambda: False)
    monkeypatch.setattr(interaction, "is_web_ipc_active", lambda: True)
    config = {reg.TOOL_GATE_KEY: lambda n, p, c: None}
    refus = outil_agent._agent_tool({"prompt": "x"}, config)
    assert refus.startswith("Error") and reg.TOOL_GATE_KEY in refus and lance == []
    refus = lancement_terminal._spawn_terminal_agent({"prompt": "x"}, config)
    assert refus.startswith("Error") and reg.TOOL_GATE_KEY in refus
    # Sans hook, la voie web reste ouverte.
    assert outil_agent._agent_tool({"prompt": "x"}, {}) == "ok" and lance == ["web"]


def test_le_hook_suit_le_relecteur_de_cloture(monkeypatch):
    from bouzecode.backend.agent import close_review
    from bouzecode.backend.multi_agent import gestionnaire
    from bouzecode.backend.profiles import discovery

    captured: dict = {}

    class _Mgr:
        def spawn(self, prompt, cfg, system_prompt, **kw):
            captured["cfg"] = cfg
            return _FakeTask()

        def wait(self, *a, **k):
            return None

    monkeypatch.setattr(gestionnaire, "get_agent_manager", lambda: _Mgr())
    monkeypatch.setattr(discovery, "resolve_agent_profile", lambda name: None)
    gate = lambda n, p, c: None  # noqa: E731
    close_review._lancer("relis", {reg.TOOL_GATE_KEY: gate, "_state": object()})
    assert captured["cfg"].get(reg.TOOL_GATE_KEY) is gate
    assert "_state" not in captured["cfg"]
