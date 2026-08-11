# [desc] Les deux dictionnaires disent la même chose, et personne n'affiche une clé qui n'existe pas. [/desc]
"""L'interface est bilingue : anglais par défaut, français au choix.

Ce que ces tests protègent n'est pas la traduction (un humain la juge) mais son INTÉGRITÉ.
Trois façons de casser une interface bilingue sans rien voir en développement :
  1. ajouter une clé dans une langue et l'oublier dans l'autre — la bascule sert alors un mot
     anglais au milieu du français, ou un marqueur `⟦clé⟧` ;
  2. écrire `t("conv.emtpy")` dans du JavaScript rarement exécuté — la faute de frappe ne se
     voit qu'en production, sur l'écran qu'on n'ouvre jamais ;
  3. créer un fichier de dictionnaire sans le brancher (ni dans `index.js` pour les modules et
     les tests, ni dans `base.html` pour les pages) — il ne serait jamais chargé.

Aucun de ces trois défauts ne fait échouer un test d'interface : la page s'affiche, en partie
seulement dans la bonne langue. On les attrape donc en lisant les fichiers.
"""
from __future__ import annotations

import re
from pathlib import Path

import bouzecode.web_v2

# Le paquet, pas le fichier de test : ces tests vivent hors de `src/`, mais lisent le
# JavaScript et les gabarits livrés.
WEB_V2 = Path(bouzecode.web_v2.__file__).resolve().parent
I18N = WEB_V2 / "static" / "js" / "i18n"
STATIC_JS = WEB_V2 / "static" / "js"
TEMPLATES = WEB_V2 / "templates"

# Une entrée de dictionnaire tient sur une ligne qui COMMENCE par sa clé. Les valeurs longues
# se poursuivent sur les lignes suivantes, préfixées par `+` : elles ne peuvent pas être prises
# pour des clés.
_KEY_RE = re.compile(r'^\s+"([A-Za-z0-9_.]+)":', re.MULTILINE)
# `t("clé")`, `window.i18n.t("clé")`, `has("clé")`. Le `[,)]` final est ce qui distingue une
# clé ENTIÈRE d'un préfixe concaténé : `t("phase." + phase)` construit sa clé à l'exécution et
# n'est donc pas vérifiable ici — sa famille l'est par les tests de rendu.
_CALL_RE = re.compile(r'\b(?:t|has)\(\s*"([A-Za-z0-9_.]+)"\s*[,)]')
_ATTR_RE = re.compile(r'data-i18n(?:-(?:placeholder|title|aria-label|value))?="([A-Za-z0-9_.]+)"')


def _dict_files(lang: str) -> list[Path]:
    return sorted((I18N / lang).rglob("*.js"))


def _keys(lang: str) -> dict[str, str]:
    """clé -> fichier qui la définit, pour toute la langue."""
    found: dict[str, str] = {}
    for path in _dict_files(lang):
        for key in _KEY_RE.findall(path.read_text(encoding="utf-8")):
            found[key] = path.name
    return found


def test_the_two_languages_define_exactly_the_same_keys():
    """Une clé ne peut pas exister d'un côté seulement : la bascule trouerait la page."""
    english, french = _keys("en"), _keys("fr")

    assert set(english) == set(french), (
        f"anglais sans français : {sorted(set(english) - set(french))} ; "
        f"français sans anglais : {sorted(set(french) - set(english))}"
    )
    assert english, "aucune clé lue : le format des dictionnaires a changé, ce test ne voit plus rien"


def test_no_key_is_defined_twice_in_the_same_language():
    """Deux fichiers qui définissent la même clé : le dernier chargé gagne, en silence."""
    for lang in ("en", "fr"):
        seen: dict[str, str] = {}
        duplicates = []
        for path in _dict_files(lang):
            for key in _KEY_RE.findall(path.read_text(encoding="utf-8")):
                if key in seen:
                    duplicates.append(f"{key} ({seen[key]} et {path.name})")
                seen[key] = path.name
        assert not duplicates, f"clés dupliquées en {lang} : {duplicates}"


def _used_keys() -> dict[str, str]:
    """Toute clé écrite en dur dans le JavaScript de l'interface ou dans un gabarit."""
    used: dict[str, str] = {}
    for path in STATIC_JS.rglob("*.js"):
        if I18N in path.parents or path == I18N:
            continue  # le noyau et les dictionnaires ne consomment pas de clés
        for key in _CALL_RE.findall(path.read_text(encoding="utf-8")):
            used[key] = str(path.relative_to(WEB_V2))
    for path in list(TEMPLATES.glob("*.html")) + [WEB_V2 / "services" / "message_view.py"]:
        for key in _ATTR_RE.findall(path.read_text(encoding="utf-8")):
            used[key] = str(path.relative_to(WEB_V2))
    return used


def test_every_key_the_interface_asks_for_exists():
    """Une faute de frappe dans `t("…")` n'affiche rien d'utile — et seulement sur cet écran-là."""
    english = _keys("en")
    unknown = {key: where for key, where in _used_keys().items() if key not in english}

    assert not unknown, f"clés utilisées mais absentes du dictionnaire : {unknown}"


def test_every_dictionary_file_is_actually_loaded():
    """Un dictionnaire non branché ne sert à rien, et rien ne le dit.

    Deux points de chargement, tous les deux obligatoires : `index.js` (modules ES et vitest)
    et `base.html` (les trois pages, y compris celles en scripts classiques)."""
    index = (I18N / "index.js").read_text(encoding="utf-8")
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")

    for lang in ("en", "fr"):
        for path in _dict_files(lang):
            relative = path.relative_to(I18N).as_posix()
            assert f'"./{relative}"' in index, f"{relative} n'est pas importé par index.js"
            # base.html boucle sur les noms de dictionnaires, sans le préfixe de langue.
            stem = relative.split("/", 1)[1].removesuffix(".js")
            assert f"'{stem}'" in base, f"{stem} n'est pas chargé par base.html"
