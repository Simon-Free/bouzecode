# [desc] Registers built-in /commit and /review skills with their prompt templates and metadata. [/desc]
"""Built-in skills that ship with bouzecode."""
from __future__ import annotations

from .loader import SkillDef, register_builtin_skill

# ── /commit ────────────────────────────────────────────────────────────────

_COMMIT_PROMPT = """\
Review the current git state and create a well-structured commit.

## Steps

1. Run `git status` and `git diff --staged` to see what is staged.
   - If nothing is staged, run `git diff` to see unstaged changes, then stage relevant files.
2. Analyze the changes:
   - Summarize the nature of the change (feature, bug fix, refactor, docs, etc.)
   - Write a concise commit title (≤72 chars) focusing on *why*, not just *what*.
   - If multiple logical changes exist, ask the user whether to split them.
3. Create the commit:
   ```
   git commit -m "<title>"
   ```
   If additional context is needed, add a body separated by a blank line.
4. Print the commit hash and summary when done.

**Rules:**
- Never use `--no-verify`.
- Never commit files that likely contain secrets (.env, credentials, keys).
- Prefer imperative mood in the title: "Add X", "Fix Y", "Refactor Z".

User context: $ARGUMENTS
"""

_REVIEW_PROMPT = """\
Review the code or pull request and provide structured feedback.

## Steps

1. Understand the scope:
   - If a PR number or URL is given in $ARGUMENTS, use `gh pr view $ARGUMENTS --patch` to get the diff.
   - Otherwise, use `git diff main...HEAD` (or `git diff HEAD~1`) for local changes.
2. Analyze the diff:
   - Correctness: Are there bugs, edge cases, or logic errors?
   - Security: Injection, auth issues, exposed secrets, unsafe operations?
   - Performance: N+1 queries, unnecessary allocations, blocking calls?
   - Style: Does it follow existing conventions in the codebase?
   - Tests: Are new behaviors tested? Do existing tests cover the change?
3. Write a structured review:
   ```
   ## Summary
   One-line overview of what the change does.

   ## Issues
   - [CRITICAL/MAJOR/MINOR] Description and location

   ## Suggestions
   - Nice-to-have improvements

   ## Verdict
   APPROVE / REQUEST CHANGES / COMMENT
   ```
4. If changes are needed, list specific file:line references.

User context: $ARGUMENTS
"""

# ── python-coding (équipement du profil coder) ──────────────────────

_PYTHON_CODING_PROMPT = """\
Règles de l'agent codeur Python. Tu travailles dans un worktree isolé avec un venv
dédié (base = branche `develop`).

## Environnement (uv — JAMAIS Poetry)
- Gestionnaire de paquets : `uv`.
- Un `.venv` par sous-projet. Exécute via `uv run --directory <sous-projet> ...`.
- JAMAIS Poetry. JAMAIS `pip install -e` d'un package interne au dépôt → publier
  d'abord sur l'index de paquets, puis installer depuis cet index.
- INTERDIT `python -c "..."` (bloqué par un hook) → écris un script `temp_*.py`,
  exécute-le, supprime-le (3 appels chaînés).
- PowerShell : double quotes, `$env:VAR` inline. Pas de `&&`, utilise `;`.
- Credentials : passe `UV_INDEX_*` inline sur la commande.

## Lancer les tests
- ⚠️ Dans ton worktree, le `.venv` (créé par `uv sync`) n'a PAS forcément `pytest`.
  Commande FIABLE (ajoute pytest à la volée, marche toujours), depuis la racine du
  sous-projet : `uv run --with pytest pytest -n auto -q <chemins de test>`.
  N'essaie PAS `python -m pytest` en boucle si pytest n'est pas installé — utilise
  directement `uv run --with pytest`.
- L'outil `RunPythonTest` peut aussi convenir s'il est disponible.
- Si une option pytest de la config manque (ex: --reruns) : `--override-ini="addopts="`.
- Playwright (réservé aux parcours UI critiques, lourd) :
  `uv run --with pytest pytest tests/playwright -q`.

## Écrire de bons tests
- User-centric / feature : on joue le VRAI comportement au point d'entrée le plus
  proche de l'utilisateur (CLI réelle, endpoint HTTP réel, fonction publique, fichier
  généré). Pas de smoke "200".
- INTERDIT `unittest.mock` (`.patch`, `@patch`, `MagicMock`) → fakes purs en mémoire
  + dépendances injectables.
- Fixtures DÉRIVÉES du réel : mêmes champs ET mêmes VALEURS qu'un vrai appel API
  (ex `parent="dispatcher:manual"`), jamais inventées pour coller au code (piège
  self-fulfilling). Détail + exemple avant/après dans la skill `fast-testing`.
- Timeouts courts. LIMITER les tests Playwright — sinon tests Python.

## Refacto
- Fichiers < 200 lignes ; ≤ 5 fichiers par dossier ; pas de `try/except/pass` ;
  pas d'abstraction prématurée ; noms descriptifs ; un README par dossier ;
  suivre les patterns existants. Auto-check après CHAQUE edit.

## Corrections hors-scope
- Tu PEUX corriger des tests/fichiers PRÉEXISTANTS cassés s'ils bloquent ta tâche
  (test rouge sans rapport, import mort, config KO), mais tu DOIS lister EXPLICITEMENT
  chaque correction hors-scope dans ta FinalAnswer : le fichier + pourquoi tu l'as
  touché. Ne masque jamais une réparation hors-scope — signale-la.

## Livraison
- Termine par une `FinalAnswer` = RAPPORT COMPLET : ce qui a changé et POURQUOI,
  fichiers touchés, résultat des tests (preuve verte), risques/limites, et la liste
  des corrections hors-scope éventuelles (cf. ci-dessus).
"""

