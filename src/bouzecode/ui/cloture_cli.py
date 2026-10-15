# [desc] Fin d'un run non interactif (-p) : code de sortie selon la raison de clôture (0 = FinalAnswer et rien d'autre), réponse FinalAnswer dans `--result-file`, fiche `<result-file>.cloture.json` pour qui lance l'agent sans lire sa session. [/desc]
"""Règle : FinalAnswer est le SEUL acte terminal qui livre. Un run non interactif relance le
modèle tant qu'il répond en prose (`close_requires_final_answer`, même plafond que le web) puis
clôt en `final_answer_never_called` ; une réponse en prose n'est jamais une livraison.

Codes de sortie (le classement vient de `web_v2.close_reasons`, la seule table qui décide) :

* 0 — `EXIT_LIVRE` : clôture par FinalAnswer (`proves_delivery`), et rien d'autre ;
* 1 — exception non rattrapée (erreur fournisseur fatale…), inchangé ;
* 3 — `EXIT_REFUS_MODELE` : le filtre de contenu a bloqué un tour malgré les relances du
  backend ; blocage aléatoire : relancer, puis changer de modèle s'il se répète ;
* 4 — `EXIT_FIN_FORCEE` : fin sans livraison — la boucle a coupé (FinalAnswer jamais appelé,
  plafond de tours, complétion vide…) ou le modèle a fini en prose (`text_no_tools`) ;
* 5 — `EXIT_MORT_EN_VOL` : arrêt non maîtrisé nommé (annulation, flux muet…), raison inconnue
  ou absente.

`--result-file X` (et `--plan-output`) reçoit le texte de FinalAnswer, et SEULEMENT si le run a
livré : jamais de repli sur la prose. La fiche `X` sans suffixe + `.cloture.json`
(`reponse.md` → `reponse.cloture.json`) porte `close_reason`, `close_detail`, `final_answer` et
`code_sortie`, qu'il y ait une réponse ou non ; elle est écrite APRÈS la réponse, si bien que
qui attend le run peut guetter la fiche. Le mode agent web (`--web-agent-dir`) n'est pas
concerné : le serveur lit la clôture dans la session et l'IPC.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..web_v2 import close_reasons
from .reponse_finale import texte_de_reponse

EXIT_LIVRE = 0
EXIT_REFUS_MODELE = 3
EXIT_FIN_FORCEE = 4
EXIT_MORT_EN_VOL = 5
REFUS_MODELE = "content_refusal"
SUFFIXE_FICHE = ".cloture.json"


def code_de_sortie(close_reason: str) -> int:
    if close_reasons.proves_delivery(close_reason):
        return EXIT_LIVRE
    if close_reason == REFUS_MODELE:
        return EXIT_REFUS_MODELE
    if close_reasons.is_controlled(close_reason):
        return EXIT_FIN_FORCEE
    return EXIT_MORT_EN_VOL


def chemin_fiche(result_file: str | Path) -> Path:
    chemin = Path(result_file)
    return chemin.with_name(chemin.stem + SUFFIXE_FICHE)


def _ecrire_reponse(state, config: dict) -> None:
    reponse = texte_de_reponse(state.messages, config)
    for cle in ("_plan_output", "_result_file"):
        if reponse and config.get(cle):
            Path(config[cle]).write_text(reponse, encoding="utf-8")


def conclure(state, config: dict) -> int:
    """Écrit la réponse FinalAnswer (run livré seulement) puis la fiche de clôture (si
    `--result-file`), et rend le code de sortie du run."""
    close_reason = str(getattr(state, "close_reason", "") or "")
    code = code_de_sortie(close_reason)
    if code == EXIT_LIVRE:
        _ecrire_reponse(state, config)
    result_file = config.get("_result_file")
    if result_file:
        fiche = {"close_reason": close_reason,
                 "close_detail": str(getattr(state, "close_detail", "") or ""),
                 "final_answer": code == EXIT_LIVRE,
                 "code_sortie": code}
        chemin_fiche(result_file).write_text(json.dumps(fiche, ensure_ascii=False, indent=2),
                                             encoding="utf-8")
    return code
