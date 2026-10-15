# [desc] Une image dans un résultat d'outil devient un fichier + une ligne (chemin, taille, poids, mode d'emploi ImageQuestion) ; jamais de base64 en texte. [/desc]
"""Référence d'image : ce que le modèle voit à la place d'une image.

Rapport docs/reduction_tokens §4 : une capture Chrome MCP partait en `str(dict)` (70 à 180 k
tokens de base64 en texte) et un `Read` d'image sur OpenRouter en base64 brut. Désormais une
image n'entre JAMAIS dans un résultat d'outil : elle est écrite dans un fichier du dossier
temporaire de l'agent, et le résultat tient en une ligne. Pour la regarder, l'agent pose une
question fermée à `ImageQuestion`, qui la montre à un modèle dans un appel annexe.
"""
from __future__ import annotations

import base64
import hashlib
import struct
from pathlib import Path

_EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
               "image/webp": ".webp", "image/bmp": ".bmp"}
MIMES = {ext: mime for mime, ext in _EXTENSIONS.items()} | {".jpeg": "image/jpeg"}


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            return None
        marker, longueur = data[i + 1], struct.unpack(">H", data[i + 2:i + 4])[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        i += 2 + longueur
    return None


def _webp_size(data: bytes) -> tuple[int, int] | None:
    chunk = data[12:16]
    if chunk == b"VP8X":
        return 1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little")
    if chunk == b"VP8 ":
        w, h = struct.unpack("<HH", data[26:30])
        return w & 0x3FFF, h & 0x3FFF
    if chunk == b"VP8L":
        bits = int.from_bytes(data[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    return None


def dimensions(data: bytes) -> tuple[int, int] | None:
    """(largeur, hauteur) lue dans l'en-tête PNG / JPEG / GIF / WebP / BMP, sans Pillow."""
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", data[16:24])
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return struct.unpack("<HH", data[6:10])
        if data[:2] == b"\xff\xd8":
            return _jpeg_size(data)
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return _webp_size(data)
        if data[:2] == b"BM":
            w, h = struct.unpack("<ii", data[18:26])
            return w, abs(h)
    except struct.error:
        return None
    return None


def ligne_image(path: str, data: bytes, libelle: str = "image") -> str:
    """`[<libelle> : <chemin>, WxH, N ko. Pour l'examiner : ImageQuestion(...)]`."""
    taille = dimensions(data)
    geometrie = f"{taille[0]}x{taille[1]}" if taille else "dimensions inconnues"
    ko = max(1, round(len(data) / 1024))
    return (f'[{libelle} : {path}, {geometrie}, {ko} ko. Pour l\'examiner : '
            f'ImageQuestion(paths=["{path}"], question="…")]')


def enregistrer(data: bytes, mime: str, prefixe: str = "capture") -> str:
    """Écrit l'image dans le dossier temporaire de l'agent (détruit en fin de session)."""
    from .scratch import _get_scratch_dir

    dossier = _get_scratch_dir() / "images"
    dossier.mkdir(parents=True, exist_ok=True)
    nom = f"{prefixe}_{hashlib.sha1(data).hexdigest()[:10]}{_EXTENSIONS.get(mime, '.png')}"
    chemin = dossier / nom
    chemin.write_bytes(data)
    return str(chemin)


def depuis_base64(b64: str, mime: str, prefixe: str = "capture") -> str:
    """Bloc image MCP (`{"type": "image", "data": b64, "mimeType": …}`) → une ligne."""
    try:
        data = base64.b64decode(b64 or "", validate=False)
    except (ValueError, TypeError):
        return f"[{prefixe} illisible : données base64 invalides]"
    chemin = enregistrer(data, mime or "image/png", prefixe)
    return ligne_image(chemin, data, "capture enregistrée")


def lire(path: Path) -> str:
    """Résultat de `Read` sur un fichier image : la ligne, pas le contenu."""
    try:
        data = path.read_bytes()
    except OSError as e:
        return f"Error: {e}"
    return ligne_image(str(path), data, "image")