# ── fast-testing (philosophie de test : user-centric + vitesse) ─────────────

_FAST_TESTING_PROMPT = """\
Philosophie de test pour bouzecode : des tests **user-centric et haut
niveau**, SOUS CONTRAINTE DE VITESSE. La suite est jouée tout le temps (à chaque
change) — un test lent est une dette qui finit désactivée. Vitesse ET réalisme,
pas l'un OU l'autre.

## 1. Tester le comportement réel, pas le retour d'une fonction
- On joue le VRAI comportement attendu par l'utilisateur, au point d'entrée le
  plus proche de lui : endpoint HTTP réel, CLI réelle, fichier généré, template
  Jinja compilé et rendu. Pas de smoke "ça renvoie 200", pas d'assertion sur un
  détail d'implémentation interne.
- Un bon test décrit une intention utilisateur ("quand je demande X, j'obtiens Y")
  et survit à un refactoring interne sans être réécrit.

## 2. Vitesse maximale — la suite tourne en permanence
- Optimise chaque test pour la vitesse : pas d'I/O réseau, pas de sleep, pas de
  DB lourde quand un fake en mémoire suffit, timeouts courts.
- Préfère `-n auto` (parallélisme) et des fixtures partagées peu coûteuses.
- Un test qui dépasse quelques centaines de ms doit se justifier.

## 3. Décourage Playwright quand c'est testable autrement
- Playwright (navigateur headless) est LENT et fragile. Réserve-le aux parcours
  UI critiques qui ne peuvent PAS être couverts autrement.
- Si le comportement est vérifiable via l'API HTTP sous-jacente, ou en compilant
  et rendant directement le template Jinja, fais-le en test Python — c'est des
  ordres de grandeur plus rapide et plus stable.

## 4. Mocke les LLM — ils sont trop lents et non déterministes
- Un appel LLM réel dans un test = plusieurs secondes + coût + non-déterminisme.
  INTERDIT dans la suite jouée en permanence.
- Injecte un fake LLM en mémoire (dépendance injectable) qui renvoie des réponses
  scriptées/déterministes. On teste alors la LOGIQUE autour du LLM (parsing,
  routage, gestion d'erreur, batching), pas le modèle lui-même.
- Réserve les appels LLM réels à un petit set de tests d'intégration explicitement
  marqués (ex: `-m llm`), exclus de la suite rapide par défaut.

## 5. Fakes purs, pas de mock magique
- Préfère des fakes/stubs purs en mémoire + dépendances injectables à
  `unittest.mock` (`.patch`, `MagicMock`) qui couplent le test à l'implémentation
  et masquent les régressions d'API.

## 6. Fixtures DÉRIVÉES du réel, JAMAIS inventées
- Règle : les cas de test se dérivent de la VRAIE forme des API / données —
  mêmes CHAMPS **et** mêmes VALEURS réelles qu'un vrai appel — jamais des valeurs
  inventées choisies pour coller au code sous test.
- Par défaut on mocke l'API SANS allumer le serveur (back : Flask
  `app.test_client()` en mémoire ; front : `fetch`-mock), mais le PAYLOAD injecté
  doit reproduire un vrai retour d'API : ex. une conversation humaine porte
  `parent="dispatcher:manual"` (ou `"dispatcher:validate"`, ou un `agent_id`),
  PAS `parent=null`.
- Danger d'une fixture inventée = test VERT self-fulfilling : la fixture épouse le
  bug, donc le test passe alors que la prod est cassée.
- Exemple vécu (bug réel) :
  - AVANT — `conversations.test.js` fabriquait des nœuds `parent: null`. Le filtre
    des racines en prod est `NODES.filter((n) => !n.parent)` (conversations.js:42) :
    avec `parent: null` le test est vert, mais en prod les ~130 conversations
    humaines réelles portent `parent="dispatcher:manual"` (truthy) → elles sont
    JETÉES des racines. Bug masqué par la fixture.
  - À CÔTÉ — `test_dispatch_routing.py` (test_agent_parent_round_trips) utilisait
    déjà la vraie valeur `"dispatcher:manual"`. Les deux côtés testaient donc des
    hypothèses CONTRADICTOIRES sur le même champ.
  - APRÈS (attendu) — la fixture front utilise `parent="dispatcher:manual"` pour
    une conversation racine ; le test devient un vrai révélateur du filtre.
- Exception — rendu visuel / CSS / layout : happy-dom et jsdom n'appliquent AUCUN
  CSS. Ne SIMULE pas le DOM pour vérifier un rendu visuel ; bascule sur un vrai
  navigateur (cf profil frontend / Playwright réservé aux parcours critiques).

User context: $ARGUMENTS
"""


