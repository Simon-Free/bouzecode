# Méthodologie de test — bouzecode

> Détail fichier par fichier et état d'avancement : `TEST_TRIAGE.md`.

## L'objectif

**Un test doit se comprendre sans ouvrir le code testé.** On lit un test comme une
histoire : *l'utilisateur demande X, l'agent fait Y, on observe Z*.

Corollaire : la suite doit être **dominée par des tests de conversation** — de vraies
conversations qui exercent l'objet principal — et non par des tests unitaires de
fonctions internes isolées.

---

## La politique de test : quatre niveaux

Du moins cher au plus cher. **Toujours prendre le plus haut de la liste qui suffit.**

### 1. `mock_llm` — le défaut, ~90 % des cas

```python
from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

result = bouzecode(["message user"], mock_llm=MockLLM([...]))
```

On ne simule que **les réponses du modèle**. La boucle, les outils, l'enforcement et
la méthodologie tournent pour de vrai. Pas de réseau, pas de navigateur → rapide
(le cluster `enforcement/` entier tourne en ~3 s).

C'est le niveau à viser pour tout ce qui est « ce que le modèle produit → ce que le
système fait » : loop, tools, enforcement, méthodologie, plan mode, skills, sessions.

### 2. `mock_api` — uniquement pour le transport

```python
result = bouzecode([...], mock_api=[...])   # pytest -p no:xdist obligatoire
```

Démarre un faux serveur SSE (`tests/mock_anthropic_server.py`), pointe le **vrai
client** dessus (`ANTHROPIC_BASE_URL`) et **n'éteint pas** `stream`/`get_tool_schemas`.
Tout le vrai pipeline tourne : dispatch, sérialisation wire, `anthropic_stream`,
parsing SSE, `XmlToolStreamParser`/thinking, retry.

À réserver strictement à ce qui est **du transport** : parsing SSE, chunk coupé en
plein tag, retry, `cache_control` sur le fil, sérialisation wire. Un vrai serveur
Flask est démarré par appel → c'est lent.

- Items de réponse : `str`, ou dict `{"chunks":[...], "thinking":[...], "status":500,
  "truncate_after":N, "stop_reason":"max_tokens", "raw_sse":"..."}`.
- `result.recorded_requests` = les **corps de requête réels** envoyés (asserter le
  wire : system, messages, cache_control).
- Référence : `tests/backend/providers/test_mock_api_e2e.py`,
  `tests/backend/methodology/cache/test_cache_wire_e2e.py`.

### 3. Client de test Flask — le défaut pour `web_v2`

```python
resp = client.get("/api/...")     # resp.status_code, resp.get_json()
```

C'est **ce qui remplace la majorité des tests Playwright** : on vérifie le
comportement HTTP (route, JSON, code de retour, effet de bord observable côté
serveur) **sans lancer de navigateur**. C'est le compromis vitesse/lisibilité
retenu pour `web_v2` : à comportement égal, un test client Flask est des ordres de
grandeur plus rapide et plus lisible qu'un test Playwright.

### 4. Playwright — dernier recours, strictement réservé

Réservé à **ce que seul un vrai DOM peut prouver** : rendu en streaming,
interaction réelle de l'utilisateur (clic, focus, scroll, ordre de repaint).

> **N'en ajouter AUCUN.** Si un test Playwright existant ne prouve que du HTTP ou du
> JSON, il doit être **redescendu au niveau 3**.

### Comment choisir

Tracer le flux réel et se demander : **où se produit le comportement ?**

| Le comportement se produit… | Niveau |
|---|---|
| côté loop / tools / méthodologie / enforcement (réaction à ce que le modèle émet) | 1 — `mock_llm` |
| côté transport (wire, SSE, parsing, retry, `cache_control`) | 2 — `mock_api` |
| côté route HTTP `web_v2` (JSON, code retour, effet de bord) | 3 — client Flask |
| côté rendu/interaction navigateur, et **uniquement** là | 4 — Playwright (ne pas en ajouter) |
| pur entrelacement de threads non déterministe, ou invariant d'un algorithme pur (bornes, parsing, tri) | test unitaire assumé |

---

## Règles de lisibilité

À appliquer **à chaque test écrit ou touché**, sans exception.

1. **Un docstring d'une ligne**, qui énonce le comportement **du point de vue de
   l'utilisateur**, pas de l'implémentation.
   - ✅ « Une lecture toujours pas snippetée au tour suivant déclenche un rappel
     d'enforcement. »
   - ❌ « teste `_check_snippet_coverage` ».
2. **Nom de test = phrase.** `test_read_without_snippet_warns`, pas `test_hook_2`.
   Un nom comme `test_empty` ou `test_small_result_excluded` ne dit pas quel
   comportement est en jeu — le renommer.
