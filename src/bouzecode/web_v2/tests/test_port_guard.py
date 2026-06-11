# [desc] Le serveur web_v2 doit refuser de demarrer si une instance ecoute deja sur le port. [/desc]
"""Bug prod 2026-06-10 : SO_REUSEADDR du dev server Flask permet deux instances
web_v2 simultanées sur 5056 sous Windows — POSTs servis aléatoirement par l'une
ou l'autre (env socle différent → agents fantômes 'No API key'), courses sur
index_cache.tmp."""
import socket

import pytest

from bouzecode.web_v2.app import fail_if_port_taken


def test_port_libre_ne_leve_pas():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
    fail_if_port_taken("127.0.0.1", free_port)


def test_port_occupe_refuse_le_demarrage():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
        holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        port = holder.getsockname()[1]
        with pytest.raises(SystemExit, match=str(port)):
            fail_if_port_taken("127.0.0.1", port)
