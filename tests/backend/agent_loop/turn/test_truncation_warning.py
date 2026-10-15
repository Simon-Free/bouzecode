"""L'avertissement de troncature doit nommer l'appel tronque.

Bug vecu : un tour d'agent de 2,8K tokens de sortie a recu
`stop_reason=max_tokens (out_tokens=4096, cap=4096) — Raise config['max_tokens']`.
Le tour n'avait rien de tronque : c'est la compaction de la note (un side-call qui
ecrase `config["max_tokens"]` juste avant d'appeler) qui avait ete coupee. Le
conseil « relevez config['max_tokens'] » etait donc faux, et le message envoyait
l'utilisateur chercher un plafond de 4096 qui n'existe nulle part dans sa config.
"""

from bouzecode.backend.agent.providers.backends.anthropic_stream import (
    _truncation_message,
)


def test_un_tour_d_agent_tronque_conseille_de_relever_la_config():
    """Chemin normal : le budget VIENT de la config, le conseil est valable."""
    message = _truncation_message(64000, 64000, {"_depth": 0, "max_tokens": 64000})

    assert "Raise config['max_tokens']" in message
    assert "side-call" not in message


def test_un_side_call_tronque_se_nomme_et_dedouane_le_tour_d_agent():
    """Le message doit dire QUI a ete coupe et que la config n'y changera rien."""
    config = {"_depth": 1, "max_tokens": 4096,
              "_call_label": "note prose compaction"}

    message = _truncation_message(4096, 4096, config)

    assert "note prose compaction" in message
    assert "will NOT help" in message
    assert "agent turn itself was not cut" in message
    assert "Raise config['max_tokens'] to let it finish" not in message


def test_un_side_call_sans_etiquette_est_quand_meme_reconnu():
    """`_depth > 0` suffit a savoir qu'on n'est pas dans le tour de l'agent."""
    message = _truncation_message(1024, 1024, {"_depth": 2, "max_tokens": 1024})

    assert "side-call" in message
    assert "will NOT help" in message
