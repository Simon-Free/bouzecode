# [desc] Cycle de vie des process d'agents bouzecode : un module par responsabilité (cf. README). [/desc]
"""Spawn et suivi des agents bouzecode, découpé par responsabilité (cf. README.md).

Paquet SANS ré-export : on importe le module qui PORTE la fonction (`agent_registre.list_agents`,
`agent_fiche.AGENTS_DIR`…) et les tests patchent ce même module — patcher un ré-export ici
n'atteindrait aucun appelant.
"""
