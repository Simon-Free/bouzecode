# [desc] Rendu de la barre des agents (une ligne par agent, facon Claude Code) en texte brut et en fragments prompt_toolkit : icone d'etat, type, description, conso, duree. [/desc]
"""`● main` puis `◯ ▶ general-purpose  description  cache now 9.5k · in 12.3k · fresh 4.3k · c-read 8.0k · out 1.2k · 0.04 $  1m 3s`.

`●` marque l'agent affiche, `◯` les autres ; l'icone d'etat (▶ ? ✓ ✗ ■) dit l'etat sans
couleur ; les petits-enfants sont indentes ; `❯` marque la selection quand la liste a le focus.
Une ligne trop large garde sa tete fixe et fait defiler le reste (cf. defilement.py).
"""
from __future__ import annotations

import time

from bouzecode.backend.multi_agent.en_process.fiche import PRINCIPAL, FicheAgent

from .defilement import fenetre

AIDE_FOCUS = "↑/↓ choisir · Entrée ouvrir · x interrompre · Échap revenir à main"
AIDE_VUE = "Échap revenir à main · ↓ (saisie vide) agents · Ctrl+X interrompre cet agent"

_STYLES = {"question": "class:barre.question", "erreur": "class:barre.erreur",
           "fini": "class:barre.fini", "annule": "class:barre.annule"}


def compacter(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def duree(secondes: float) -> str:
    s = int(secondes)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60}s"
    return f"{s // 3600}h {s % 3600 // 60}m"


def cache_now(fiche: FicheAgent, maintenant: float) -> str:
    """Taille du prefixe en cache apres le DERNIER appel (pas un cumul), « (expiré) » passe
    le TTL du fil ; "" sans appel avec cache."""
    cache = fiche.cache_courant()
    if cache is None:
        return ""
    return f"cache now {compacter(cache.tokens)}" + (" (expiré)" if cache.expire(maintenant) else "")


def conso(fiche: FicheAgent, maintenant: float | None = None) -> str:
    """`cache now` (etat courant), l'entree totale (tout le prompt envoye, cache lu compris),
    puis les cumuls de la vie de l'agent en composantes DISJOINTES : entree fraiche, cache lu, cache ecrit (omis a 0), sortie, cout. `entree`
    comprend l'ecriture de cache, pas la lecture (cf. registry.fresh_input_tokens)."""
    from bouzecode.backend.agent.providers.registry import fresh_input_tokens
    t = fiche.tokens()
    if not any(t.values()):
        return ""
    courant = cache_now(fiche, maintenant or time.time())
    morceaux = [courant] if courant else []
    morceaux.append(f"in {compacter(t['entree'] + t['cache_lu'])}")
    morceaux.append(f"fresh {compacter(fresh_input_tokens(t['entree'], t['cache_ecrit']))}")
    if t["cache_lu"]:
        morceaux.append(f"c-read {compacter(t['cache_lu'])}")
    if t["cache_ecrit"]:
        morceaux.append(f"c-write {compacter(t['cache_ecrit'])}")
    morceaux.append(f"out {compacter(t['sortie'])}")
    cout = fiche.cout()
    morceaux.append(f"{cout:.2f} $" if cout is not None else "? $")
    return " · ".join(morceaux)


def ligne(fiche: FicheAgent, nav, largeur_type: int, largeur: int, selectionnee: bool,
          maintenant: float) -> str:
    """Tete fixe (curseur, puce, icone, type) puis les details ; trop larges, les details
    DEFILENT (defilement.fenetre) au lieu d'etre tronques : toute la conso finit par passer."""
    curseur = "❯ " if selectionnee else "  "
    puce = "●" if fiche.id == nav.vue else "◯"
    if fiche.id == PRINCIPAL:
        tete, gauche, droite = f"{curseur}{puce} main", conso(fiche, maintenant), ""
    else:
        retrait = "  " * max(0, fiche.profondeur - 1)
        tete = f"{curseur}{retrait}{puce} {fiche.icone} {fiche.type_agent:<{largeur_type}}"
        #  Outil en cours ; s'il rend une progression (pytest n/N), elle tient sa place.
        en_cours = getattr(fiche, "progression", "") or fiche.activite
        activite = f" [{en_cours}]" if fiche.activite and fiche.actif else ""
        alerte = f"  ⚑ {fiche.alertes[-1]}" if fiche.alertes else ""
        gauche = " ".join(fiche.description.split()) + activite + alerte
        droite = "  ".join(x for x in (conso(fiche, maintenant), duree(fiche.duree(maintenant))) if x)
    if not gauche and not droite:
        return tete
    tete += "  "
    place = largeur - len(tete)
    if len(gauche) + 2 + len(droite) <= place:
        #  Tout tient : conso et duree calees a droite, comme les durees de Claude Code.
        return (tete + gauche + " " * max(2, place - len(gauche) - len(droite)) + droite).rstrip()
    details = "  ".join(x for x in (gauche, droite) if x)
    return (tete + fenetre(details, place, maintenant)).rstrip()


FENETRE = 5   # sous-agents visibles a la fois ; au-dela, fleches ▲/▼ et defilement


