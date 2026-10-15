# [desc] Marqueurs pytest DERIVES du test (dossier, fixtures, corps) au lieu d'etre poses a la main [/desc]
"""Deux axes de marqueurs, tous deux DERIVES de ce que le test est et de ce qu'il consomme.

**Axe zone** — `backend` / `ui` / `web` : quelle partie du produit. Lu dans l'arborescence
(`marker_for`), qui EST deja la thematique.

**Axe dependance** — `network` / `llm` / `timing` / `slow` : de quoi le test a besoin pour
tourner, et ce qu'il coute. Lu a trois endroits, chacun choisi pour sa granularite (voir
chaque fonction) : la cloture de fixtures (`markers_for`), le corps du test
(`markers_for_source`), le module entier (`markers_for_module`). Les deux axes se cumulent :
`-m "backend and not network"`.

Le second axe existe parce que le premier ne repond pas a « qu'est-ce que je peux lancer hors
VPN, et qu'est-ce qui me coute dix minutes ». Le vocabulaire est commun aux depots demo :
`network` sort du process, `llm` appelle un vrai modele, `timing` affirme des chevauchements
temporels (donc ne se parallelise pas), `slow` vaut « plus de 5 s constatees ».

`slow` accompagne les familles dont on a MESURE qu'elles coutent des secondes — sinon
`-m "not slow"` ment. Il n'est pas colle aux 103 tests de concurrence qui durent des
fractions de seconde : les declarer lents serait le meme mensonge, dans l'autre sens.

Le vocabulaire commun compte aussi `browser` : PAS declare ici. Sur les 2933 clotures de
fixtures, aucune ne tire `page` / `browser` / `context` et `page.goto` n'apparait nulle part —
`tests/frontend/` passe par le client de test Flask, malgre le « Flask + Playwright » de
`pyproject.toml`. Declarer un marqueur que personne ne porte est le defaut qu'on corrige.

MESURE du 2026-08-14, `-n 4` (jamais `-n auto` : la machine est partagee) :

    avant   -m "not web and not ui"          2711 tests   1917 s (31 min 57)
    apres   -m "not slow and not timing"     2796 tests    109 s (1 min 49)
    reste   -m "slow or timing" -p no:xdist   137 tests    365 s (6 min 04)

Le run « apres » couvre PLUS de tests que le run « avant » — il n'exclut ni `ui` ni `web` — et
tient en moins de deux minutes. Les 30 durees les plus longues du run « avant » : 62 s (un
chronometre), 30 s (un `sleep` de fichier-cible), huit tests de 17 a 30 s qui lancent tous un
pytest imbrique, puis les appels au gateway. La queue de la suite est faite de dependances.

La voie « reste » sort 3 rouges — trois runs imbriques tues a 60 s parce que d'autres agents
occupaient la machine. C'est la nature de cette famille, et c'est justement la raison de la
sortir : ces rouges-la ne disent rien du code, et ils ne polluent plus la voie de 109 s.

⚠ Les 1917 s comptent aussi ~26 minutes passees dans UN test qui ne termine jamais
(`test_enforcement_persist.py` : le faux flux ne satisfaisait jamais l'enforcement, la boucle
d'agent tournait en rond). C'etait un bug du depot, pas une dependance : le run « apres » l'a
explicitement deselectionne pour que les deux chiffres se comparent. REPARE (mesure du
2026-10-15 : 1 passed en 1,0 s) — le test sert desormais un flux scripte borne
(`_scripted_stream`) qui finit par un tour sans tool call et echoue en une seconde, en le
disant, si la boucle reclame un tour hors script. Il ne porte toujours aucun marqueur, et ne
doit pas en recevoir : un marqueur rendrait invisible une regression au lieu de la montrer.

Repartition obtenue : `llm` 11, `network` 11, `timing` 126, `slow` 35 sur 2933 tests.

    pytest                                  # inchange : rien de nouveau n'est deselectionne
    pytest -m "not slow and not timing"     # la boucle de dev, en parallele
    pytest -m timing -p no:xdist            # la famille fragile, en sequentiel
    pytest -m "not network"                 # hors VPN

⛔ Ce qui est pose a la main derive, et ce depot en donne trois preuves. `ui` et `web` etaient
declares dans `pyproject.toml` et portes par ZERO test au 2026-08-13 : la desselection ne
desselectionnait rien, et les 29 fichiers de `tests/ui/` et `tests/frontend/` — annonces
« set aside » — tournaient a chaque run. `llm` etait dans le meme etat au 2026-08-14 (zero
`@pytest.mark.llm` sur 2920 tests), et sa description (« readme_sync regen ») designait des
tests qui tournent contre un `_FakeClient` : les vrais appels au gateway sont ailleurs.

Les poser a la main sur 434 fichiers ne tiendrait pas davantage : le dossier porte deja
l'information, on la lit au lieu de la dupliquer dans un decorateur.
"""
from __future__ import annotations

