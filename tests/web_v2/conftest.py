# [desc] Isolation autouse de l'arbre `tests/web_v2/` : mêmes garde-fous que l'arbre `src/`. [/desc]
"""Le SECOND arbre de tests web doit poser les mêmes garde-fous que le premier.

`src/bouzecode/web_v2/tests/conftest.py` redirige, pour CHAQUE test, le store de tickets
(`_persistence.TICKETS_DIR` — la source, pas seulement le ré-export), le parc d'agents
(`runner.AGENTS_DIR` + `purge.TRASH_DIR`), les worktrees et la liste des projets vers un
`tmp_path`. Sans cette garde ici, les tests de `tests/web_v2/` écrivaient dans l'état de
PRODUCTION : `test_tickets_concurrency` comptait 102 tickets au lieu de 12 (les résidus des
exécutions précédentes) et `rehome_agent_cwd` ne retrouvait jamais le ticket que le test
venait de semer, puisque la base SQLite lue restait la vraie.

Les fixtures sont IMPORTÉES plutôt que recopiées : deux copies d'un garde-fou divergent, et
c'est précisément ce que la docstring de `production_isolation` demande d'éviter. Importer
une fixture dans un conftest suffit à l'enregistrer pour tout le répertoire.
"""
from bouzecode.web_v2.tests.conftest import (  # noqa: F401
    _forget_session_caches,
    _isolate_production_state,
)