3. **Structure visible** : ce que l'utilisateur dit → ce que le modèle émet → ce
   qu'on observe. Trois blocs, dans cet ordre.
4. **Pas de `MagicMock`.** Pour vérifier qu'une fonction interne est appelée, on
   **espionne la couture** avec un `monkeypatch` qui enregistre puis délègue à la
   vraie implémentation. Un `MagicMock` fige une signature interne et ne prouve
   aucun comportement.
5. **Pas d'import de symbole privé** (`from x import _foo`) dans un test de feature.
   Si on a besoin du privé, c'est qu'on teste l'implémentation, pas le
   comportement. (Les tests unitaires assumés d'un module de bas niveau — parseur,
   compteur de lignes — peuvent importer leurs propres privés : c'est leur objet.)
6. **Pas de précondition posée à la main** quand la conversation peut la produire.
   Exemple concret : au lieu de `_read_files.add(path)`, faire lire le fichier par
   l'agent au tour 1. Cf. `methodology/snippet/test_snippet_e2e.py::_run_after_reads`.

---

## ⚠️ Le piège n°1 : le test de conversation vide

Un test de conversation qui asserte **une absence** (« aucun warning n'est émis »)
peut passer sans jamais atteindre le code visé. C'est arrivé pendant ce chantier :
deux tests « le Snippet du même batch couvre le Read » passaient alors que le
scan de couverture ne tournait pas du tout à ce moment de la conversation.

**Règle : toute assertion d'absence doit être accompagnée de son contrôle négatif**
— une variante minimalement modifiée qui, elle, DOIT déclencher. Si le contrôle
négatif est silencieux lui aussi, le test ne prouve rien et la forme du tour est à
revoir.

Exemple appliqué : `enforcement/e2e/test_e2e_snippet_coverage.py` appaire
`test_read_snippeted_in_the_same_batch_raises_no_warning` avec
`test_read_snippeted_on_another_file_in_the_same_batch_warns`.

Corollaire du même garde-fou : **ne jamais déclarer un cas « inatteignable » sur une
lecture seule.** Avant d'ajouter une exception dans le code de prod, lancer la suite
large : un test existant peut prouver que le cas EST atteignable. Une exception
posée sur un cas en fait réel **casse la prod**.

---

## Gotchas du harness `bouzecode()`

- **Un batch méta-seul ne clôt PAS le tour.** `Methodology` et `Snippet` sont dans
  `loop_turn.META_ONLY_TOOLS` : un tour qui n'émet qu'eux (même avec du texte final)
  reçoit un nudge « ce tour n'a produit ni travail ni réponse finale » et **continue**.
  Ce qui clôt une session, c'est **une réponse en texte SANS aucun tool call**
  (`close_reason="text_no_tools"`), ou `FinalAnswer`.
  → Tout scénario `MockLLM` se termine donc par une réponse texte nue. C'est la
  cause n°1 de `AssertionError: MockLLM: stream() called N times, only N-1 responses
  configured`.
- **Le scan de couverture Snippet attend le tour suivant.** `get_unsnippeted_reads`
  se tait tant que le batch porteur de la lecture n'a pas d'assistant après lui.
  Un scénario « lecture puis clôture immédiate » ne l'exerce jamais : intercaler un
  vrai tour de travail.
- **`mock_tools` fake TOUS les outils** (il remplace `_execute_level`) : Methodology
  et Snippet renvoient alors `[X executed]` au lieu de s'exécuter. Si un test a
  besoin que Methodology/Snippet tournent **réellement** tout en fournissant la
  sortie d'un outil custom, **enregistrer cet outil** avec un vrai `func` (via
  `push_local_overlay` + `register_tool`) et **ne pas** passer `mock_tools`.
  Cf. `methodology/snippet/test_tool_id_snippet_e2e.py`.
- **La note de méthodologie n'est jamais vide en conversation** : le tour Methodology
  y écrit son `content` et le message user y est auto-append. Asserter sur le
  *contenu snippeté* (ou son absence), pas sur `note == ""`.
- **Lire l'état après coup** : `result.state.context_state.notes[METHODOLOGY_NOTE]`,
  `result.state.notes_timeline`, `result.events` (les `EnforcementWarning` /
  `RecoveryFailed` émis par la boucle — souvent le meilleur point d'observation,
  sans aucun mock), et le payload réellement envoyé via `mock.recorded_calls[i]`.
- **La recovery ne tourne qu'avec `recover_memory=True`** dans `config_overrides`.

---

## Exceptions assumées

- **Les invariants de configuration statique** (un schéma d'outil contient tel
  param, un template de prompt mentionne tel mot, les docs XML exposent telle
  option) ne sont PAS des comportements de conversation — le harness stub les
  schémas. Ils restent des assertions directes sur la donnée statique
  (ex. `tools/symbols/test_symbols_schema.py`,
  `methodology/snippet/test_snippet_skill_mention.py`), car ils gardent la
  **découvrabilité** d'une option par le modèle, que la conversation (qui code
  l'appel en dur) ne vérifie pas.
- **Les invariants d'un algorithme pur** : bornes et seuils
  (`enforcement/test_snippet_threshold.py`), départage de chemins
  (`methodology/snippet/test_snippet_tool_fallback.py`), parseur XML streaming,
  compteurs de tokens. Une conversation atteint *une* branche, pas *chaque*
  branche. On les garde en unitaire — mais on leur applique quand même les règles
  de lisibilité 1 et 2.
- **La repro déterministe d'une race** (entrelacement de threads). Le *comportement
  correct* (un batch parallèle finit sans corruption) est, lui, observable.

---

## Cas pilote — `_build_assistant_content` (référence + leçon)

- **Atteignable** (thinking transmis + archivé + strippé du wire) → couvert par
  `thinking/overflow/test_thinking_save_e2e.py` (harness `bouzecode()` + spy sur
  `_build_assistant_content`).
- **`at_text == "."` : on a CRU que c'était inatteignable, c'était FAUX.** En posant
  une exception, la suite large a immédiatement échoué sur
  `agent_loop/turn/test_truncated_stream.py` : sur une réponse tronquée par
  `max_tokens`, le modèle émet un `.` seul comme texte visible. → On a **reverté
  l'exception**, gardé le traitement gracieux, et **écrit un test de feature qui
  l'atteint depuis MockLLM** : `test_thinking_save_e2e.py::
  test_truncated_dot_turn_keeps_thinking_drops_dot`.

Leçon : la frontière « atteignable / non » se vérifie **en exécutant**, pas en
raisonnant.

Infra réutilisable issue du pilote : `MockLLM` accepte
`{"thinking": [...], "text": "..."}` et émet de vrais `ThinkingChunk`.

---

## Bugs réels trouvés par la conversion en conversation

- **`_build_grep_summary` cassé sur Windows** (corrigé) : il parsait
  `chemin:ligne:contenu` via `split(":", 2)`, mais `C:\...` injecte un `:` parasite
  → `matches` vide. Le test unitaire le ratait (chemins Unix `src/foo.py:1:`). La
  conversation, avec de vrais chemins Windows absolus, l'a exposé. Fix = regex
  `^(.+?):(\d+):(.*)$`. Couvert par
  `tools/search/test_search_e2e.py::test_grep_overflow_returns_structured_summary`.
- **Garde-fou Edit « modified on disk » invisible au modèle** (constat, non
  corrigé) : `_edit` ajoute un `[Warning] modified on disk`, MAIS
  `_compact_tool_result` (loop_turn.py) réduit tout Edit réussi à
  `✓ fichier (+X/-Y lines)` et **jette le warning** avant qu'il n'entre dans le
  transcript → le modèle ne le voit jamais. Ce garde-fou n'est donc PAS observable
  en conversation (et est probablement inopérant en prod). Les tests file-state
  restent en unit dans `tools/test_mods.py`. À investiguer côté prod.
- **`regression/structure/test_no_mcp_references.py` passait à vide** (corrigé) :
  `SRC_DIR` pointait vers `tests/backend/regression/src/` (inexistant post-migration
  `src/`) → `rglob` ne scannait rien. Fix du chemin.
- **Deux tests de couverture Snippet passaient à vide** (corrigé, cf. « piège n°1 »
  ci-dessus) : la forme du tour empêchait le scan de tourner.

---

## Dette connue

- `enforcement/test_enforcement_recovery.py::test_enforce_methodology_is_plain_and_dedups`
  — historiquement rouge (cf. `docs/archive/REMAINING_TEST_FAILURES.md`, archivé
  depuis la racine). Il exige que `enforce_methodology` devienne une **fonction
  plate**, la récupération se faisant après le tour via `run_enforcement_recovery`
  — or `run_enforcement_recovery` **n'est pas câblé dans `loop.py`**. Le rendre plat
  désactiverait silencieusement l'enforcement in-wire en session réelle. C'est une
  **décision d'architecture volontairement mise de côté par le propriétaire** :
  ne pas « réparer » ce test en aplatissant la fonction.
  *(État au 2026-07-27 : le test passe. La dette d'architecture, elle, reste
  entière — `run_enforcement_recovery` n'a toujours aucun appelant en prod.)*

## Où lancer les tests

```
.venv\Scripts\python.exe -m pytest tests\<chemin> -q
.venv\Scripts\python.exe -m pytest tests\<chemin> -q -p no:xdist     # obligatoire pour mock_api
```

Échec pré-existant à ignorer : `tests/backend/tools/registry/test_commands_cli.py::test_commands`
(dépend de l'environnement).
