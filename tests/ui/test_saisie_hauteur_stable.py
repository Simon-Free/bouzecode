# [desc] Regression test checking that the prompt_toolkit input's rendered height stays stable across periodic refreshes [/desc]
"""Reproduit le saut : renderer qui rend max(lignes sous le curseur, dernier ecran, voulue)
et `_retrecir_si_plus_court` qui efface quand la voulue est plus petite -> alternance a
chaque `refresh_interval`. Vraie session prompt_toolkit, ecran vt100 en memoire."""
from __future__ import annotations

import io
import threading
import time

from prompt_toolkit.application import create_app_session
from prompt_toolkit.data_structures import Size
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output.vt100 import Vt100_Output


class _Ecran(Vt100_Output):
    """Terminal 40 x 120 en memoire ; 30 lignes libres sous le curseur (comme Windows)."""

    def __init__(self) -> None:
        super().__init__(io.StringIO(), lambda: Size(rows=40, columns=120), term="xterm",
                         enable_cpr=False)

    def get_rows_below_cursor_position(self) -> int:
        return 30


def test_hauteur_de_la_saisie_stable_entre_deux_rafraichissements():
    from bouzecode.ui.paste_input import _new_session

    hauteurs: list[int] = []
    pret = threading.Event()
    with create_pipe_input() as clavier:
        ecran = _Ecran()

        def saisir():
            with create_app_session(input=clavier, output=ecran):
                session = _new_session(InMemoryHistory(), bottom_toolbar=lambda: "barre agents",
                                       refresh_interval=0.05)

                def noter(app):
                    ecran_rendu = app.renderer._last_screen
                    if ecran_rendu is not None:
                        hauteurs.append(ecran_rendu.height)
                    pret.set()

                session.app.after_render += noter
                session.prompt("> ", default="ligne 1\n\n   \nligne 4")

        fil = threading.Thread(target=saisir, daemon=True)
        fil.start()
        assert pret.wait(10), "la saisie ne s'est jamais rendue"
        fin = time.monotonic() + 1.5
        while time.monotonic() < fin and len(hauteurs) < 15:
            time.sleep(0.05)
        clavier.send_text("\r")
        fil.join(10)

    stables = hauteurs[2:]  # le premier rendu peut precéder la mesure des lignes libres
    assert len(stables) >= 5, f"trop peu de rendus : {hauteurs}"
    assert len(set(stables)) == 1, f"la hauteur saute d'un rendu a l'autre : {hauteurs}"
    assert stables[0] < 15, f"la barre est repoussee en bas de l'ecran : {hauteurs}"
