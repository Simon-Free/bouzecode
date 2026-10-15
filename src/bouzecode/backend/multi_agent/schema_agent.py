# [desc] Schéma de l'outil `Agent` exposé au modèle (description et paramètres : background, isolation, branches, projet, doublon assumé). [/desc]
"""Schéma JSON de `Agent`, enregistré par `tools.py`. Le texte est lu par le modèle : toute
modification change son comportement."""
from __future__ import annotations


SCHEMA_AGENT = {
    "name": "Agent",
    "description": (
        "Lance un sous-agent autonome sur une PARTIE fermée de ta mission (types : "
        "ListAgentTypes). Il démarre sans ton contexte : le prompt porte objectif, chemins "
        "absolus, faits mesurés, pièges, critère d'acceptation, hors-périmètre. Il demande "
        "lui-même son worktree ou son venv (Environment) ; donne-lui des fichiers disjoints "
        "de ceux des autres. PARALLÉLISER : N parties indépendantes = N appels Agent dans UN "
        "SEUL message ; ils démarrent TOUS en même temps (écrivant dans le même dépôt : "
        "isolation='worktree'). Récursif : un enfant peut lancer ses propres enfants, "
        "jusqu'à max_agent_depth (défaut 4) ; au-delà l'appel est refusé. Option `background` (défaut "
        "false) : false = tu es en pause jusqu'à ce que TOUS les enfants du message aient "
        "fini, et tu reçois leurs rapports ; true = la main t'est rendue aussitôt, tu "
        "continues ton tour et tu les attends plus tard avec CheckAgentResult(wait=true). "
        "Des Agent répartis sur PLUSIEURS messages sans background=true partent, eux, l'un "
        "après l'autre. Rien d'automatique après sa livraison : pas de test, pas de "
        "merge — tu lis son rapport et tu intègres sa branche."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Task description for the sub-agent",
            },
            "subagent_type": {
                "type": "string",
                "description": "Profil de l'enfant ('general-purpose' par défaut) ; voir ListAgentTypes.",
            },
            "name": {
                "type": "string",
                "description": "Nom lisible, qui le rend adressable pendant qu'il tourne.",
            },
            "model": {
                "type": "string",
                "description": "Model override for this specific agent (optional)",
            },
            "background": {
                "type": "boolean",
                "description": (
                    "false (DÉFAUT) : tu es en pause jusqu'à la fin de l'enfant (et de "
                    "ses frères lancés dans le même message, qui tournent en même temps "
                    "que lui) ; son rapport est le résultat de l'appel. Pour paralléliser "
                    "puis attendre : false, tous les Agent dans le MÊME message. true "
                    "SEULEMENT si tu as autre chose à faire pendant qu'il travaille : la "
                    "main t'est rendue tout de suite ; récupère son rapport avec "
                    "CheckAgentResult(task_id, wait=true) avant de clore. La fin d'un "
                    "enfant ne te réveille JAMAIS (sauf profils manager/monitor) : clore "
                    "ne vaut pas attendre."
                ),
            },
            "wait": {
                "type": "boolean",
                "description": (
                    "Ancien nom, INVERSE de background (wait=false ≡ background=true) ; "
                    "prioritaire s'il est fourni. Préfère background."
                ),
            },
            # `isolation` REVIENT le 2026-10-05, mais décidé sur le BESOIN RÉEL (règle dans
            # la description) : le défaut reste `shared`, jamais un worktree « au cas où ».
            "isolation": {
                "type": "string",
                "enum": ["shared", "worktree", "worktree_venv"],
                "description": (
                    "Environnement de l'enfant, décidé par TOI sur le besoin réel. "
                    "'shared' (DÉFAUT) : ton dossier — lecture, enquête, ou un seul enfant "
                    "qui écrit. 'worktree' : plusieurs enfants écrivent EN PARALLÈLE dans "
                    "le même dépôt (un worktree chacun, sinon ils s'écrasent). "
                    "'worktree_venv' : l'enfant modifie les DÉPENDANCES (pyproject, uv "
                    "sync) — venv dédié, le tien reste intact. Jamais de worktree « au "
                    "cas où » : il coûte un provisionnement."
                ),
            },
            "resume_branch": {
                "type": "string",
                "description": (
                    "Point de départ seulement : le worktree de l'enfant part de cette "
                    "branche, mais il livre sur une branche NEUVE (pour livrer sur X : "
                    "work_branch)."
                ),
            },
            "work_branch": {
                "type": "string",
                "description": (
                    "Branche EXISTANTE où l'enfant commite directement (« mets à jour la "
                    "branche X ») ; l'écrire en prose ne provisionne rien. Refusé si elle "
                    "n'existe pas ou est déjà sortie par un autre worktree."
                ),
            },
            "project_slug": {
                "type": "string",
                "description": (
                    "Vide par défaut : l'enfant hérite de ton projet. À remplir pour un AUTRE "
                    "projet, ou si un dispatch est refusé faute de projet (l'erreur liste "
                    "les slugs)."
                ),
            },
            "doublon_assume": {
                "type": "string",
                "description": (
                    "Vide par défaut. Un brief qui recouvre celui d'un de tes enfants encore "
                    "actif est REFUSÉ ; si c'est vraiment un autre livrable, dis ici en quoi "
                    "il diffère (la raison est écrite sur son ticket)."
                ),
            },
        },
        "required": ["prompt"],
    },
}
