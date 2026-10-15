"""Le dump de diagnostic d'une complétion dégénérée.

Demandé après trois incidents consécutifs (2026-09-28, claude-opus-5) où le run se
fermait sur « empty completion » SANS QUE PERSONNE NE VOIE les tokens réellement
émis : le warning ne portait qu'un extrait tronqué, perdu dans le terminal. Ici on
vérifie qu'un fichier JSON persistant est écrit par incident, qu'il contient le
texte brut INTÉGRAL (et non tronqué) et que son chemin est rendu à l'appelant pour
être cité dans le warning.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

MODULE = "bouzecode.backend.agent.providers.backends.completion_diagnostics"


def _dump(**kwargs):
    from bouzecode.backend.agent.providers.backends import completion_diagnostics as cd
    return cd.dump_degenerate_completion(**kwargs)


def test_dump_ecrit_un_json_et_rend_son_chemin(tmp_path, monkeypatch):
    from bouzecode.backend.agent.providers.backends import completion_diagnostics as cd
    monkeypatch.setattr(cd, "DIAGNOSTICS_DIR", tmp_path)

    path = _dump(
        reason="protocol_discarded",
        model="claude-opus-5",
        provider="anthropic",
        stop_reason="end_turn",
        raw_text="<tool_calls>",
        streamed_text="",
        tool_calls=[],
        usage={"in": 71350, "out": 9},
        events=[{"type": "content_block_delta", "delta_type": "text_delta", "text": "<tool_calls>"}],
    )

    assert path is not None, "le dump doit rendre le chemin du fichier écrit"
    assert Path(path).exists(), f"fichier de diagnostic absent : {path}"
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    assert data["reason"] == "protocol_discarded"
    assert data["model"] == "claude-opus-5"
    assert data["stop_reason"] == "end_turn"
    assert data["raw_text"] == "<tool_calls>"
    assert data["events"][0]["delta_type"] == "text_delta"
    # Quel code a produit le tour (export « malgré un pull » du 2026-10-06).
    assert data["bouzecode_version"] not in ("", "unknown")
    assert "bouzecode_boot_commit" in data and "bouzecode_branche" in data


def test_dump_conserve_le_texte_brut_en_entier(tmp_path, monkeypatch):
    """`discarded_text` est tronqué à 400 car. pour le warning ; le dump, lui, est
    la source de vérité pour déboguer et ne doit RIEN tronquer."""
    from bouzecode.backend.agent.providers.backends import completion_diagnostics as cd
    monkeypatch.setattr(cd, "DIAGNOSTICS_DIR", tmp_path)

    gros = "x" * 5000
    path = _dump(reason="protocol_discarded", model="m", provider="anthropic",
                 stop_reason="end_turn", raw_text=gros, streamed_text="",
                 tool_calls=[], usage={}, events=[])

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    assert data["raw_text"] == gros, "le texte brut a été tronqué dans le dump"


def test_deux_incidents_ne_sécrasent_pas(tmp_path, monkeypatch):
    from bouzecode.backend.agent.providers.backends import completion_diagnostics as cd
    monkeypatch.setattr(cd, "DIAGNOSTICS_DIR", tmp_path)

    kw = dict(reason="empty", model="m", provider="anthropic", stop_reason="end_turn",
              streamed_text="", tool_calls=[], usage={}, events=[])
    p1 = _dump(raw_text="premier", **kw)
    p2 = _dump(raw_text="second", **kw)

    assert p1 != p2, "deux incidents doivent produire deux fichiers distincts"
    assert len(list(tmp_path.glob("*.json"))) == 2


def test_un_echec_decriture_ne_casse_jamais_le_run(tmp_path, monkeypatch):
    """Le diagnostic est un bonus : s'il échoue (disque plein, droits), il doit
    renvoyer None sans lever — jamais tuer la session qu'il documente."""
    from bouzecode.backend.agent.providers.backends import completion_diagnostics as cd
    monkeypatch.setattr(cd, "DIAGNOSTICS_DIR", tmp_path / "fichier_pas_dossier")
    (tmp_path / "fichier_pas_dossier").write_text("je ne suis pas un dossier", encoding="utf-8")

    path = _dump(reason="empty", model="m", provider="anthropic", stop_reason="end_turn",
                 raw_text="x", streamed_text="", tool_calls=[], usage={}, events=[])
    assert path is None
