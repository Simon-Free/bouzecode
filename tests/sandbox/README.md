# Bac à sable BouzéqUI v2 (faux LLM)

Lance le vrai serveur `web_v2` et de **vrais agents** (`python -m bouzecode`) dont le modèle est
un **faux LLM** local, dans un HOME jetable. Aucun appel à l'API réelle, aucune écriture dans le
vrai `~/.bouzecode`.

```bash
tests/sandbox/run_sandbox.sh start --fresh --seed   # HOME neuf + données (~40 s avec --test)
tests/sandbox/run_sandbox.sh start                  # idempotent : ne relance que ce qui est arrêté
tests/sandbox/run_sandbox.sh status
tests/sandbox/run_sandbox.sh stop                   # serveur + agents du bac à sable + faux LLM
```

**Windows** (ni `env -i`, ni `pgrep`) : `tests/sandbox/run_sandbox.py start|stop|status|seed`,
mêmes options et variables (ports par défaut 5156 / 5199, HOME `%TEMP%\bz-sandbox`), lancé avec
le Python du venv. HOME **et** USERPROFILE sont isolés (`Path.home()` lit USERPROFILE). Les
deux lanceurs écrivent `~/.bouzecode/config.json` (`claude-opus-5`, `BZ_SANDBOX_MODEL`) : le
modèle par défaut du code est servi par le gateway préprod, la garde d'environnement refuserait
tout lancement.

- UI : http://127.0.0.1:5056 · faux LLM : http://127.0.0.1:5099 (`/health`, `/log`, `/last`)
- HOME : `/tmp/bz-sandbox` (`BZ_SANDBOX_HOME`) · logs : `$HOME/.run/{web,mock_llm}.log`
- Réglages : `MOCK_LLM_LATENCY` (0.8 s avant le 1er token), `MOCK_LLM_CHUNK_DELAY`, `MOCK_LLM_SLOW_DELAY`

**Ports libres** (`BZ_UI_PORT`, `MOCK_LLM_PORT`) : `backend/multi_agent/client_tickets.py` lit désormais
`BOUZECODE_WEB_BASE_URL` ; un manager lance ses sous-agents quel que soit le port.