def ordre(registre) -> list[FicheAgent]:
    """main, puis les sous-agents en cours, puis l'historique (fini, erreur, annule)."""
    arbre = registre.arbre()
    principal = [f for f in arbre if f.id == PRINCIPAL]
    sous = [f for f in arbre if f.id != PRINCIPAL]
    return principal + [f for f in sous if f.actif] + [f for f in sous if not f.actif]


def lignes(registre, nav, largeur: int = 100, maintenant: float | None = None) -> list[tuple[str, str]]:
    """(style, texte) par ligne ; [] sans sous-agent (barre repliee)."""
    agents = ordre(registre)
    if len(agents) < 2:
        return []
    maintenant = maintenant or time.time()
    sous = agents[1:]
    largeur_type = max(len(f.type_agent) for f in sous)
    nb_actifs = sum(1 for f in sous if f.actif)
    debut = nav.cadrer(len(sous), FENETRE)
    fin = min(len(sous), debut + FENETRE)

    def rendre(index: int, fiche: FicheAgent) -> tuple[str, str]:
        selectionnee = nav.focus and index == nav.selection
        texte = ligne(fiche, nav, largeur_type, largeur, selectionnee, maintenant)
        return ("class:barre.selection" if selectionnee else _STYLES.get(fiche.etat, "")), texte

    rendu = [rendre(0, agents[0])]
    if debut:
        rendu.append(("class:barre.aide", f"  ▲ {debut} de plus"))
    for k in range(debut, fin):
        if k >= nb_actifs and (k == nb_actifs or k == debut):
            rendu.append(("class:barre.aide", f"  ── historique ({len(sous) - nb_actifs}) ──"))
        rendu.append(rendre(k + 1, sous[k]))
    if len(sous) > fin:
        rendu.append(("class:barre.aide", f"  ▼ {len(sous) - fin} de plus"))
    aide = AIDE_FOCUS if nav.focus else (AIDE_VUE if nav.vue != PRINCIPAL else "")
    if aide:
        rendu.append(("class:barre.aide", "  " + aide))
    return rendu


def texte(registre, nav, largeur: int = 100, maintenant: float | None = None) -> str:
    return "\n".join(t for _style, t in lignes(registre, nav, largeur, maintenant))


def fragments(registre, nav, largeur: int = 100) -> list[tuple[str, str]]:
    sortie: list[tuple[str, str]] = []
    for style, t in lignes(registre, nav, largeur):
        sortie += [(style, t), ("", "\n")]
    return sortie[:-1]


# ── Pied du rendu de main (spinner, texte en direct, reflexion) ──────────────
#  Pendant un tour de main, l'invite prompt_toolkit n'est pas affichee : la barre est alors
#  dessinee SOUS la ligne vivante par spinner.py / rendering.py. Sans source (pas de TUI
#  interactif) ou sans sous-agent, rien ne change : aucune ligne, aucune sequence en plus.
EFFACER_BLOC = "\r\x1b[J"  # debut de ligne + effacement jusqu'en bas de l'ecran

_source_pied = None
_pied_dessine = False


def definir_pied(source) -> None:
    """`source()` rend les lignes de la barre ([] = repliee) ; None la retire."""
    global _source_pied
    _source_pied = source


def lignes_pied() -> list[str]:
    if _source_pied is None:
        return []
    import shutil
    largeur = max(20, shutil.get_terminal_size((100, 24)).columns - 1)
    return [ligne_[:largeur] for ligne_ in _source_pied()]


def bloc_pied() -> str:
    """Les lignes de la barre SOUS la ligne courante, curseur ramene au debut de celle-ci."""
    global _pied_dessine
    lignes_ = lignes_pied()
    _pied_dessine = bool(lignes_)
    if not lignes_:
        return ""
    return "\n" + "\n".join(lignes_) + f"\x1b[{len(lignes_)}A\r"


def effacement(par_defaut: str) -> str:
    """Ce qui efface la ligne vivante : le bloc entier si la barre est dessinee dessous."""
    global _pied_dessine
    if _pied_dessine:
        _pied_dessine = False
        return EFFACER_BLOC
    return par_defaut


def avec_pied(rendu_rich):
    """Le texte en cours de main + la barre en pied du MEME `rich.Live` (meme cadence)."""
    lignes_ = lignes_pied()
    if not lignes_:
        return rendu_rich
    from rich.console import Group
    from rich.text import Text
    return Group(rendu_rich, Text("\n".join(lignes_), style="dim"))


_pensee: list[str] = []


def penser(morceau: str, ecrire) -> bool:
    """Reflexion de main avec la barre dessous : seules les lignes COMPLETES sont ecrites
    (au-dessus de la barre, redessinee apres chacune). False = pas de barre, l'appelant
    ecrit comme avant."""
    if not _pensee and not lignes_pied():
        return False
    _pensee.append(morceau)
    *completes, reste = "".join(_pensee).split("\n")
    _pensee[:] = [reste]
    if completes:
        texte = "\n".join(f"\033[3;2m{ligne_}\033[0m" for ligne_ in completes)
        ecrire(f"{EFFACER_BLOC}{texte}\n{bloc_pied()}")
    return True


def fin_de_pensee(ecrire) -> None:
    """Fin du bloc de reflexion : la ligne entamee est ecrite, la barre effacee."""
    reste = "".join(_pensee)
    _pensee.clear()
    ecrire(effacement("") + (f"\033[3;2m{reste}" if reste else ""))
