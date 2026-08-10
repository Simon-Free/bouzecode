# [desc] Conformity: a mechanism documented as active must be reachable from live code. [/desc]
"""Le harnais ne doit pas présenter comme vivant ce que plus personne n'appelle.

Un audit du 2026-07-27 a trouvé six mécanismes DOCUMENTÉS comme actifs et pourtant
morts : un levier réglable dont le lecteur n'a aucun appelant, un fichier de prompt
qui prescrit encore des outils mais n'est jamais injecté, un résumeur de compaction
dont le prompt n'est même plus chargé. Rien ne les avait détectés ; ils ont été
trouvés à la main.

RÈGLE DE DÉTECTION — deux univers PETITS et ÉNUMÉRABLES, une seule question :

  1. Les assets de prompt `src/system_prompts/*.txt` (6 fichiers). Chacun doit être
     chargé dans une constante par `_embedded_data.py`, ET cette constante doit être
     lue par du code que quelque chose appelle.
  2. Les leviers d'environnement `BOUZECODE_*` lus par `os.environ.get(...)` dans
     `src/` (35 lectures). La fonction qui lit doit avoir au moins un appelant.

CE QUE LA RÈGLE NE COUVRE PAS, volontairement :
  - Les symboles cités dans les tableaux « Module Reference » des `AGENTS.md`. Mesuré :
    61 signalements sur 700 symboles (9 %), dominés par des API publiques appelées
    depuis les tests ou les plugins, et par des `AGENTS.md` web_v2 périmés. Une règle
    qui hurle à ce rythme est désactivée en un mois — pire que pas de règle du tout.
  - Les chaînes d'appel profondes : `is_live` ne remonte QU'UN cran (cf. `source_index`).
  - Le code atteint par répartition dynamique (nom en base, hook enregistré par chaîne).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.backend.conformity.source_index import SRC, source_index

PROMPTS_DIR = SRC / "system_prompts"
EMBEDDED = SRC / "bouzecode" / "backend" / "core" / "_embedded_data.py"

# Exemptions EXPLICITES et DATÉES (2026-07-28). Ce sont les mécanismes morts que ce
# test a trouvés à sa première exécution. Ils ne sont PAS corrigés ici : plusieurs
# vivent dans des fichiers dont d'autres agents ont la charge. Chaque entrée porte la
# décision à prendre, pour que la dette reste visible au lieu d'être un skip muet.
EXEMPT_PROMPT_ASSETS = {
    "04_windows_platform_hints.txt":
        "TODO — mort : `context.py` substitue `{platform_hints}` par \"\" et le prompt "
        "vivant n'a plus le placeholder. `WINDOWS_PLATFORM_HINTS` n'est lu que par "
        "`get_platform_hints()`, qui n'a aucun appelant. Le fichier prescrit pourtant "
        "toujours des outils. DÉCISION : supprimer le fichier + la fonction, ou "
        "recâbler le placeholder. Propriétaire : agent en charge de core/context.py.",
    # 2026-08-10 — réintroduits par le portage OSS. En amont les deux assets ont été
    # SUPPRIMÉS (avec la constante `MEMORY_CONSOLIDATION_PROMPT`) parce que `/memory`
    # n'y avait aucun handler ; le dépôt public, lui, garde `/memory` vivant via
    # `commands/oss_shims/memory_cmd.py` → paquet à plat `memory/`. Mais ces deux
    # FICHIERS restent morts pour autant : la consolidation utilise son propre prompt
    # inline (`memory/consolidator.py::_SYSTEM`) et rien ne lit jamais le .txt.
    "06_memory_consolidation.txt":
        "TODO — mort : doublon figé de `memory/consolidator.py::_SYSTEM`, qui est la "
        "copie réellement envoyée au modèle. DÉCISION : faire lire ce fichier par le "
        "consolidateur, ou supprimer l'asset. Propriétaire : owner du paquet memory/.",
    "08_compaction_summarizer.txt":
        "TODO — mort : aucun consommateur, à aucun moment de l'historique public. La "
        "compaction utilise `COMPACTION_SYSTEM_PROMPT`, une chaîne littérale de "
        "`_embedded_data.py`. DÉCISION : recâbler ou supprimer l'asset.",
}

# 2026-07-29 — `BOUZECODE_PARALYSIS_ABORT_AFTER` ne figure plus ici : la décision prise
# est « supprimer levier, doc et champ d'API web », et elle a été exécutée en entier —
# `_get_paralysis_abort_after()`, le paramètre des deux routes web, la variable posée par
# le runner, la ligne de la skill `agent-loop` et les tests qui épinglaient le transport.
EXEMPT_ENV_KNOBS: dict[str, str] = {}


@pytest.fixture(scope="module")
def index():
    return source_index()


def prompt_asset_constants() -> dict[str, str]:
    """{nom de fichier prompt: constante dans laquelle `_embedded_data.py` le charge}."""
    tree = ast.parse(EMBEDDED.read_text(encoding="utf-8"))
    loaded = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
            continue
        call = node.value
        if not (isinstance(call, ast.Call) and getattr(call.func, "id", "") == "_load_prompt"):
            continue
        target = node.target if isinstance(node, ast.AnnAssign) else node.targets[0]
        loaded[call.args[0].value] = target.id
    return loaded


def orphan_prompt_assets(index) -> dict[str, str]:
    """{fichier prompt: pourquoi il n'atteint jamais le modèle}. Exemptions non filtrées."""
    constants = prompt_asset_constants()
    orphans = {}
    for asset in sorted(PROMPTS_DIR.glob("*.txt")):
        constant = constants.get(asset.name)
        if constant is None:
            orphans[asset.name] = "jamais chargé par _embedded_data.py"
        elif not index.is_live(constant, exclude=EMBEDDED):
            orphans[asset.name] = f"{constant} n'est lu par aucun code appelé"
    return orphans


def orphan_env_knobs(index) -> dict[str, str]:
    """{variable BOUZECODE_*: son lecteur sans appelant}. Exemptions non filtrées."""
    orphans = {}
    for knob in index.env_knobs():
        if knob.reader is None or index.references(knob.reader):
            continue
        where = Path(knob.path).relative_to(SRC)
        orphans[knob.variable] = f"{knob.reader}() — {where}:{knob.lineno}, 0 appelant"
    return orphans


def test_every_prompt_asset_reaches_the_model(index):
    """Un fichier de `src/system_prompts/` doit finir dans un prompt réellement envoyé."""
    found = {name: why for name, why in orphan_prompt_assets(index).items()
             if name not in EXEMPT_PROMPT_ASSETS}
    assert not found, (
        f"Assets de prompt jamais injectés : {found}. Soit le texte doit être recâblé, "
        "soit le fichier doit disparaître — un prompt mort prescrit encore."
    )


def test_every_env_knob_is_read_by_code_something_calls(index):
    """Un levier `BOUZECODE_*` annoncé comme réglable doit avoir un lecteur appelé."""
    found = {var: why for var, why in orphan_env_knobs(index).items()
             if var not in EXEMPT_ENV_KNOBS}
    assert not found, (
        f"Leviers d'environnement sans effet : {found}. Le régler ne change rien, "
        "alors que la doc et l'API web l'exposent."
    )


def test_every_exemption_is_still_a_real_orphan(index):
    """Les exemptions ne doivent pas devenir un dépotoir.

    Si un mécanisme exempté est réparé (ou supprimé), son entrée devient périmée et
    doit partir — sinon la liste finit par absoudre des morts qu'on n'a jamais vus.
    """
    still_dead = set(orphan_prompt_assets(index)) | set(orphan_env_knobs(index))
    stale = sorted((set(EXEMPT_PROMPT_ASSETS) | set(EXEMPT_ENV_KNOBS)) - still_dead)
    assert not stale, (
        f"Exemptions périmées : {stale} — ces mécanismes ne sont plus morts. "
        "Retire leur entrée de EXEMPT_PROMPT_ASSETS / EXEMPT_ENV_KNOBS."
    )


def test_the_rule_leaves_the_living_alone(index):
    """Preuve de non-hurlement : le prompt système principal n'est PAS signalé."""
    orphans = orphan_prompt_assets(index)
    assert "01_main_system_prompt.txt" not in orphans
    assert "05_plan_mode.txt" not in orphans
    assert index.is_live("SYSTEM_PROMPT_TEMPLATE", exclude=EMBEDDED)


def test_an_import_alias_still_counts_as_a_real_use(index):
    """Preuve que la règle mord au bon endroit : `iter_sse` n'est JAMAIS appelé sous son
    propre nom — il est importé `as _iter_sse` puis appelé ainsi. Sans la résolution
    d'alias, la règle le déclarerait mort, et deux faux positifs suffisent à faire
    supprimer un garde-fou."""
    assert index.references("iter_sse"), "la résolution d'alias a régressé"
    assert index.references("register_chrome_devtools_tools")


def test_a_name_nobody_ever_writes_is_not_live(index):
    """Contrôle négatif : l'index ne déclare pas vivant n'importe quoi."""
    assert not index.is_live("un_symbole_qui_n_existe_nulle_part")
