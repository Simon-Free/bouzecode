"""L'outil `FinalAnswer` TEL QUE LE REGISTRE L'APPELLE transmet `taches_terminees` et
`taches_restantes` au handler.

Régression trouvée le 2026-09-23 en bac à sable : la lambda d'enregistrement ne passait que
`answer` et `recap`. Le validateur voyait donc les deux champs obligatoires ABSENTS même quand
le modèle les fournissait — toute clôture d'un profil `require_recap` était refusée, et le
reste-à-faire déclaré n'atteignait jamais le Bureau. Le test passe par le ToolDef enregistré,
pas par `_final_answer` : c'est la couture elle-même qui était cassée.
"""
from bouzecode.backend.core.tool_registry import get_tool
from bouzecode.backend.tools import registration


def _outil():
    registration._register_builtins()
    outil = get_tool("FinalAnswer")
    assert outil is not None
    return outil


def test_les_deux_listes_atteignent_le_validateur():
    config = {"require_recap": True, "recap_coding": False, "_depth": 0, "model": ""}
    rendu = _outil().func({
        "answer": "réponse complète",
        "recap": {"symptoms": "le bouton ne répond pas", "explanation": "écouteur manquant"},
        "taches_terminees": ["j'ai corrigé le bouton"],
        #  Item volontairement incomplet (pas de titre) : le refus s'arrête AVANT la
        #  porte LLM et nomme CE défaut — donc les listes lui sont bien parvenues.
        "taches_restantes": [{"corps": "câbler l'onglet"}],
    }, config)
    assert "taches_restantes[0].titre" in rendu
    assert "taches_terminees" not in rendu.replace("taches_restantes", "")


def test_omettre_les_listes_reste_refuse():
    config = {"require_recap": True, "recap_coding": False, "_depth": 0, "model": ""}
    rendu = _outil().func({"answer": "réponse", "recap": {"symptoms": "s", "explanation": "e"}},
                          config)
    assert "taches_terminees" in rendu and "taches_restantes" in rendu
