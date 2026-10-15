# [desc] Test de non-régression prouvant que le bootstrap prod enregistre les 8 outils du profil bureau-assistant [/desc]
from __future__ import annotations

import importlib

from bouzecode.backend.core.tool_registry import get_tool, unregister_tool
from bouzecode.backend.tools import registration

#  Les outils declares par le profil builtin bureau-assistant.yaml.
#  `Mails` et `Teams` (lecture Outlook / Teams via MS Graph) sont dans cette liste pour la
#  meme raison que les autres : l'assistant est lance avec un prompt qui les NOMME. Un tool
#  nomme mais absent du registry = un assistant qui promet de lire les mails et ne peut pas.
NOMS_BUREAU = ["ResteAFaire", "Taches", "Chantiers", "Decisions", "Flotte", "LancerAgent",
               "Mails", "Teams"]


def _rejouer_le_bootstrap() -> None:
    """Repart d'un registry SANS les outils du Bureau, puis rejoue le bootstrap.

    Necessaire car d'autres tests appellent `bureau_tools.register()` directement :
    sans ce nettoyage, le test passerait par accident selon l'ordre d'execution
    (pytest-xdist) au lieu de prouver que la PROD les enregistre.
    """
    for nom in NOMS_BUREAU:
        unregister_tool(nom)
    for nom in NOMS_BUREAU:
        assert get_tool(nom) is None, f"{nom} devrait avoir ete retire du registry"
    importlib.reload(registration)


def test_le_bootstrap_des_outils_enregistre_les_outils_du_bureau():
    """Sans ca, l'assistant du Bureau est lance avec un prompt qui nomme des outils
    que le runtime ne connait pas : il ne peut rien faire."""
    _rejouer_le_bootstrap()

    manquants = [nom for nom in NOMS_BUREAU if get_tool(nom) is None]
    assert manquants == [], f"outils absents du registry apres bootstrap : {manquants}"


def test_le_profil_bureau_assistant_voit_tous_ses_outils_et_pas_de_quoi_coder():
    _rejouer_le_bootstrap()

    autorises = registration.enabled_tools_for_profile("bureau-assistant")

    assert set(NOMS_BUREAU) <= autorises, (
        "le profil ne voit pas ses outils : " + str(sorted(set(NOMS_BUREAU) - autorises))
    )
    interdits = {"Edit", "Write", "Bash"} & autorises
    assert not interdits, f"l'assistant ne doit pas pouvoir coder, or il a : {interdits}"