def _register_builtins() -> None:
    register_builtin_skill(SkillDef(
        name="python-coding",
        description="Règles de l'agent codeur Python (uv, tests user-centric sans mock, refacto, livraison)",
        triggers=[],
        tools=[],
        prompt=_PYTHON_CODING_PROMPT,
        file_path="<builtin>",
        when_to_use="Équipement automatique du profil coder. Couvre l'environnement Python (uv), comment lancer/écrire les tests, les règles de refacto et la livraison.",
        argument_hint="",
        arguments=[],
        user_invocable=False,
        context="inline",
        source="builtin",
    ))
    register_builtin_skill(SkillDef(
        name="fast-testing",
        description="Philosophie de test bouzecode : tests user-centric haut niveau SOUS CONTRAINTE DE VITESSE (suite jouée en permanence) — décourage Playwright si testable via API/Jinja, mocke les LLM, fakes purs, vitesse maximale",
        triggers=["/fast-testing"],
        tools=[],
        prompt=_FAST_TESTING_PROMPT,
        file_path="<builtin>",
        when_to_use="À charger avant d'écrire ou de relire des tests. Couvre : tester le comportement réel (pas le retour d'une fonction), maximiser la vitesse de la suite jouée en permanence, éviter Playwright quand l'API/le rendu Jinja suffit, mocker les LLM (trop lents/non déterministes), utiliser des fakes purs.",
        argument_hint="[optional context]",
        arguments=[],
        user_invocable=True,
        context="inline",
        source="builtin",
    ))
    register_builtin_skill(SkillDef(
        name="commit",
        description="Review staged changes and create a well-structured git commit",
        triggers=["/commit"],
        tools=["Bash", "Read"],
        prompt=_COMMIT_PROMPT,
        file_path="<builtin>",
        when_to_use="Use when the user wants to commit changes. Triggers: '/commit', 'commit changes', 'make a commit'.",
        argument_hint="[optional context]",
        arguments=[],
        user_invocable=True,
        context="inline",
        source="builtin",
    ))

    register_builtin_skill(SkillDef(
        name="review",
        description="Review code changes or a pull request and provide structured feedback",
        triggers=["/review", "/review-pr"],
        tools=["Bash", "Read", "Grep"],
        prompt=_REVIEW_PROMPT,
        file_path="<builtin>",
        when_to_use="Use when the user wants a code review. Triggers: '/review', '/review-pr', 'review this PR'.",
        argument_hint="[PR number or URL]",
        arguments=["pr"],
        user_invocable=True,
        context="inline",
        source="builtin",
    ))


_register_builtins()
