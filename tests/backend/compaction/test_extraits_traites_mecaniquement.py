# [desc] La compaction retire / relit / fusionne les extraits de la note sans appel au modèle [/desc]
"""Les extraits (snippets) de la note, traités mécaniquement à la compaction.

Rejoué le 2026-09-24 sur une vraie session DeepSeek : 50 extraits dont ~46 périmés,
jetables ou en double, aucun retiré (juge tronqué), et 31 marqueurs « périmé » avalés
par la synthèse de prose — les vieux extraits paraissaient valides. On observe ici,
par l'outil Methodology (le chemin de l'agent), ce que devient la note.
"""
from __future__ import annotations

import os
import tempfile

import pytest

from bouzecode.backend.agent.providers import AssistantTurn, StreamStarted
from bouzecode.backend.agent.stream_interceptor import set_stream_interceptor
from bouzecode.backend.context_manager import compact_methodology as cm
from bouzecode.backend.context_manager.compact_prose import compact_prose
from bouzecode.backend.context_manager.methodology import methodology_tool
from bouzecode.backend.context_manager.state import METHODOLOGY_NOTE, ContextState


class Session:
    def __init__(self):
        self.turn_count, self.compaction_log = 0, []


class Modele:
    """Répond au juge et au résumeur ; note chaque appel."""

    def __init__(self, juge="KEEP ALL", resume="Mission en cours : réparer x.", fin="end_turn"):
        self.juge, self.resume, self.fin, self.appels = juge, resume, fin, []

    def __call__(self, _raw):
        def stream(model=None, system=None, messages=None, tool_schemas=None, config=None):
            texte = str(messages[0]["content"])
            self.appels.append({"juge": "SNIPPETS IN MEMORY" in texte, "config": config})
            reponse = self.juge if "SNIPPETS IN MEMORY" in texte else self.resume
            yield StreamStarted()
            yield AssistantTurn(text=reponse, tool_calls=[], in_tokens=0, out_tokens=0,
                                stop_reason=self.fin)
        return stream


@pytest.fixture
def modele():
    def installer(**kw) -> Modele:
        m = Modele(**kw)
        set_stream_interceptor(m)
        return m
    yield installer
    set_stream_interceptor(None)


@pytest.fixture
def seuil_extraits_morts_bas(monkeypatch):
    """La passe mécanique part dès le moindre extrait mort (seuil C à 1 token)."""
    monkeypatch.setattr(cm, "DEAD_SNIPPET_TOKENS_THRESHOLD", 1)


def _ecrire(path, lignes: list[str]) -> str:
    path.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    return str(path)


def _extrait(path: str, loc: str, corps: dict[int, str], libelle: str = "vu") -> str:
    lignes = "\n".join(f"{n:>5}  {t}" for n, t in corps.items())
    return f'## snippet: {path}{loc} — "{libelle}"\n{lignes}'


def _ajouter(note: str, ajout: str = "## Delta tour 9\nJe continue.") -> tuple[str, str]:
    """L'agent écrit dans sa note (ce qui arme la compaction) ; rend (note, message)."""
    etat = ContextState(notes={METHODOLOGY_NOTE: note})
    msg = methodology_tool({"content": ajout},
                           {"_context_state": etat, "_state": Session(), "_depth": 0})
    return etat.notes[METHODOLOGY_NOTE], msg


def test_un_extrait_symbole_perime_est_relu_dans_le_fichier_actuel(tmp_path, modele,
                                                                   seuil_extraits_morts_bas):
    modele()
    app = _ecrire(tmp_path / "app.py", ["def calcul():", "    return 42", ""])
    note = "\n".join(["## User\nRéparer calcul.",
                      _extrait(app, " :: calcul", {1: "def calcul():", 2: "    return 0"}),
                      f"## snippet-stale: {app} :: calcul — STALE (file edited)"])
    apres, _msg = _ajouter(note)
    assert "return 42" in apres and "return 0" not in apres
    assert "snippet-stale" not in apres


def test_un_extrait_lignes_perime_est_retire_avec_une_trace(tmp_path, modele,
                                                            seuil_extraits_morts_bas):
    modele()
    app = _ecrire(tmp_path / "app.py", ["a = 1", "b = 2"])
    note = "\n".join(["## User\nx", _extrait(app, " L1-2", {1: "a = 0", 2: "b = 0"}),
                      f"## snippet-stale: {app} L1-2 — STALE (file edited)"])
    apres, _msg = _ajouter(note)
    assert f"## snippet: {app}" not in apres and "a = 0" not in apres
    assert f"## snippet-dropped: {app} L1-2 — extrait retiré (périmé) : relis-le si besoin" in apres


def test_les_extraits_temporaires_et_de_fichiers_disparus_sont_retires(tmp_path, modele,
                                                                       seuil_extraits_morts_bas):
    modele()
    fd, sonde = tempfile.mkstemp(suffix="_sonde.py", dir=tempfile.gettempdir())
    os.close(fd)
    try:
        disparu = str(tmp_path / "worktree_nettoye" / "server.py")
        note = "\n".join(["## User\nx", _extrait(sonde, " L1-1", {1: "print(1)"}),
                          _extrait(disparu, " L1-1", {1: "servir()"})])
        apres, _msg = _ajouter(note)
    finally:
        os.unlink(sonde)
    assert "print(1)" not in apres and "servir()" not in apres
    assert "(fichier temporaire)" in apres and "(fichier supprimé)" in apres


