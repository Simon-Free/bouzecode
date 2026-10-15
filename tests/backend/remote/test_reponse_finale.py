"""--result-file de l'agent headless (reponse.md de l'agent distant) : FinalAnswer, et rien d'autre."""
from bouzecode.ui.reponse_finale import texte_de_reponse


def test_la_reponse_finalanswer_prime_sur_un_dernier_message_vide():
    messages = [{"role": "assistant", "content": "travail en cours"},
                {"role": "assistant", "content": [{"type": "tool_use", "name": "FinalAnswer"}]}]
    assert texte_de_reponse(messages, {"_final_answer": "add(a, b) ajoutee, 1 test vert."}) == \
        "add(a, b) ajoutee, 1 test vert."


def test_sans_finalanswer_la_prose_n_est_jamais_la_reponse():
    """Seul FinalAnswer livre : un dernier texte assistant n'est pas une reponse (plus de repli)."""
    messages = [{"role": "assistant", "content": [{"type": "text", "text": "fait"}]},
                {"role": "user", "content": "ok"},
                {"role": "assistant", "content": "voila, termine"}]
    assert texte_de_reponse(messages, {}) == ""
    assert texte_de_reponse([], {}) == ""


def test_reponse_lue_dans_l_appel_finalanswer_quand_config_n_a_rien():
    """Forme mesuree le 2026-10-06 : dernier assistant au contenu vide, reponse dans tool_calls."""
    messages = [{"role": "user", "content": "dis bonjour"},
                {"role": "assistant", "content": "", "tool_calls": [
                    {"id": "1", "name": "Methodology", "input": {"content": "..."}},
                    {"id": "2", "name": "FinalAnswer", "input": {"answer": "bonjour"}}]},
                {"role": "tool", "name": "FinalAnswer", "content": "Session closing — final answer delivered"}]
    assert texte_de_reponse(messages, {}) == "bonjour"
    format_openai = [{"role": "assistant", "content": None, "tool_calls": [
        {"function": {"name": "FinalAnswer", "arguments": '{"answer": "fait"}'}}]}]
    assert texte_de_reponse(format_openai, {}) == "fait"
