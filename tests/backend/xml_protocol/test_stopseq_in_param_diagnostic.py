
"""Le diagnostic doit NOMMER la stop-sequence quand elle est avalee dans un param.

Chaine causale reproduite ici : le litteral de fermeture du wrapper de batch est
envoye a l'API comme stop sequence (anthropic_stream / openrouter_stream). Si le
modele l'ecrit LITTERALEMENT dans un corps de <param> (typiquement une note qui
cite le protocole), le provider coupe la generation a cet endroit : le param n'est
jamais ferme et tous les tool calls suivants du batch -- FinalAnswer inclus --
n'existent jamais. Le modele recommence alors la meme erreur jusqu'a epuiser les
budgets de relance, et la session sort par final_answer_never_called /
empty_completion : "pas de FinalAnswer et pourtant le programme s'arrete".

Le diagnostic actuel dit seulement "param is never closed", ce qui n'apprend rien
au modele sur la cause -- donc il recidive. On exige ici que la cause soit nommee.

Le litteral est construit par concatenation A DESSEIN : ecrit en entier dans ce
fichier, il couperait la generation de l'agent qui ecrit le test.
"""

from bouzecode.backend.xml_tool_protocol.recovery import describe_unclosed_tail

WRAPPER_CLOSE = "</" + "tool_calls>"


def _truncated_batch() -> str:
    """Ce que le harness recoit quand la stop sequence tombe dans un param."""
    return (
        '<tool_use name="Methodology" id="m1">'
        '<param name="content">Le tag ' + WRAPPER_CLOSE
    )


def test_diagnostic_names_the_param_left_open():
    """Acquis a preserver : le param fautif est nomme."""
    assert 'name="content"' in describe_unclosed_tail(_truncated_batch())


def test_diagnostic_names_the_stop_sequence_as_the_cause():
    """Le modele doit apprendre POURQUOI le flux s'est arrete la."""
    msg = describe_unclosed_tail(_truncated_batch())
    assert "stop sequence" in msg.lower(), msg


def test_diagnostic_gives_the_actionable_remedy():
    """Nommer la cause sans donner le remede ne corrige pas la recidive."""
    assert "CDATA" in describe_unclosed_tail(_truncated_batch())


def test_ordinary_unclosed_param_is_not_blamed_on_the_stop_sequence():
    """Pas de faux positif : un param tronque sans le tag garde l'ancien message."""
    msg = describe_unclosed_tail(
        '<tool_use name="Edit" id="e1"><param name="old_string">value = None'
    )
    assert "stop sequence" not in msg.lower(), msg