import inspect
from collections.abc import Iterable
from pathlib import Path

# Dossier de tests -> marqueur. `frontend` porte `web` : c'est le nom declare dans
# pyproject.toml, on ne le renomme pas ici (l'addopts existant s'appuie dessus).
DOSSIER_MARQUEUR = {
    "tests/backend/": "backend",
    "tests/ui/": "ui",
    "tests/frontend/": "web",
}


def marker_for(node_path: str) -> str | None:
    """Marqueur d'un test d'apres son chemin, ou None s'il n'est dans aucun dossier connu.

    `node_path` est accepte avec des separateurs Windows ou POSIX.
    """
    path = node_path.replace("\\", "/")
    for dossier, marqueur in DOSSIER_MARQUEUR.items():
        if dossier in path:
            return marqueur
    return None


# ============================================================================
# Second axe, ORTHOGONAL au precedent : de quoi le test a-t-il besoin pour
# tourner, et combien coute-t-il ? Les deux se cumulent : `-m "backend and not
# network"`. Voir le docstring de `markers_for` / `markers_for_source`.
# ============================================================================

# Seule porte vers le gateway REEL. `tests/conftest.py::_llm_network_guard` fait echouer
# bruyamment tout appel a `stream_anthropic` qui n'est pas passe par la : la liste des tests
# qui sortent du process se lit donc exactement dans les corps qui appellent cette fonction.
APPEL_GATEWAY_REEL = "require_api_key("

# Un test qui pilote lui-meme des threads affirme un ORDRE ou un CHEVAUCHEMENT : il compte des
# executions simultanees, reproduit une course, verifie qu'un verrou tient. Le paralleliser
# revient a le mettre en concurrence avec ce qu'il mesure.
JETONS_CONCURRENCE = ("threading.Thread", "ThreadPoolExecutor")

# Un test qui se CHRONOMETRE affirme une duree reelle. Le seul du depot (2026-08-14) attend
# `_INTER_CHUNK_TIMEOUT_S` puis exige `_INTER_CHUNK_TIMEOUT_S <= elapsed < +3 s` : 62 s
# mesurees, le test le plus lent de la suite, et une fenetre de 3 s que la charge suffit a
# faire sauter.
JETONS_CHRONOMETRE = ("time.monotonic(", "time.perf_counter(")

def markers_for(node_path: str, fixture_names: Iterable[str]) -> set[str]:
    """Marqueurs derives de la CLOTURE DE FIXTURES du test.

    Une fixture autouse de repertoire est une declaration faite une fois pour toutes : elle
    reste vraie quand un fichier est renomme ou qu'un test est ajoute a cote. C'est pour ca
    qu'on lit `item.fixturenames` plutot qu'une liste de modules.

    `node_path` fait partie du contrat commun aux depots demo (meme signature dans
    `demo_application` et `demo_ingestion`, ou des dossiers entiers sont « navigateur »
    ou « base de donnees »). Ici il ne discrimine rien de plus : l'axe zone
    (`marker_for`, ci-dessus) epuise deja ce que l'arborescence dit de bouzecode.

    Aucune fixture n'implique plus de marqueur. `_un_seul_pytest_imbrique_a_la_fois` (verrou
    du repertoire runner) valait `timing`+`slow` ; mesure du 2026-10-05, ces tests etaient lents
    et rouges parce que leur pytest imbrique collectait `%TEMP%` entier. Etanches
    (`tests/pytest_imbrique.py`), ils durent 1 a 3 s et tournent en `-n 4`.
    """
    return set()


