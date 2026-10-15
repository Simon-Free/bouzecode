# [desc] Lit/ecrit le contexte perso (user-level) injecte dans le system prompt de l'assistant du Bureau.
#
# Le fichier vise est EXACTEMENT celui que la couche additive de
# backend/core/profile_extra.py concatene au prompt : ~/.bouzecode/profiles/bureau-assistant.local.md.
# Un seul module connait ce chemin, pour que l'UI et l'agent ne puissent pas divergere. [/desc]
"""Le contexte perso de l'assistant du Bureau, editable depuis l'UI.

Demande utilisateur du 2026-09-21 : « je voudrais pouvoir enrichir le system prompt de mon
assistant pour lui signaler des elements de contexte qu'il ne possede pas, pour mon usage
perso, donc par user, pas dans le code ».

Le profil `bureau-assistant` est SHIPPÉ dans la wheel (il porte aussi la tool allowlist
restrictive qui empeche l'assistant de coder). On ne le surcharge donc pas par nom : on lui
ajoute une couche purement ADDITIVE, un markdown pose a cote de lui dans le dossier de
configuration de l'utilisateur. `backend/core/profile_extra.py` le concatene EN DERNIER a la
prose composee ; ce module est le seul endroit du serveur web qui en connait le chemin.
"""
from __future__ import annotations

from pathlib import Path

#  Profil de l'assistant du Bureau (meme valeur que routes/work/bureau_v2.TYPOLOGIE_ASSISTANT).
PROFIL_ASSISTANT = "bureau-assistant"

#  Suffixe reconnu par backend/core/profile_extra._load_local_prose : `<profil>.local.md`.
SUFFIXE_LOCAL = ".local.md"


def chemin_contexte(profil: str = PROFIL_ASSISTANT) -> Path:
    """Chemin du markdown de contexte perso pour ce profil.

    Import TARDIF de `config` : `CONFIG_DIR` doit etre relu A L'APPEL, sinon un test qui le
    redirige vers un tmp_path (monkeypatch du module) ecrirait dans le vrai ~/.bouzecode.
    """
    from bouzecode.backend.core import config

    return Path(config.CONFIG_DIR) / "profiles" / f"{profil}{SUFFIXE_LOCAL}"


def lire_contexte(profil: str = PROFIL_ASSISTANT) -> str:
    """Le contexte perso, ou "" s'il n'existe pas encore.

    `utf-8-sig` : un fichier edite au Notepad Windows commence par un BOM, qui polluerait
    la premiere ligne du prompt. Toute erreur disque rend "" — l'edition du contexte est un
    CONFORT, elle ne doit jamais casser le tiroir de l'assistant.
    """
    try:
        return chemin_contexte(profil).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return ""


def ecrire_contexte(contenu: str, profil: str = PROFIL_ASSISTANT) -> Path:
    """Ecrit le contexte perso et rend le chemin ecrit.

    Normalise les fins de ligne (le textarea du navigateur envoie du CRLF sous Windows) et
    retire les blancs de bord : un contenu vide laisse un fichier vide, que la couche
    additive ignore alors purement et simplement (aucun en-tete parasite dans le prompt).
    """
    chemin = chemin_contexte(profil)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    texte = (contenu or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    chemin.write_text(texte + "\n" if texte else "", encoding="utf-8")
    return chemin
