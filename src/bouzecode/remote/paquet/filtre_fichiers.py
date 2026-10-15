"""Tri des fichiers non suivis demandes : ce qui peut partir sur la VM, ce qui est refuse et pourquoi.

Refus systematiques : secrets (`.env*`, cles, certificats, magasins d'identifiants), executables
Windows (`.exe`, `.dll`, `.msi`), liens symboliques, chemins qui sortent du depot, fichiers
absents et fichiers plus gros que le seuil (configurable, 20 Mo par defaut).
"""
import fnmatch
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

SEUIL_OCTETS_DEFAUT = 20 * 1024 * 1024

MOTIFS_SECRETS = (
    ".env", ".env.*", "*.env", "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.kdbx", "*.ppk",
    "id_rsa*", "id_ed25519*", "id_ecdsa*", ".netrc", ".npmrc", ".pypirc", ".git-credentials",
    "credentials*", "*secret*", "*.token",
)
EXTENSIONS_BINAIRES_INTERDITES = (".exe", ".dll", ".msi", ".bat", ".cmd", ".scr")


@dataclass
class TriFichiers:
    acceptes: list[str] = field(default_factory=list)
    refuses: list[dict] = field(default_factory=list)

    def refuser(self, chemin: str, raison: str) -> None:
        self.refuses.append({"chemin": chemin, "raison": raison})


def raison_de_refus(depot: Path, chemin_relatif: str, seuil_octets: int) -> str | None:
    relatif = PurePosixPath(chemin_relatif.replace("\\", "/"))
    if relatif.is_absolute() or ".." in relatif.parts or not relatif.parts:
        return "chemin hors du depot"
    if ".git" in relatif.parts:
        return "contenu interne git"
    nom = relatif.name.lower()
    if any(fnmatch.fnmatch(nom, motif) for motif in MOTIFS_SECRETS):
        return "secret potentiel"
    if nom.endswith(EXTENSIONS_BINAIRES_INTERDITES):
        return "executable interdit"
    absolu = depot / Path(*relatif.parts)
    if absolu.is_symlink():
        return "lien symbolique"
    if not absolu.is_file():
        return "fichier absent"
    if absolu.stat().st_size > seuil_octets:
        return f"trop gros (> {seuil_octets} octets)"
    return None


def trier_fichiers_non_suivis(depot: Path, chemins: list[str], seuil_octets: int = SEUIL_OCTETS_DEFAUT) -> TriFichiers:
    tri = TriFichiers()
    for chemin in chemins:
        raison = raison_de_refus(depot, chemin, seuil_octets)
        if raison:
            tri.refuser(chemin, raison)
        else:
            tri.acceptes.append(PurePosixPath(chemin.replace("\\", "/")).as_posix())
    return tri