def markers_for_source(test_source: str) -> set[str]:
    """Marqueurs derives du CORPS du test.

    Pourquoi pas une liste de modules, comme dans `demo_ingestion` : ici la granularite du
    fichier ment. Mesure du 2026-08-14 — `test_terminal_subagent.py` compte 10 tests dont UN
    seul appelle le gateway, `test_e2e_run_python_test.py` 11 dont UN seul. Marquer ces modules
    entiers `llm` sortirait 19 tests hors-ligne du run par defaut de `-m "not llm"`.

    Le corps du test, lui, est exact et ne demande aucun entretien : un test live ecrit demain
    appellera `require_api_key()` — c'est la seule facon de franchir `_llm_network_guard` —
    et sera marque le jour meme.
    """
    marqueurs: set[str] = set()
    if APPEL_GATEWAY_REEL in test_source:
        # `network` ET `llm` : `llm` dit QUOI (une vraie generation, facturee), `network` dit
        # que le test ne peut pas tourner hors VPN. Un developpeur hors ligne coupe `network`
        # sans avoir a connaitre le vocabulaire des modeles.
        marqueurs.update({"llm", "network", "slow"})
    if any(jeton in test_source for jeton in JETONS_CHRONOMETRE):
        marqueurs.update({"timing", "slow"})
    return marqueurs


def markers_for_module(module_source: str) -> set[str]:
    """`timing` derive du MODULE entier, et pas du seul corps du test. Volontairement large.

    Les deux erreurs n'ont pas le meme prix, et c'est ce qui fixe la granularite :

    - trop marquer `timing` ne coute qu'un peu de sequentiel — les tests tournent, ils tournent
      juste l'un apres l'autre ;
    - pas assez marquer rend un ROUGE FAUX, et un rouge faux fait cesser de lire les resultats.

    Mesure du 2026-08-14 : au corps du test seul, `test_dag_concurrency.py` n'aurait eu qu'UN
    test marque sur 7 — les six autres affirment pourtant le meme chevauchement, via des
    helpers definis en tete de module. Au module, la famille compte 103 tests dans 9 fichiers.
    `demo_ingestion` a tranche pareil (« ils n'ont pas de fixture commune, c'est leur SUJET
    qui les reunit ») avec une liste de modules ecrite a la main ; ici le sujet se lit dans le
    code du module, donc il n'y a rien a tenir a jour.

    Pas de `slow` ici : ces tests durent des fractions de seconde. Le leur coller sortirait
    103 tests rapides d'un `-m "not slow"` — le mensonge symetrique de celui qu'on corrige.
    """
    if any(jeton in module_source for jeton in JETONS_CONCURRENCE + JETONS_CHRONOMETRE):
        return {"timing"}
    return set()


# ── De quoi nourrir les regles ci-dessus. Seuls morceaux qui touchent au disque ; les regles,
#    elles, restent pures et se testent sans lancer pytest dans pytest. ──────────────────────

def source_du_test(item) -> str:
    """Le code source de la fonction de test, ou "" pour un item qui n'en a pas (doctest)."""
    fonction = getattr(item, "function", None)
    return inspect.getsource(fonction) if fonction is not None else ""


def source_du_module(chemin: str, cache: dict[str, str]) -> str:
    """Le fichier de test entier, lu UNE fois par module (2933 items pour 434 fichiers)."""
    if chemin not in cache:
        cache[chemin] = Path(chemin).read_text(encoding="utf-8", errors="replace")
    return cache[chemin]
