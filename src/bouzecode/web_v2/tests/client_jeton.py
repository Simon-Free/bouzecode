# [desc] Client de test Flask qui joint le jeton local de l'app à chaque requête (les gardes de securite.py restent actives). [/desc]
"""Le client de test des suites : il envoie `X-Bouzecode-Token` comme le front et les outils.

La garde du jeton n'est PAS désactivée sous test : le client joint simplement le jeton que
l'app a chargé (`app.config["BOUZECODE_TOKEN"]`), sauf si le test pose lui-même l'en-tête
(y compris vide, pour éprouver le 401). Branché par les conftests via `armer(monkeypatch)`.
"""
from __future__ import annotations

from flask import Flask
from flask.testing import FlaskClient

from bouzecode.backend.core.jeton_local import EN_TETE


class ClientAvecJeton(FlaskClient):
    def open(self, *args, **kwargs):
        jeton = self.application.config.get("BOUZECODE_TOKEN")
        en_tetes = kwargs.get("headers")
        deja_pose = en_tetes is not None and EN_TETE in dict(en_tetes)
        if jeton and not deja_pose:
            kwargs["headers"] = {**dict(en_tetes or {}), EN_TETE: jeton}
        return super().open(*args, **kwargs)


def armer(monkeypatch) -> None:
    monkeypatch.setattr(Flask, "test_client_class", ClientAvecJeton)
