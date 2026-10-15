# [desc] Empreintes du préfixe journalisées à chaque appel (llm_call, side_call) contre les faux serveurs OpenRouter et Anthropic : deux appels identiques → « aucune », un outil ajouté → « tools », une note qui grossit → « note_allongee », un extrait purgé au milieu de la note → « note_reecrite » à la bonne position, un historique réécrit → « messages » ; un message relevé dans la boîte après un lot d'outils allonge l'historique sans casser le préfixe, rappel frais toujours en dernier. [/desc]
"""Un raté de cache vient-il de nous ou du fournisseur ? (essai DeepSeek via DeepInfra : 2 048
tokens lus en cache sur 17 586 contre ≈ 12 000 aux tours voisins, sans moyen de trancher.)

On joue de vrais appels par `dispatch.stream` — conversion, flux, journal — contre les faux
serveurs existants ; seul le transport est remplacé. Les appels passent pour des appels ANNEXES
(copie de la config de la boucle) : ils sont journalisés en `side_call` par dispatch. Le chemin
principal (`llm_call`, journalisé par la boucle) est couvert par une vraie conversation.
"""
from __future__ import annotations

import json
import os

import pytest

from bouzecode.backend.agent.providers.backends import dispatch, openrouter_stream
from bouzecode.backend.agent.state import AgentState
from bouzecode.backend.context_manager import ContextState
from bouzecode.backend.context_manager.methodology import methodology_tool
from tests.e2e_harness import bouzecode


def _outil(nom: str) -> dict:
    return {"name": nom, "description": f"Outil {nom}.",
            "input_schema": {"type": "object", "properties": {"x": {"type": "string"}}}}


OUTILS = [_outil("Bash"), _outil("Read")]
HISTORIQUE = [{"role": "user", "content": "Ajoute add(a, b) dans calc.py."}]


