# [desc] Tests that a message to the main agent interrupts its wait on a child agent, which keeps running. [/desc]
from __future__ import annotations

import threading

from bouzecode.backend.multi_agent import outil_agent, outils_enfants
from bouzecode.backend.multi_agent.en_process.fiche import PRINCIPAL

from tests.backend.multi_agent.test_en_process_execution import tui  # noqa: F401  (fixture)


def test_un_message_a_main_interrompt_son_attente_et_l_enfant_continue(tui):  # noqa: F811
    registre, config = tui
    resultat: list[str] = []
    fil = threading.Thread(target=lambda: resultat.append(
        outil_agent._agent_tool({"prompt": "courrier", "name": "c"}, config)), daemon=True)
    fil.start()
    for _ in range(100):
        if registre.sous_agents() and registre.sous_agents()[0].actif:
            break
        registre.attendre_changement(0.05)
    enfant = registre.sous_agents()[0]

    assert "mis en file" in registre.envoyer(PRINCIPAL, "on change de plan")
    fil.join(5)

    assert not fil.is_alive(), "main reste bloque sur son enfant malgre le message"
    assert "Attente INTERROMPUE" in resultat[0] and enfant.id in resultat[0]
    assert enfant.actif  # l'enfant n'est pas tue
    assert config["_bg_agent_launched"] is True
    assert registre.relever(PRINCIPAL) == ["on change de plan"]  # courrier intact pour main
    registre.envoyer(enfant.id, "fin")
    verdict = outils_enfants._check_agent_result({"task_id": enfant.id, "wait": True}, config)
    assert "lu : fin" in verdict
