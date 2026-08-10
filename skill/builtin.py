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

User context: $ARGUMENTS
"""


def _register_builtins() -> None:
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


_register_builtins()