class _Flux:
    ok, status_code, encoding, text = True, 200, "utf-8", ""

    def iter_lines(self, decode_unicode=False):
        chunk = {"provider": "DeepInfra", "choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 10, "completion_tokens": 1}}
        yield "data: " + json.dumps(chunk)
        yield "data: [DONE]"


class _FauxOpenRouter:
    def __init__(self) -> None:
        self.envois: list[dict] = []

    def post(self, url, **kw):
        self.envois.append(kw["json"])
        return _Flux()


@pytest.fixture
def openrouter(monkeypatch):
    serveur = _FauxOpenRouter()
    monkeypatch.setattr(openrouter_stream, "_build_session", lambda: serveur)
    monkeypatch.setenv("OPENROUTER_KEY", "sk-or-test")
    return "deepseek-v4.1-flash", serveur


@pytest.fixture
def anthropic(monkeypatch):
    from tests import cache_conversation_helpers as cch
    from tests.mock_anthropic_server import start_mock_anthropic
    url, app = start_mock_anthropic(["ok"] * 10)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", url)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("BOUZECODE_ANTHROPIC_NATIVE_TOOLS", "1")
    monkeypatch.setattr(cch, "LIVE_API_ALLOWED", True)  # serveur local, pas le gateway
    return "claude-opus-5", app


@pytest.fixture
def anthropic_xml(anthropic, monkeypatch):
    """Protocole XML : les outils voyagent en doc dans le système, après le bloc stable."""
    monkeypatch.setenv("BOUZECODE_ANTHROPIC_NATIVE_TOOLS", "0")
    return anthropic


class _Session:
    """Une session et sa note ; chaque appel est annexe (config copiée de celle de la boucle)."""

    def __init__(self, modele: str) -> None:
        self.state, self.note, self.modele = AgentState(), ContextState(), modele
        methodology_tool({"content": "## Plan\n- [ ] lire calc.py"}, {"_context_state": self.note})

    def appel(self, outils=OUTILS, historique=HISTORIQUE) -> dict:
        config = {"model": self.modele, "_context_state": self.note, "_state": self.state,
                  "_main_config_id": 0, "_call_label": "essai",
                  "anthropic_api_key": os.environ.get("ANTHROPIC_API_KEY", "")}
        list(dispatch.stream(self.modele, "Tu es un agent.", list(historique), outils, config))
        return self.state.compaction_log[-1]

    def noter(self, texte: str) -> None:
        methodology_tool({"content": texte}, {"_context_state": self.note})


@pytest.fixture(params=["openrouter", "anthropic", "anthropic_xml"])
def session(request):
    modele, _serveur = request.getfixturevalue(request.param)
    return _Session(modele)


def test_le_premier_appel_journalise_les_empreintes_sans_reference(session):
    entree = session.appel()
    assert entree["event"] == "side_call"
    prefixe = entree["prefixe"]
    assert set(prefixe["empreintes"]) == {"system", "tools", "note", "messages"}
    assert all(len(h) == 12 for h in prefixe["empreintes"].values())
    assert prefixe["longueurs"]["system"] > 0 and prefixe["longueurs"]["note"] > 0
    assert "prefixe_change" not in entree, "pas d'appel précédent : rien à comparer"


def test_deux_appels_identiques_donnent_aucune(session):
    premier = session.appel()
    second = session.appel()
    assert second["prefixe_change"] == "aucune"
    assert second["prefixe"]["empreintes"] == premier["prefixe"]["empreintes"]


def test_un_outil_ajoute_donne_tools(session):
    session.appel()
    entree = session.appel(outils=OUTILS + [_outil("Grep")])
    assert entree["prefixe_change"] == "tools"


def test_une_note_qui_grossit_est_un_allongement_pur(session):
    """La note grossit à chaque tour : tant que l'ancienne tête cachable reste un préfixe exact
    de la nouvelle, le cache doit tenir — un raté viendrait du fournisseur."""
    session.appel()
    session.noter("- [x] lire calc.py : add manque")
    entree = session.appel()
    assert entree["prefixe_change"] == "note_allongee"
    assert entree["note_allongee"] is True and entree["note_divergence"] is None
    assert "note_extrait" not in entree


SNIPPET = '## snippet: /tmp/x.py L1-2 — "brouillon"\n    1  def add(a, b):\n    2      return a + b'


def _purger_les_extraits(session) -> None:
    """La passe mécanique de compaction des extraits, telle que le harnais la joue."""
    from bouzecode.backend.context_manager.compact_snippets import journaliser, passe_mecanique
    from bouzecode.backend.context_manager.methodology import METHODOLOGY_NOTE
    avant = session.note.notes[METHODOLOGY_NOTE]
    resultat = passe_mecanique(avant)
    assert resultat.change
    session.note.notes[METHODOLOGY_NOTE] = resultat.note
    journaliser({"_state": session.state}, avant, resultat)


def test_un_extrait_purge_au_milieu_de_la_note_est_une_reecriture(session):
    session.noter(SNIPPET)
    session.noter("## Suite\n- [ ] écrire sub")
    avant = session.appel()
    _purger_les_extraits(session)
    entree = session.appel()
    assert entree["prefixe_change"] == "note_reecrite"
    assert entree["note_allongee"] is False
    # L'extrait avant la divergence montre ce qui a été retiré ; l'après, ce qui l'a remplacé.
    assert "## snippet: /tmp/x.py" in entree["note_extrait"]
    assert "snippet-dropped" in entree["note_extrait_nouveau"]
    assert 0 < entree["note_divergence"] < avant["prefixe"]["longueurs"]["note"]
    assert entree["note_perdue"] == avant["prefixe"]["longueurs"]["note"] - entree["note_divergence"]
    assert all(len(entree[k]) <= 62 for k in ("note_extrait", "note_extrait_nouveau"))
    assert not any(isinstance(v, str) and len(v) > 200 for v in entree.values()), \
        "la note n'est jamais journalisée en entier"


def test_la_position_de_la_reecriture_est_celle_du_texte_envoye(openrouter):
    """Sur OpenRouter, la note part en premier message user : la position journalisée est celle
    du premier caractère qui diffère entre les deux notes réellement envoyées."""
    modele, serveur = openrouter
    session = _Session(modele)
    session.noter(SNIPPET)
    session.noter("## Suite\n- [ ] écrire sub")
    session.appel()
    _purger_les_extraits(session)
    entree = session.appel()
    ancienne, nouvelle = (e["messages"][1]["content"] for e in serveur.envois[-2:])
    attendu = ancienne.index("## snippet: /tmp/x.py") + len("## snippet")
    assert entree["note_divergence"] == attendu
    assert ancienne[:attendu] == nouvelle[:attendu] and ancienne[attendu] != nouvelle[attendu]


def test_la_note_envoyee_a_openrouter_est_celle_de_l_empreinte(openrouter):
    """Note et delta partent bout à bout : l'empreinte porte sur ce texte-là, pas sur une autre
    jointure — sinon chaque tour passerait pour une réécriture."""
    from bouzecode.backend.agent.providers.backends.empreinte import _court
    modele, serveur = openrouter
    session = _Session(modele)
    session.appel()
    session.noter("- [x] lire calc.py : add manque")
    entree = session.appel()
    # La note : l'enveloppe <working_notes> en tête du premier message user (2026-10-07).
    premier = serveur.envois[-1]["messages"][1]["content"]
    note = premier[:premier.index("</working_notes>\n\n") + len("</working_notes>\n\n")]
    assert entree["prefixe"]["empreintes"]["note"] == _court(note)
    assert entree["prefixe_change"] == "note_allongee"


def test_un_historique_reecrit_donne_sa_position(session):
    session.appel()
    suite = HISTORIQUE + [{"role": "assistant", "content": "Je lis."},
                          {"role": "user", "content": "Continue."}]
    entree = session.appel(historique=suite)
    assert entree["messages_allonges"] is True and entree["messages_divergence"] is None
    reecrit = [{"role": "user", "content": "Ajoute sub(a, b)."}] + suite[1:]
    entree = session.appel(historique=reecrit)
    assert entree["messages_allonges"] is False
    assert entree["messages_divergence_message"] == 0
    assert "Ajoute add" in entree["messages_extrait"]


def test_apres_une_reprise_sans_memoire_la_note_reste_note(openrouter):
    """Session reprise : le journal a l'appel précédent mais pas ses textes → ancienne valeur."""
    modele, _ = openrouter
    session = _Session(modele)
    session.appel()
    del session.state._prefixes_precedents
    session.noter("- [x] lire calc.py : add manque")
    entree = session.appel()
    assert entree["prefixe_change"] == "note"
    assert "note_allongee" not in entree


def test_un_historique_qui_s_allonge_garde_le_prefixe_mais_une_reecriture_le_casse(session):
    session.appel()
    suite = HISTORIQUE + [{"role": "assistant", "content": "Je lis."},
                          {"role": "user", "content": "Continue."}]
    assert session.appel(historique=suite)["prefixe_change"] == "aucune"
    reecrit = [{"role": "user", "content": "Ajoute sub(a, b)."}] + suite[1:] + [
        {"role": "assistant", "content": "Bien."}, {"role": "user", "content": "Et ensuite ?"}]
    assert session.appel(historique=reecrit)["prefixe_change"] == "messages"


def test_le_systeme_envoye_a_openrouter_est_celui_de_l_empreinte(openrouter):
    """L'empreinte « system » porte sur le message système tel qu'il part sur le fil."""
    from bouzecode.backend.agent.providers.backends.empreinte import _court
    modele, serveur = openrouter
    entree = _Session(modele).appel()
    envoye = serveur.envois[-1]
    assert entree["prefixe"]["empreintes"]["system"] == _court(envoye["messages"][0]["content"])
    assert entree["prefixe"]["longueurs"]["system"] == len(envoye["messages"][0]["content"])
    assert entree["provider"] == "DeepInfra"


def test_les_appels_annexes_de_libelles_differents_ne_se_comparent_pas(openrouter):
    modele, _ = openrouter
    session = _Session(modele)
    session.appel()
    config = {"model": modele, "_context_state": session.note, "_state": session.state,
              "_main_config_id": 0, "_call_label": "compaction"}
    list(dispatch.stream(modele, "Compacte la note.", HISTORIQUE, [], config))
    assert "prefixe_change" not in session.state.compaction_log[-1]


def test_les_appels_principaux_journalisent_l_empreinte_et_la_comparent(monkeypatch):
    """Vraie conversation contre le faux serveur Anthropic : chaque `llm_call` porte ses
    empreintes. Au second tour, système et outils sont intacts ; la note, elle, a reçu le
    nouveau message utilisateur (« ## User @… ») à sa fin : elle est seulement allongée."""
    monkeypatch.setenv("BOUZECODE_ANTHROPIC_NATIVE_TOOLS", "1")
    result = bouzecode(["Ajoute add(a, b) dans calc.py.", "Ajoute aussi sub(a, b)."],
                       mock_api=["Noté.", "Noté aussi."],
                       config_overrides={"model": "claude-opus-5", "enforce_tests": False})
    appels = [e for e in result.state.compaction_log if e.get("event") == "llm_call"]
    assert len(appels) == 2
    assert all(len(a["prefixe"]["empreintes"]["tools"]) == 12 for a in appels)
    assert appels[0]["prefixe"]["ordre"][0] == "tools", "Anthropic lit les outils natifs en tête"
    assert "prefixe_change" not in appels[0]
    avant, apres = (a["prefixe"]["empreintes"] for a in appels)
    assert (avant["system"], avant["tools"]) == (apres["system"], apres["tools"])
    assert appels[1]["prefixe_change"] == "note_allongee"


#  Un message relevé dans la boîte de l'agent (`loop.relever_courrier`) entre APRÈS les résultats
#  du lot d'outils, comme un message user. Il allonge l'historique sans rien réécrire : le préfixe
#  caché tient, et il ferme le payload.
LOT = [{"role": "assistant", "content": "Je lis.",
        "tool_calls": [{"id": "t1", "name": "Read", "input": {"x": "calc.py"}}]},
       {"role": "tool", "tool_call_id": "t1", "name": "Read", "content": "def sub(a, b): ..."}]
COURRIER = {"role": "user", "content": "[Précision de l'utilisateur] Appelle-la plutôt somme()."}


def test_un_message_releve_apres_le_lot_d_outils_garde_le_prefixe(session):
    session.appel(historique=HISTORIQUE + LOT)
    entree = session.appel(historique=HISTORIQUE + LOT + [COURRIER])
    assert entree["prefixe_change"] == "aucune"


def test_un_message_insere_dans_l_historique_deja_envoye_donne_messages(session):
    """Le contre-exemple : glisser le courrier DANS l'historique déjà envoyé le réécrit."""
    session.appel(historique=HISTORIQUE + LOT)
    entree = session.appel(historique=HISTORIQUE + [COURRIER] + LOT)
    assert entree["prefixe_change"] == "messages"


def test_openrouter_note_en_tete_courrier_apres_les_outils_a_la_toute_fin(openrouter):
    modele, serveur = openrouter
    _Session(modele).appel(historique=HISTORIQUE + LOT + [COURRIER])
    fil = serveur.envois[-1]["messages"]
    # 2026-10-07 : note en tête de la demande (<working_notes>), contexte de session à part,
    # consignes du harnais (<harness_notes>) juste après les résultats, avant le courrier.
    assert [m["role"] for m in fil] == ["system", "user", "user", "assistant", "tool", "user", "user"]
    assert fil[1]["content"].startswith("<working_notes>") and "lire calc.py" in fil[1]["content"]
    assert fil[-2]["content"].startswith("<harness_notes>")
    assert fil[-1]["content"].endswith(COURRIER["content"]), "le courrier ferme le payload"
    assert "[RAPPEL — à chaque tour]" not in json.dumps(fil, ensure_ascii=False)


def test_conversation_avec_courrier_releve_ne_casse_ni_systeme_ni_outils(monkeypatch):
    """Vraie boucle contre le faux serveur Anthropic (outils XML exécutés) : l'utilisateur écrit
    pendant le 1er lot d'outils ; le courrier arrive au 2e appel, système et outils intacts."""
    monkeypatch.setenv("BOUZECODE_ANTHROPIC_NATIVE_TOOLS", "0")
    lot = ('<tool_use name="Methodology" id="m{n}"><param name="content">note {n}</param></tool_use>\n'
           '<tool_use name="Bash" id="b{n}"><param name="command">echo {n}</param></tool_use>')
    boite = ["Appelle le fichier FINAL.md."]

    def relever():
        lus = list(boite)
        boite.clear()
        return lus

    result = bouzecode(["Écris un fichier."], mock_api=[lot.format(n=1), lot.format(n=2), "Fini."],
                       config_overrides={"model": "claude-opus-5", "enforce_tests": False,
                                         "_inbox_pop": relever})
    appels = [e for e in result.state.compaction_log if e.get("event") == "llm_call"]
    assert len(appels) >= 2
    changes = [a.get("prefixe_change") for a in appels[1:]]
    assert not {"system", "tools"} & set(changes), changes
    empreintes = [a["prefixe"]["empreintes"] for a in appels]
    assert len({(e["system"], e["tools"]) for e in empreintes}) == 1
    courrier = next(i for i, m in enumerate(result.messages)
                    if m["role"] == "user" and "FINAL.md" in str(m.get("content")))
    assert result.messages[courrier - 1]["role"] == "tool"
    # Sur le fil : l'appel qui porte le courrier reprend À L'IDENTIQUE tout ce que l'appel
    # précédent avait envoyé (hors son dernier message, porteur des injections du tour).
    avant, apres = (r["messages"] for r in result.recorded_requests[0:2])
    assert "FINAL.md" in json.dumps(apres[-1]) and "FINAL.md" not in json.dumps(avant)
    assert apres[:len(avant) - 1] == avant[:-1]
    assert "[RAPPEL — à chaque tour]" not in json.dumps(apres[-1], ensure_ascii=False)
    assert (result.recorded_requests[0]["system"][:2], result.recorded_requests[0].get("tools")) \
        == (result.recorded_requests[1]["system"][:2], result.recorded_requests[1].get("tools"))
