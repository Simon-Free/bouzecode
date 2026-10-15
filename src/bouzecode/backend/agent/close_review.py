# [desc] Relecteur indépendant à la clôture (opt-in `close_review`) : un sous-agent à contexte vide teste le résultat comme un utilisateur et rend VERDICT OK/KO. [/desc]
"""Relecture indépendante d'une tâche d'interface, au moment de la clôture.

La porte `close_parcours` prouve que l'agent a JOUÉ des parcours ; elle ne prouve pas
qu'il a joué les bons. Le relecteur, lui, n'a rien écrit : contexte vide, la demande
d'origine et le dossier de travail, les mêmes outils que le codeur. Il reprend le contrat
du validateur de ticket (`services/work/_prompts.build_validator_prompt`) : une dernière
ligne `VERDICT: OK|KO`. Un KO refuse la clôture avec ses retours — le travail revient à
l'agent dans SA session, sans aller-retour humain.

Coût : une session d'agent entière. D'où l'opt-in (`close_review: true` dans la config)
et la limite aux tâches d'interface. Best-effort comme le validateur : un relecteur qui
plante, dépasse son délai ou ne rend pas de verdict ne bloque jamais la clôture.
"""
from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)

MAX_KO = 2  # au-delà, la clôture passe : un relecteur ne doit jamais geler une session
_VERDICT_RE = re.compile(r"VERDICT\s*:\s*(OK|KO)", re.IGNORECASE)
_THINKING_RE = re.compile(r"<thinking>.*?</thinking>", re.DOTALL)


def _prompt(demande: str, cwd: str, answer: str, parcours: object) -> str:
    return (
        "Tu es un RELECTEUR INDÉPENDANT. Tu n'as pas écrit ce travail et tu ne crois rien "
        "sur parole. Teste-le comme un UTILISATEUR : lance l'application, joue dans un vrai "
        "navigateur chaque exigence de la demande (afficher, agir, enregistrer, recharger, "
        "relire) et vérifie que rien ne se perd ni ne s'affiche trop tôt. Ne modifie aucun "
        "fichier du projet (tes scripts de test : Write temp=True).\n\n"
        f"## DEMANDE D'ORIGINE\n{demande[:8000]}\n\n"
        f"## RÉSULTAT À TESTER\nDossier : {cwd}\n\n"
        f"## CE QUE L'AGENT AFFIRME (à vérifier, pas à croire)\n{answer[:4000]}\n"
        f"Parcours déclarés : {str(parcours)[:3000]}\n\n"
        "Termine par la liste des défauts trouvés, chacun avec sa preuve (commande + sortie "
        "observée), puis une ligne contenant EXACTEMENT 'VERDICT: OK' si chaque exigence "
        "fonctionne pour un utilisateur, sinon 'VERDICT: KO'. Émets toujours cette ligne."
    )


def verdict(texte: str) -> str:
    """'OK', 'KO' ou '' : le DERNIER verdict livré, hors raisonnement."""
    trouves = _VERDICT_RE.findall(_THINKING_RE.sub("", texte or ""))
    return trouves[-1].upper() if trouves else ""


def _doit_relire(config: dict) -> bool:
    if not config.get("close_review") or config.get("_depth", 0) != 0:
        return False
    if os.environ.get("BOUZECODE_RUN_KIND", "work") != "work":
        return False
    from .close_parcours import journal, tache_d_interface
    messages = list(getattr(config.get("_state"), "messages", None) or [])
    return tache_d_interface(messages, journal(messages))


def _lancer(prompt: str, config: dict) -> str:
    """Le sous-agent relecteur, en process (même voie que l'outil Agent hors web)."""
    from ..multi_agent.gestionnaire import get_agent_manager
    from ..profiles.discovery import resolve_agent_profile
    from ..core.tool_registry import inherit_private
    # Le point de contrôle de l'hôte (`_tool_gate`, ) suit le relecteur.
    eff = inherit_private(config, {k: v for k, v in config.items() if not k.startswith("_")})
    eff["close_review"] = False
    mgr = get_agent_manager()
    task = mgr.spawn(prompt, eff, config.get("_system_prompt", ""),
                     depth=config.get("_depth", 0),
                     profile=resolve_agent_profile(config.get("close_review_profile", "default")),
                     name="relecteur")
    mgr.wait(task.id, timeout=float(config.get("close_review_timeout", 1200)))
    return str(task.result or "")


def relire(answer: str, config: dict, parcours: object = None) -> tuple[bool, str]:
    """(accepté, retours). KO → refus avec les retours du relecteur ; tout le reste passe."""
    if not _doit_relire(config):
        return True, ""
    kos = int(config.get("_relecture_ko", 0))
    if kos >= MAX_KO:
        return True, ""
    state = config.get("_state")
    from .close_parcours import demande_d_origine
    demande = demande_d_origine(list(getattr(state, "messages", None) or []))
    from ..core.dossier_agent import courant
    cwd = courant()
    try:
        rapport = _lancer(_prompt(demande, cwd, answer, parcours), config)
    except Exception as exc:  # noqa: BLE001 — best-effort : ne jamais bloquer une clôture
        logger.warning("close_review: relecteur en échec (%s) — clôture acceptée", exc)
        return True, ""
    if verdict(rapport) != "KO":
        if not verdict(rapport):
            logger.warning("close_review: aucun verdict rendu — clôture acceptée")
        return True, ""
    config["_relecture_ko"] = kos + 1
    return False, rapport.strip()[-4000:]
