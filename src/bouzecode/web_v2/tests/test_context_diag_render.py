from bouzecode.web_v2.services.sessions.context_diag_render import render_context_diag_html

TEXT = '## Titre\n\n- point **gras**\n\n<tool_use name="Bash"><param name="command">ls</param></tool_use>\n'


def _html():
    diag = {
        "turn": 34,
        "session_id": "x",
        "model": "m",
        "totals": {},
        "delta_items": [{"kind": "assistant", "text": TEXT, "est_tokens": 10}],
        "cached_items": [],
    }
    return render_context_diag_html(diag)


def test_markdown_est_formate():
    h = _html()
    assert "<h4>Titre</h4>" in h
    assert "<strong>gras</strong>" in h
    assert "## Titre" not in h


def test_xml_est_togglable_et_indente():
    h = _html()
    assert 'class="cd-xml"' in h
    assert "Bash" in h
    assert "  &lt;param" in h