**Python** : toujours `.venv/bin/python`, jamais `uv run`/`uv sync` (l'index uv pointe sur
l'Artifactory corporate, injoignable).

## Instantané du seed et mode test

```bash
tests/sandbox/run_sandbox.sh start --snapshot --test   # HOME seedé en ~1,5 s (instantané)
tests/sandbox/run_sandbox.sh start --reseed --test     # force un seed complet + nouvel instantané
```

- `--snapshot` restaure `~/.cache/bz-sandbox/seed-<empreinte>.tar.zst` (`BZ_SNAPSHOT_DIR`) :
  0,2 s d'extraction + ~1 s de démarrage du serveur. Sans archive valide, il joue le seed
  complet (~40 s en mode test), attend que **plus aucun agent ne travaille**, arrête tout
  (aucun processus d'agent dans l'archive : jamais d'« en cours » fantôme), archive, redémarre.
- **Empreinte** (`snapshot.py`, liste `EMPREINTE`) : `seed.py`, `mock_llm_server.py`,
  `run_sandbox.sh`, `snapshot.py`, et les modules qui écrivent le format sur disque (session
  d'agent, `runner`/`ipc`, `sessions/store.py`, schémas SQLite `_persistence`, `micros`,
  `tasks`, `decisions`, `bureau_meta`). Elle est calculée AVANT le seed : un code modifié
  pendant le seed donne un re-seed au run suivant. `BZ_SNAPSHOT_LOOSE=1` réduit l'empreinte
  aux fichiers du bac à sable (utile pendant une refacto, au risque de rater un changement
  de format).
- **Restauration dans un autre HOME** : l'archive mémorise son HOME d'origine ; chaque
  occurrence est réécrite (fichiers texte en octets — sessions, `projects.json`, `.git` /
  `gitdir` des worktrees — et colonnes TEXT des bases SQLite ; journaux `-wal/-shm` jamais
  touchés). Vérifié : worktrees git valides, question en attente à laquelle on répond, zéro
  erreur console.
- **Mode test** (`--test` ou `BZ_E2E=1`) : faux LLM avec `MOCK_LLM_LATENCY=0` et
  `MOCK_LLM_CHUNK_DELAY=0` (sauf valeur explicite). `[scn:slow]` et `[scn:hang]` gardent leurs
  propres délais : ce sont eux qui testent le streaming et les phases d'attente. Sans
  `--test`, délais réalistes pour la démo.

## Rejouer seulement ce qui a changé

`scripts/test_changed.sh [--ref REF] [--all] [--no-e2e]` enchaîne `vitest --changed`,
`pytest --testmon` (Flask + backend) et les tests de bout en bout avec `--only-changed --ff`,
sur un bac à sable restauré par page (ports 5556-5558 / 5599-5597, `/tmp/bz-sb-changed-*`).
Un fichier de bout en bout déclare ce qu'il couvre :
`pytestmark = pytest.mark.couvre("static/js/bureau/**", "routes/work/micros/**")` (globs
relatifs à `src/bouzecode/web_v2/`, ou à la racine s'ils commencent par `src/`, `tests/`,
`scripts/` ou `/`). Détails : `src/bouzecode/web_v2/tests/pytest_only_changed.py`.

## Piloter le faux LLM : `[scn:<nom>]` dans le prompt

Mettez le tag **en 2ᵉ ligne** : le titre du ticket est la 1ʳᵉ ligne du prompt.

| Tag | Comportement | État final attendu |
|---|---|---|
| *(aucun)* / `reply` | une phrase + FinalAnswer | terminé (livré) |
| `slow` | prose streamée lentement (~30 s) | en cours → terminé |
| `long` | rapport markdown très long (titres, code, tableaux) | terminé |
| `question` | `AskUserQuestion` à 2 options, conclut après la réponse | à répondre → terminé |
| `plan` | `WritePlan` avec validation requise | plan à valider → terminé |
| `tools` | Bash + Glob, Read, Snippet + Write `NOTES.md`, commit git | terminé, commit sur la branche |
| `subagents` | lance 2 sous-agents (`slow`, `question`) via `Agent`, clôt, se réveille quand ils finissent | manager chaud / orchestre |
| `recap` | FinalAnswer avec récap complet + 2 tâches restantes (dont une décision) | terminé + pastille Récap |
| `crash` | HTTP 400 non retentable | planté |
| `error429` | deux 429 puis réponse normale | terminé (après retries) |
| `error500` | 500 persistant (l'agent réessaie ~10 fois avec backoff) | planté au bout de plusieurs minutes |
| `hang` | premier token après 45 s | « le modèle lit votre demande… » puis terminé |
| `overflow` | réflexion interminable sans outil → coupée, résumée par un appel annexe, puis conclut | terminé ; `/costs` : 1 appel annexe, sortie du tour coupé estimée |
| `nometh` | lot sans Methodology → rattrapage forcé par un appel annexe | terminé ; `/costs` : 1 appel annexe |
| `reflexion-tours` | trois tours enchaînés (réflexion streamée + `Bash` court), puis conclut | terminé ; les tours s'empilent dans le fil |
| `question-reflexion` | `AskUserQuestion`, puis après la réponse les mêmes trois tours (reprise CHAUDE) | à répondre → terminé ; tours empilés (TODO §3) |
| `lot-pause` | deux `Agent` (enfants `etapes`) dans UN message, SANS `background` : le parent attend | les deux enfants naissent ensemble (TODO §4), puis terminé |
| `bureau-tache` | *(assistant)* `Taches(creer)` | ligne ajoutée au Bureau |
| `bureau-chantier` | *(assistant)* `Chantiers(creer)` | chantier ajouté |
| `bureau-lancer` | *(assistant)* `LancerAgent` | ⚠ échoue : bug d'import en prod (voir plus bas) |
| `bureau-flotte` | *(assistant)* `Flotte` + `ResteAFaire` | réponse texte |
| `bureau-lancer-question` | *(assistant)* `LancerAgent` d'une tâche `question` | l'assistant est réveillé avec la question de la tâche (TODO §6) |
| `manager-worktree` | *(composé)* worktree, spec non commitée, 2 sous-agents (`enfant-commit` : worktree + commit + intégration), rend la main, **réveillé** par le serveur : bilan, commit, intégration, FinalAnswer | tâche À relire, `enfant_a.md` + `enfant_b.md` dans la base |
| `manager-worktree-crash` | *(composé)* idem, mais l'enfant B plante (`crash`) | un enfant « Arrêté sans finir », le manager conclut au réveil |
| `enfant-commit` | sous-agent : worktree, écrit+commite le fichier nommé `Fichier : x.md` du prompt, intègre, FinalAnswer | livré |
| `relance-apres-final` | à mettre dans un **retour** à un agent déjà conclu (relance « même agent ») : 4 tours dont deux `sleep 3`, commit de `RETOUR.md` | En cours puis À relire |
| `integre-soi-meme` | à lancer en isolation `worktree` : demande « Puis-je intégrer ma branche ? », puis commite `LIVRE.md` et intègre LUI-MÊME sa branche (`Environment integrate`) | Attend ta réponse puis À relire (branche intégrée) |

Une relance sans tag (« et après ? ») reçoit la réponse par défaut. Un tag dans la relance
rejoue ce scénario (utile pour l'assistant du Bureau : « Crée une tâche [scn:bureau-tache] »).

**Usage déterministe (vérité terrain des compteurs)** : chaque réponse porte un `usage` calculé
depuis la requête (1 token = 4 caractères du JSON envoyé, cache simulé sur les `cache_control`,
sortie = ⌈texte/4⌉), journalisé par appel sur `GET /usage_log`. `MOCK_LLM_USAGE_SEMANTICS=gateway`
(défaut : input inclut l'écriture de cache, comme le gateway) ou `anthropic` (sémantique officielle ;
le script pose alors `BOUZECODE_USAGE_INPUT_INCLUDES_CACHE_WRITE=0` côté serveur). Voir
`docs/refonte_ui/tokens_audit.md`.

**Fonctionnement** : le faux LLM est sans état. Il lit le scénario dans les énoncés
utilisateur, que le harnais range dans la note Methodology (`## User @…`, bloc system, et non
dans `messages`). Il lit l'étape dans des marqueurs `⟦mock uN sK⟧` qu'il écrit lui-même dans
sa Methodology. Les `tool_result` d'un lot disparaissent du fil au tour suivant : on ne peut
donc pas s'y fier. Plusieurs agents concurrents sont servis sans interférence.

## Ce que crée le seed

- 3 dépôts git (`demo-api`, `demo-front`, `demo-data`) avec historique, enregistrés comme projets.
- 3 chantiers et des lignes à tous les états : brouillon, brouillon avec précisions, prête,
  lancée (vrai agent), faite, abandonnée, décision, sans chantier.
- ~12 conversations réelles : livrées, avec récap, commit en worktree non intégré, rapport
  long, plantée, question en attente, plan à valider, manager + 2 sous-agents (dont un en
  attente de réponse), une archivée (restaurable), une lente encore en cours à la fin.

## Bugs de prod mis au jour par le bac à sable (non corrigés ici)

1. **`FinalAnswer` jette `taches_terminees` / `taches_restantes`** : `backend/tools/registration.py:327`,
   la lambda ne passe que `answer` et `recap`. Le reste-à-faire et les décisions déclarés par
   les agents n'arrivent jamais au Bureau. Les profils `require_recap` (sous-agents `coder`)
   voient leur clôture **refusée 3 fois** avant acceptation forcée.
2. **`LancerAgent` (assistant du Bureau) plante** : `backend/tools/bureau_tools.py:236` importe
   `bouzecode.web_v2.services.dispatch`. Le module vit dans `services/work/dispatch.py`.
3. **Port 5056 codé en dur** dans `backend/multi_agent/client_tickets.py` (voir plus haut).
4. **Parser XML incrémental** : un fence ``` coupé entre deux fragments SSE (« `` » | « `python »)
   fait ignorer le lot `<tool_calls>` qui suit. Le tour se clôt en `text_no_tools`.
   Le faux LLM évite volontairement ce découpage.


## Scénarios composés et vérificateur d'invariants

Les scénarios `manager-worktree*` et `relance-apres-final` rejouent les ENCHAÎNEMENTS observés en
recette avec un vrai modèle (délégation depuis un worktree, réveil du parent, relance après la
réponse finale) : c'est là que les bugs d'état et d'intégration sont apparus. Un scénario
« collant » (`SCENARIOS_COLLANTS`) se poursuit sur l'énoncé suivant SANS tag — le message de
réveil envoyé par le serveur — au lieu de retomber sur la réponse par défaut.

Pendant CHAQUE test de `src/bouzecode/web_v2/tests/e2e_sandbox/`, `conftest.py` interroge en fond
`/api/agents/tree`, `/api/lignes`, `/api/inbox` et `/api/nav/counts` (~0,5 s) et fait échouer le
test si une règle de `invariants.py` est violée et DURE (6 s ; 30 s pour les pastilles, servies
par un autre cache). Règles : « Attend ses sous-agents » sans descendant actif, « En cours » sans
process vivant, agent tué pendant son propre appel `Environment`, travail intégré mais « En
échec » / « Arrêté sans finir », deux agents actifs sur une tâche, récap découpé en caractères,
pastilles incohérentes avec la boîte et l'arbre, mots bannis (SPEC §1) dans les libellés.
Une violation déjà présente au début du test est listée dans le résumé de session, sans faire
échouer ce test. Dispense : `@pytest.mark.sans_invariants` (à justifier).
