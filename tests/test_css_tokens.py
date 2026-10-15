"""Garde anti blanc-sur-blanc : un token CSS inconnu tombe sur son fallback.

Bug constate le 2026-09-07 sur http://127.0.0.1:5056/bureau : `pages.css` ecrivait
`.ligne { background: var(--fond-carte, #fff) }` alors que `--fond-carte` n'est
defini NULLE PART (les tokens du theme vivent dans le `:root` de `app.css`). Le
navigateur applique donc le fallback -- #fff -- comme FOND, sous un texte qui
herite `color: var(--text)` = #f4f4f6. Resultat : blanc sur blanc, la liste du
Bureau etait illisible. Aucune erreur, aucun warning : un token mal orthographie
est un bug de theme SILENCIEUX. Ce test le rend bruyant.

Perimetre volontairement etroit -- le seul motif qui casse la lisibilite :
un token INCONNU dont le fallback est une couleur CLAIRE utilisee comme FOND.
Sont donc tolerees (et ne doivent PAS faire echouer ce test) :
  * `color: var(--warn, #d29922)` -> du texte dore sur fond sombre est lisible ;
  * `var(--r-sm, 8px)`, `var(--mono, Consolas)` -> ni couleur, ni fond ;
  * `background: var(--inconnu, #171a20)` -> fallback SOMBRE, coherent au theme.
Exiger la definition de TOUS les tokens forcerait un refactor de nommage sans
rapport avec la lisibilite.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "src" / "bouzecode" / "web_v2" / "static"

# Definition d'un token : `--nom:` en tete de declaration.
RE_DEF = re.compile(r"(--[A-Za-z0-9_-]+)\s*:")
# Usage avec fallback hexadecimal : var(--nom, #rrggbb)
RE_FALLBACK_HEX = re.compile(r"var\(\s*(--[A-Za-z0-9_-]+)\s*,\s*(#[0-9A-Fa-f]{3,8})\s*\)")
# La declaration est-elle une declaration de FOND ? (`background`, `background-color`)
RE_FOND = re.compile(r"background(-color)?\s*:", re.IGNORECASE)

CLAIR = 0.6  # luminance relative au-dela de laquelle un fond est "clair"

# Les deux tokens fantomes qui ont provoque le bug : ils ne doivent plus JAMAIS
# reapparaitre, meme avec un fallback sombre (ils n'existent pas).
TOKENS_FANTOMES = ("--fond-carte", "--bord")


def _feuilles() -> list[Path]:
    """Les feuilles de style maison (le vendor Monaco ne nous appartient pas)."""
    return sorted(f for f in STATIC.glob("*.css") if "monaco" not in f.name.lower())


def _luminance(hexa: str) -> float:
    """Luminance relative approchee (0 = noir, 1 = blanc) d'une couleur #rgb/#rrggbb."""
    brut = hexa.lstrip("#")
    if len(brut) in (3, 4):
        brut = "".join(c * 2 for c in brut[:3])
    r, v, b = (int(brut[i : i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * v + 0.0722 * b


def _tokens_definis() -> set[str]:
    definis: set[str] = set()
    for feuille in _feuilles():
        definis |= set(RE_DEF.findall(feuille.read_text(encoding="utf-8")))
    return definis


def test_les_feuilles_css_sont_trouvees() -> None:
    """Sans ce garde-fou, un mauvais chemin rendrait les tests verts pour rien."""
    noms = {f.name for f in _feuilles()}
    assert {"app.css", "pages.css"} <= noms, f"CSS introuvables dans {STATIC} : {noms}"


def test_le_theme_definit_bien_ses_tokens_de_base() -> None:
    """Le fond, le texte et les surfaces doivent exister : tout le reste s'y adosse."""
    manquants = {"--bg", "--text", "--panel", "--panel2", "--border"} - _tokens_definis()
    assert not manquants, f"tokens de base absents du :root : {sorted(manquants)}"


@pytest.mark.parametrize("fantome", TOKENS_FANTOMES)
def test_les_tokens_fantomes_du_bureau_ont_disparu(fantome: str) -> None:
    """`--fond-carte` / `--bord` n'ont jamais existe : ils doublonnaient --panel / --border."""
    coupables = []
    for feuille in _feuilles():
        for numero, ligne in enumerate(feuille.read_text(encoding="utf-8").splitlines(), 1):
            # Token EXACT : `var(--bord)` ou `var(--bord,` -- sans quoi `var(--border)` matcherait.
            if f"var({fantome})" in ligne or f"var({fantome}," in ligne:
                coupables.append(f"{feuille.name}:{numero} | {ligne.strip()[:120]}")
    assert not coupables, (
        f"{fantome} n'est defini nulle part : le fallback clair serait applique.\n"
        + "\n".join(coupables)
    )


def test_aucun_fond_clair_derriere_un_token_inconnu() -> None:
    """Le motif exact du blanc-sur-blanc : fond clair peint par le fallback d'un token absent."""
    definis = _tokens_definis()
    fautifs: list[str] = []

    for feuille in _feuilles():
        for numero, ligne in enumerate(feuille.read_text(encoding="utf-8").splitlines(), 1):
            if not RE_FOND.search(ligne):
                continue  # ni background ni background-color : la lisibilite n'est pas en jeu
            for token, hexa in RE_FALLBACK_HEX.findall(ligne):
                if token in definis:
                    continue
                if _luminance(hexa) > CLAIR:
                    fautifs.append(
                        f"{feuille.name}:{numero} -> {token} absent des feuilles, "
                        f"FOND clair {hexa} applique | {ligne.strip()[:120]}"
                    )

    assert not fautifs, (
        "Token(s) inconnu(s) dont le fallback peint un FOND CLAIR : sur le theme "
        "sombre le texte reste var(--text) = #f4f4f6 => illisible.\n" + "\n".join(fautifs)
    )
