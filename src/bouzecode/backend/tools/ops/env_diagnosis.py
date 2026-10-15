# [desc] Échecs pytest regroupés par signature (type + 1re ligne, chemins et nombres normalisés) et remède d'une ligne pour les signatures d'environnement connues (navigateur Playwright absent, module absent, connexion refusée, port pris, setups à ~2 s). [/desc]
"""Séparer le bruit d'environnement des vrais échecs.

Suite finale du 2026-10-13 : 98 failed + 149 errors, dont 144 fois `BrowserType.launch:
Executable doesn't exist at …chromium_headless_shell-1208…` et ~80 timeouts navigateur ; ~5
échecs seulement venaient du changement. Montrés un par un, les 5 vrais étaient noyés. Ici,
un échec = une signature (type d'exception + première ligne du message, chemins → `<path>`,
nombres → `N`) ; une signature répétée tient sur une ligne. Une signature inconnue n'est pas
interprétée : son extrait part au modèle tel quel, comme avant.
"""
from __future__ import annotations

import re

_TYPE_RE = re.compile(r"^([A-Za-z_][\w.]*): (.*)$")
_CHEMIN_RE = re.compile(r"[A-Za-z]:[\\/][^\s'\"]+|(?<![\w.])/(?:[^\s/'\"]+/)+[^\s'\"]*")
_NOMBRE_RE = re.compile(r"\d+")
_REVISION_RE = re.compile(r"(chromium[\w-]*?-\d+|firefox-\d+|webkit-\d+)")
_DUREE_SETUP_RE = re.compile(r"^(\d+(?:\.\d+)?)s\s+setup\s+\S")

_REMEDES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"Executable doesn't exist at"),
     "navigateur Playwright absent ({revision}) : l'installer (`playwright install`) écrit "
     "des .exe — demande d'abord l'accord de l'utilisateur ; repli sans installation : "
     'channel="msedge".'),
    (re.compile(r"No module named '([^']+)'"),
     "module {module} absent de l'environnement du run : vérifie l'interpréteur et le "
     "PYTHONPATH (src du worktree) avant de toucher au code ; installer dans le venv partagé "
     "demande l'accord de l'utilisateur."),
    (re.compile(r"ConnectionRefused|Connection refused|ECONNREFUSED|WinError 10061|"
                r"ERR_CONNECTION_REFUSED", re.IGNORECASE),
     "connexion refusée : le serveur visé ne tourne pas (ou pas sur ce port) — démarre-le ou "
     "corrige l'URL ; ce n'est pas le code testé."),
    (re.compile(r"Address already in use|WinError 10048|EADDRINUSE|"
                r"only one usage of each socket address", re.IGNORECASE),
     "port déjà pris par un autre process (autre agent, serveur resté ouvert) : port 0 "
     "(libre) ou arrête l'ancien process."),
]


def premiere_erreur(bloc: list[str]) -> str:
    """Première ligne `E ` d'un échec ; sans elle (collecte, crash), sa dernière ligne utile."""
    for ligne in bloc:
        if ligne.startswith("E ") and ligne[1:].strip():
            return ligne[1:].strip()
    utiles = [l.strip() for l in bloc if l.strip() and not l.startswith("-")]
    return utiles[-1] if utiles else ""


def signature(message: str) -> str:
    """`pkg._x.Error: msg` → `pkg Error: msg normalisé` ; chemins `<path>`, nombres `N`."""
    message = " ".join(message.split())
    if m := _TYPE_RE.match(message):
        type_exc, reste = m.groups()
        morceaux = type_exc.split(".")
        type_court = f"{morceaux[0]} {morceaux[-1]}" if len(morceaux) > 1 else type_exc
        message = f"{type_court}: {reste}"
    message = _NOMBRE_RE.sub("N", _CHEMIN_RE.sub("<path>", message))
    return message[:200]


def regrouper(blocs: list[tuple[str, list[str]]]) -> list[tuple[str, str, list]]:
    """[(signature, premier message brut, blocs)] dans l'ordre de première apparition."""
    groupes: dict[str, tuple[str, str, list]] = {}
    for nom, bloc in blocs:
        brut = premiere_erreur(bloc)
        cle = signature(brut)
        groupes.setdefault(cle, (cle, brut, []))[2].append((nom, bloc))
    return list(groupes.values())


def remede(message_brut: str) -> str:
    for motif, texte in _REMEDES:
        if m := motif.search(message_brut):
            revision = _REVISION_RE.search(message_brut)
            return texte.format(revision=revision.group(1) if revision else "révision inconnue",
                                module=m.group(1) if m.groups() else "")
    return ""


def note_setups_a_deux_secondes(lignes_durees: list[str]) -> str:
    """Trois setups ou plus entre 1,9 et 2,3 s : sous Windows, la signature d'une connexion
    refusée (le client TCP réessaie pendant ~2 s avant d'abandonner un port fermé)."""
    durees = [float(m.group(1)) for l in lignes_durees if (m := _DUREE_SETUP_RE.match(l.strip()))]
    proches = [d for d in durees if 1.9 <= d <= 2.3]
    if len(proches) < 3:
        return ""
    return (f"env : {len(proches)} setups à ~2 s — sous Windows, signature d'une connexion "
            f"refusée (réessai TCP vers un port fermé) : vérifie que le serveur attendu tourne.")


def _id_exemple(nom: str, ids: list[str]) -> str:
    """Titre de bloc pytest (`TestX.test_y[p]`, `ERROR at setup of test_y`) → id du résumé."""
    court = re.sub(r"^ERROR (?:at (?:setup|teardown) of|collecting) ", "", nom).replace(".", "::")
    return next((i for i in ids if i == court or i.endswith("::" + court)), court)


def rendu_groupes(groupes: list[tuple[str, str, list]], ids: list[str],
                  lignes_durees: list[str]) -> str:
    """Section « échecs regroupés », ou '' si rien n'est répété ni reconnu."""
    lignes, utile = [], False
    for cle, brut, blocs in groupes:
        texte_remede = remede(brut)
        utile = utile or len(blocs) > 1 or bool(texte_remede)
        lignes.append(f"{len(blocs)} × {cle} (e.g. {_id_exemple(blocs[0][0], ids)})")
        if texte_remede:
            lignes.append(f"  env : {texte_remede}")
    note = note_setups_a_deux_secondes(lignes_durees)
    if not utile and not note:
        return ""
    total = sum(len(b) for _, _, b in groupes)
    return "\n".join([f"échecs regroupés ({total} en {len(groupes)} signatures) :", *lignes,
                      *([note] if note else [])])
