"""Une FinalAnswer LIVRÉE doit rester dans la note — sinon la session qui continue
après elle perd son propre référent.

Constaté en production (session TUI `session_081618_e59985ab.json`, 07/09/2026) : un
agent avait énoncé 4 propositions dans l'argument `answer` de sa FinalAnswer ; le
message user suivant (« Ok pour 1. Pour 2, disons 2 minutes… ») a bien été
auto-appendé dans la note par `append_user_msg_to_methodology`, mais PAS la réponse
à laquelle il répondait. Aucune troncature, aucune compaction n'étaient en cause :
la plateforme persistait la QUESTION du user et jamais la RÉPONSE de l'agent.

Ces tests exercent le chemin RÉEL : le handler du tool `FinalAnswer` tel que le
registre l'appelle, avec le vrai validateur de clôture. Aucun mock, aucun réseau —
les deux cas de refus rendent la main AVANT la porte LLM.
"""

from bouzecode.backend.context_manager.state import METHODOLOGY_NOTE, ContextState
from bouzecode.backend.tools.registration import _final_answer


RECAP_COMPLET = {
    "symptoms": "le bouton ne répond pas",
    "explanation": "l'écouteur manquait",
    "tests": "3 tests pytest verts",
    "changes": [{"file": "src/x.py", "summary": "ajoute l'écouteur"}],
}


class FakeState:
    def __init__(self):
        self.final_answer = None
        self.recap = None
        self.recap_missing = False
        self.taches_terminees = None
        self.taches_restantes = None
        self.taches_declarees = False


def _config(context_state: ContextState) -> dict:
    """Profil de livraison minimal qui ACCEPTE la clôture (cf. tests agent_loop)."""
    return {
        "require_recap": True,
        "recap_expects_object": True,
        "close_validation": True,
        "_depth": 0,
        "model": "",
        "_state": FakeState(),
        "_context_state": context_state,
    }


def test_cloture_acceptee_persiste_la_reponse_dans_la_note():
    gc = ContextState()
    out = _final_answer(
        "1. archiver les cartes  2. délai de 2 minutes  3. remplir les champs serveur",
        _config(gc),
        recap=RECAP_COMPLET,
        taches_terminees="[]",
        taches_restantes="[]",
    )

    assert "Session closing" in out          # clôture acceptée
    note = gc.notes.get(METHODOLOGY_NOTE, "")
    assert "## FinalAnswer @" in note
    #  Le LIBELLÉ exact doit survivre : c'est lui que le message user suivant référence.
    assert "délai de 2 minutes" in note
    assert "3. remplir les champs serveur" in note


def test_answer_vide_ne_touche_pas_la_note():
    gc = ContextState()
    out = _final_answer("   ", _config(gc))

    assert "Error" in out and "empty" in out
    assert gc.notes.get(METHODOLOGY_NOTE, "") == ""


def test_cloture_refusee_ne_persiste_rien():
    #  Une clôture REFUSÉE n'a rien livré à l'utilisateur : la noter polluerait la
    #  note d'une réponse jamais délivrée. L'agent réémettra sa FinalAnswer corrigée.
    gc = ContextState()
    config = _config(gc)
    out = _final_answer("réponse complète", config, RECAP_COMPLET)  # taches_* omises

    assert "CLÔTURE REFUSÉE" in out
    assert config["_final_answer_refused"] is True
    assert gc.notes.get(METHODOLOGY_NOTE, "") == ""


def test_deux_clotures_successives_gardent_les_deux_reponses():
    #  Une session TUI enchaîne plusieurs FinalAnswer (relances user) : chacune doit
    #  rester lisible, pas écraser la précédente.
    gc = ContextState()
    for texte in ("première livraison", "seconde livraison"):
        _final_answer(
            texte,
            _config(gc),
            recap=RECAP_COMPLET,
            taches_terminees="[]",
            taches_restantes="[]",
        )
    note = gc.notes[METHODOLOGY_NOTE]
    assert note.count("## FinalAnswer @") == 2
    assert "première livraison" in note and "seconde livraison" in note
