# conformity

## Purpose

Garde-fous contre une seule classe de panne : **le harnais présente comme vivant ce
qui est mort**. Un audit du 2026-07-27 a trouvé six cas en un jour (un levier sans
appelant, un prompt jamais injecté, un résumeur jamais chargé, quatre skills jetées en
silence) — aucun n'avait été détecté par un test.

Ces tests lisent la **configuration réelle et le disque réel**, exécutent le **vrai
loader** plutôt que d'en recopier le comportement, et utilisent des **exemptions
datées avec la décision à prendre** plutôt que des skips muets. Ils sont les frères de
`tests/backend/prompts/test_prompt_registry_conformity.py`.

## Usage

```
uv run --no-sync --directory . pytest tests/backend/conformity -n auto -v
```

| Fichier | Rôle |
|---------|------|
| `source_index.py` | Index AST du `src/` livré : un import n'est PAS un usage, un alias d'import l'est. Fournit `source_index()`, `references()`, `is_live()`, `env_knobs()`. |
| `test_documented_mechanism_reachability.py` | Un mécanisme documenté comme actif doit être joignable : assets `system_prompts/*.txt` et leviers `BOUZECODE_*`. |
| `test_skill_declaration_loadability.py` | Toute skill déclarée (`<store>/<nom>.md`, `<store>/<nom>/skill.md`) se résout vraiment, et aucune ne masque un builtin. |

## Ajouter une exemption

Jamais de `pytest.skip`. On ajoute une entrée datée dans le dict d'exemptions du test,
portant la DÉCISION à prendre et son propriétaire. `test_every_exemption_is_still_a_real_orphan`
supprime les entrées périmées : une exemption dont le mécanisme est réparé fait rougir
le test, pour qu'elle parte.
