# [desc] Tests the wire pieces a host agent (Focus) must not receive: Methodology echo, dev profile, session context. [/desc]
"""Ce qu'un agent hôte (Focus) ne doit pas recevoir de bouzecode.

Incident Focus du 2026-09-28/29 (claude-opus-5 via le gateway, refus content_filter) :
- l'écho `[↩ Methodology: {"content": …}]` recopiait côté utilisateur la note que le
  modèle venait d'écrire — seul déclencheur restant d'un refus en milieu de conversation
  (bissection sur le vrai payload) ; la note est déjà dans le bloc METHODOLOGY ;
- le profil « Agent de développement » et le contexte de session (répertoire, branche)
  étaient ajoutés au prompt d'un agent métier qui n'a ni dépôt ni worktree.
"""
from bouzecode.backend.agent.minimal_payload import _tool_call_recall
from bouzecode.backend.agent.providers.backends.dispatch import stream

READ_SCHEMA = {
    "name": "Read",
    "description": "Read a file from disk.",
    "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}},
                     "required": ["file_path"]},
}


def test_methodology_and_snippet_recalls_never_echo_their_content():
    assert _tool_call_recall("Methodology", {"content": "### T8\nfait constaté"}) == "[↩ Methodology]\n"
    assert _tool_call_recall("Snippet", {"tool_id": "d1", "label": "schéma"}) == "[↩ Snippet]\n"


def test_other_tools_keep_their_input_recall():
    assert _tool_call_recall("Bash", {"command": "git status"}) == "[↩ Bash: git status]\n"


def _system_text(config: dict) -> str:
    generator = stream(model="deepseek-v4-flash", system="Tu es l'agent Focus.",
                       messages=[{"role": "user", "content": "Hello"}],
                       tool_schemas=[READ_SCHEMA], config={"xml_tools": True, **config})
    payload = next(generator)
    generator.close()
    return "\n".join(block["text"] for block in payload.system_blocks)


def test_host_agent_can_drop_the_dev_profile_and_the_session_context(monkeypatch):
    monkeypatch.setenv("OPENROUTER_KEY", "sk-or-fake")
    host = _system_text({"agent_profile_extra": False, "session_context": False})
    assert "Tu es l'agent Focus." in host
    assert "# Contexte de session" not in host
    assert host == _system_text({"agent_profile_extra": False, "session_context": False})
    default = _system_text({})
    assert "# Contexte de session" in default
    assert len(default) > len(host)