def test_les_doublons_et_chevauchements_sont_fusionnes_en_un_extrait_a_jour(
        tmp_path, modele, seuil_extraits_morts_bas):
    modele()
    app = _ecrire(tmp_path / "app.py", [f"ligne {n}" for n in range(1, 31)])
    note = "\n".join([
        "## User\nx",
        _extrait(app, " L1-20", {n: f"ligne {n}" for n in range(1, 21)}, "début"),
        _extrait(app, " L10-30", {n: f"ligne {n}" for n in range(10, 31)}, "large fin"),
        _extrait(app, " L1-20", {n: f"ligne {n}" for n in range(1, 21)}, "début bis"),
    ])
    apres, _msg = _ajouter(note)
    assert apres.count(f"## snippet: {app}") == 1
    assert f"## snippet: {app} L1-30" in apres and "   30  ligne 30" in apres


def test_un_marqueur_perime_n_est_jamais_avale_par_la_synthese(modele):
    modele(resume="Mission en cours : x.\n- fait : y")
    prose = "\n".join(f"## Tour {n}\n" + "Constat détaillé du tour. " * 40 for n in range(8))
    note = "\n".join(["## User\nx", "## snippet: /p/a.py :: f — \"f\"\n    1  def f(): pass",
                      "## snippet-stale: /p/a.py :: f — STALE (file edited)", prose])
    apres, retire = compact_prose(note, ContextState(), {"_state": Session(), "_depth": 0})
    assert retire > 0
    assert "## snippet-stale: /p/a.py :: f" in apres


def test_la_synthese_n_est_pas_redecoupee_en_prose_nouvelle_a_la_passe_suivante(modele):
    titres = "\n".join(f"## Section {n}\n" + "fait établi. " * 60 for n in range(7))
    m = modele(resume="Mission en cours : x.\n" + titres[:5000])
    prose = "\n".join(f"## Tour {n}\n" + "Constat détaillé du tour. " * 60 for n in range(20))
    config = {"_state": Session(), "_depth": 0}
    une, _ = compact_prose("## User\nx\n" + prose, ContextState(), config)
    appels = len(m.appels)
    compact_prose(une + "\n## Tour 11\nPetit ajout.", ContextState(), config)
    assert len(m.appels) == appels, "la synthèse a été reprise pour de la prose nouvelle"


def test_un_juge_coupe_n_est_pas_un_verdict_et_sera_reinterroge(tmp_path, modele, monkeypatch):
    m = modele(juge="Je réfléchis aux extraits", fin="length")
    monkeypatch.setattr(cm, "LIVE_SNIPPET_TOKENS_THRESHOLD", 1)
    app = _ecrire(tmp_path / "app.py", ["x = 1"])
    etat = ContextState(notes={METHODOLOGY_NOTE: "\n".join(
        ["## User\nx", _extrait(app, " L1-1", {1: "x = 1"})])})
    config = {"_context_state": etat, "_state": Session(), "_depth": 0}
    methodology_tool({"content": "## Delta tour 9\nJe continue."}, config)
    methodology_tool({"content": "## Delta tour 10\nencore"}, config)
    juges = [a for a in m.appels if a["juge"]]
    assert len(juges) == 2
    assert juges[0]["config"]["max_tokens"] >= 8192, "budget du juge trop court pour raisonner"


def test_une_reponse_vide_du_juge_n_est_pas_un_verdict(tmp_path, modele, monkeypatch):
    m = modele(juge="", fin="end_turn")
    monkeypatch.setattr(cm, "LIVE_SNIPPET_TOKENS_THRESHOLD", 1)
    app = _ecrire(tmp_path / "app.py", ["x = 1"])
    etat = ContextState(notes={METHODOLOGY_NOTE: "\n".join(
        ["## User\nx", _extrait(app, " L1-1", {1: "x = 1"})])})
    config = {"_context_state": etat, "_state": Session(), "_depth": 0}
    methodology_tool({"content": "## Delta tour 9\nJe continue."}, config)
    methodology_tool({"content": "## Delta tour 10\nencore"}, config)
    assert len([a for a in m.appels if a["juge"]]) == 2


def test_le_filet_de_securite_borne_la_note_quand_la_synthese_echoue(modele, monkeypatch):
    modele(resume="")  # la synthèse échoue (réponse vide)
    monkeypatch.setattr(cm, "NOTE_PROSE_TOKENS_THRESHOLD", 200)
    anciens = [f"## Delta tour {n}\n" + f"ancien constat {n}. " * 30 for n in range(40)]
    note = "\n".join(["## User\nMission : réparer x.", "## Todolist\n- [ ] étape",
                      *anciens])
    apres, _ = _ajouter(note, "## Delta tour 99\ndernier ajout")
    assert len(apres) < len(note) / 2
    assert "## élagage de secours" in apres
    assert "Mission : réparer x." in apres and "## Todolist" in apres
    assert "ancien constat 39" in apres and "dernier ajout" in apres
    assert "ancien constat 0." not in apres


def test_les_appels_de_compaction_ne_recoivent_pas_les_rappels_de_l_agent(monkeypatch):
    from bouzecode.backend.agent.providers.backends.dispatch import stream
    monkeypatch.setenv("ANTHROPIC_API_KEY", "cle-factice")

    def envoye(outils):
        gen = stream(model="anthropic/claude-sonnet-4-6", system="Tu résumes.",
                     messages=[{"role": "user", "content": "Note."}], tool_schemas=outils,
                     config={"_depth": 1})
        charge = next(gen)
        gen.close()
        return str(charge.messages) + str(charge.system_blocks)

    outil = [{"name": "Bash", "description": "shell",
              "input_schema": {"type": "object", "properties": {}}}]
    # Seul rappel d'agent restant depuis le retrait du rappel frais : l'amorce de Methodology.
    tete = "[METHODOLOGY — your persistent working memory across turns]"
    assert tete not in envoye([])
    assert tete in envoye(outil)
