# [desc] Compression gzip des réponses dynamiques (JSON, HTML, texte) quand le navigateur l'accepte. [/desc]
"""Les réponses de l'API partent compressées si le client annonce `Accept-Encoding: gzip`.

Mesuré sur le poste d'essai : l'ouverture d'un agent (`/blocks?after=0`) envoyait 2,4 Mo de
HTML dans du JSON, `/api/lignes` 0,23 Mo (2,4 Mo sous Windows) — du texte très redondant que
gzip divise par 5 à 10. Bibliothèque standard seulement (pas de Flask-Compress).

Ne sont PAS compressées : les réponses en flux ou en passthrough (fichiers statiques servis par
`send_file`, qui ont leur propre cache), celles qui portent déjà un encodage, les petites
(< 1 Ko : l'en-tête coûterait plus que le gain) et les statuts autres que 200. Un ETag fort
devient faible : la représentation compressée n'est pas octet pour octet celle qui l'a produit.
"""
from __future__ import annotations

import gzip

from flask import Flask, Response, request

TAILLE_MIN = 1024
#  Niveau 1 : le serveur tourne le plus souvent sur le poste même (localhost), où c'est le
#  temps CPU qui compte. Mesuré sur 2,4 Mo de /blocks : ÷3,5 en 19 ms, contre ÷4,4 en 36 ms
#  au niveau 5 ; /api/lignes (0,23 Mo) : ÷3,8 en 1,6 ms.
NIVEAU = 1
TYPES = frozenset({"application/json", "text/html", "text/plain", "text/css",
                   "application/javascript", "text/javascript", "image/svg+xml"})


def _accepte_gzip() -> bool:
    return "gzip" in (request.headers.get("Accept-Encoding") or "").lower()


def compresser(response: Response) -> Response:
    if (response.status_code != 200 or response.direct_passthrough or response.is_streamed
            or "Content-Encoding" in response.headers or response.mimetype not in TYPES
            or not _accepte_gzip()):
        return response
    corps = response.get_data()
    if len(corps) < TAILLE_MIN:
        return response
    response.set_data(gzip.compress(corps, compresslevel=NIVEAU, mtime=0))
    response.headers["Content-Encoding"] = "gzip"
    response.vary.add("Accept-Encoding")
    etag, faible = response.get_etag()
    if etag and not faible:
        response.set_etag(etag, weak=True)
    return response


def installer(app: Flask) -> None:
    app.after_request(compresser)
