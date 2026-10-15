# [desc] Schémas des outils multi-agents autres que `Agent` (MessageAgent, SendMessage, CheckAgentResult, ListAgentTasks, ListAgentTypes, Fleet), exposés au modèle. [/desc]
"""Schémas JSON enregistrés par `tools.py`. Le texte est lu par le modèle : toute modification
change son comportement."""
from __future__ import annotations


SCHEMA_MESSAGE_AGENT = {
    "name": "MessageAgent",
    "description": (
        "Envoie une nouvelle instruction à un agent enfant DÉJÀ lancé (même agent, "
        "contexte gardé), identifié par son ticket_id. À utiliser pour ré-orienter ou "
        "compléter la consigne d'un enfant en cours au lieu d'en spawner un nouveau. "
        "S'il travaille, il la lit à sa prochaine étape (après ses outils en cours) ; "
        "`interrompre=true` coupe son tour pour qu'il reparte AUSSITÔT avec (à réserver "
        "à un enfant parti dans une mauvaise direction). Refuse si le ticket est "
        "introuvable. Disponible uniquement en mode bouzeui web."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "ticket_id": {
                "type": "string",
                "description": "Id du ticket de l'agent enfant à ré-instruire.",
            },
            "text": {
                "type": "string",
                "description": "Nouvelle instruction / message à lui transmettre.",
            },
            "interrompre": {
                "type": "boolean",
                "description": ("Vrai = couper son tour en cours pour qu'il reparte "
                                "aussitôt avec ce message. Défaut : lu à sa prochaine étape."),
            },
            "arreter": {
                "type": "boolean",
                "description": ("Vrai = demande d'ARRÊT : il rend son rapport maintenant, "
                                "et plus rien ne le relancera automatiquement ensuite."),
            },
            "question": {
                "type": "integer",
                "description": ("Numéro de la question d'un sous-agent à laquelle `text` "
                                "répond (donné dans le message qui te l'a remontée). Déjà "
                                "répondue par quelqu'un d'autre : rien n'est transmis."),
            },
        },
        "required": ["ticket_id", "text"],
    },
}


SCHEMA_SEND_MESSAGE = {
    "name": "SendMessage",
    "description": (
        "Send a follow-up message to a running background agent. "
        "The message is queued and processed after the agent finishes its current work. "
        "Reference agents by the name set via Agent(name=...) or by task ID."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "to":      {"type": "string", "description": "Agent name or task ID"},
            "message": {"type": "string", "description": "Message to send to the agent"},
        },
        "required": ["to", "message"],
    },
}


SCHEMA_CHECK_AGENT_RESULT = {
    "name": "CheckAgentResult",
    "description": (
        "État d'un de tes enfants (ticket_id ou id de tâche) : en cours, livré, intégré, "
        "branche, worktree. wait=true : attend qu'il rende la main et renvoie son compte "
        "rendu. arreter=true : arrête un enfant LOCAL encore actif (fenêtre de terminal ou "
        "thread)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "ticket_id rendu par Agent"},
            "wait": {"type": "boolean",
                     "description": "Bloquer jusqu'à sa fin (défaut : non)."},
            "arreter": {"type": "boolean",
                        "description": "Arrêter cet enfant local (défaut : non)."},
        },
        "required": ["task_id"],
    },
}


SCHEMA_LIST_AGENT_TASKS = {
    "name": "ListAgentTasks",
    "description": ("Tes enfants (lancés par Agent) et leur état réel : en cours, livré, "
                    "intégré, branche, worktree."),
    "input_schema": {
        "type": "object",
        "properties": {},
    },
}


SCHEMA_LIST_AGENT_TYPES = {
    "name": "ListAgentTypes",
    "description": (
        "List all available agent types (built-in and custom). "
        "Use the type names as subagent_type when calling Agent."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
    },
}


SCHEMA_FLEET = {
    "name": "Fleet",
    "description": (
        "Pilote la flotte d'agents gouvernés SANS shell brut ni HTTP. "
        "action='list' liste tous les agents (id, état, projet, parent). "
        "action='kill' arrête un agent actif (agent_id requis). "
        "Disponible uniquement en mode bouzeui web."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "kill"],
                "description": "'list' pour lister les agents, 'kill' pour en tuer un.",
            },
            "agent_id": {
                "type": "string",
                "description": "Id de l'agent à tuer (requis si action='kill').",
            },
        },
        "required": ["action"],
    },
}
