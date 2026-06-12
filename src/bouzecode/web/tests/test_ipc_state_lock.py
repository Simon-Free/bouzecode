# [desc] write_state ne doit jamais lever quand state.json est lu/verrouille par le serveur (WinError 5). [/desc]
"""Bug prod 2026-06-10 : pendant un WritePlan, os.replace(state.tmp -> state.json)
a leve PermissionError (le serveur lisait state.json) et a tue tout le run R1."""
import os

from bouzecode.web import ipc


def test_write_state_survit_au_fichier_verrouille(tmp_path):
    paths = ipc.from_dir(tmp_path)
    ipc.write_state(paths, ipc.STATUS_RUNNING)
    fd = os.open(paths.state, os.O_RDONLY)
    try:
        ipc.write_state(paths, ipc.STATUS_IDLE)  # ne doit pas lever malgre le verrou
    finally:
        os.close(fd)
    ipc.write_state(paths, ipc.STATUS_FINISHED)
    assert ipc.read_state(paths)["status"] == ipc.STATUS_FINISHED


def test_write_state_nominal(tmp_path):
    paths = ipc.from_dir(tmp_path)
    ipc.write_state(paths, ipc.STATUS_RUNNING, turn=3)
    state = ipc.read_state(paths)
    assert state["status"] == ipc.STATUS_RUNNING
    assert state["turn"] == 3
