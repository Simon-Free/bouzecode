"""Telechargement (Artifactory, sans proxy) et deballage des paquets npm brotli et conda (.conda/zstd).

La decompression brotli/zstd s'execute avec le Python du venv outils (ou ces modules sont installes) ;
ce module-ci reste en stdlib pour etre lance par le python3.11 systeme de la VM.
"""
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path

DECOMPRESSER_BROTLI = (
    "import brotli,sys;open(sys.argv[2],'wb').write(brotli.decompress(open(sys.argv[1],'rb').read()))")
DEBALLER_CONDA = """import sys, tarfile, zipfile, zstandard
with zipfile.ZipFile(sys.argv[1]) as archive:
    nom = next(n for n in archive.namelist() if n.startswith("pkg-") and n.endswith(".tar.zst"))
    with archive.open(nom) as flux, zstandard.ZstdDecompressor().stream_reader(flux) as tar_flux:
        with tarfile.open(fileobj=tar_flux, mode="r|") as tar:
            tar.extractall(sys.argv[2], filter="data")
"""


def telecharger(url: str, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    ouvreur = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with ouvreur.open(url, timeout=300) as reponse, open(destination, "wb") as sortie:
        shutil.copyfileobj(reponse, sortie)
    return destination


def deballer_chromium(python: str, url: str, destination: Path) -> Path:
    archive = telecharger(url, destination / "paquet.tgz")
    with tarfile.open(archive) as tar:
        membre = tar.getmember("package/bin/chromium.br")
        tar.extractall(destination, members=[membre], filter="data")
    executable = destination / "chromium"
    subprocess.run([python, "-c", DECOMPRESSER_BROTLI, str(destination / "package" / "bin" / "chromium.br"),
                    str(executable)], check=True)
    executable.chmod(0o755)
    shutil.rmtree(destination / "package")
    archive.unlink()
    return executable


def deballer_conda(python: str, url: str, destination: Path) -> None:
    archive = telecharger(url, destination / ".telechargements" / url.rsplit("/", 1)[1])
    subprocess.run([python, "-c", DEBALLER_CONDA, str(archive), str(destination)], check=True)
    archive.unlink()
