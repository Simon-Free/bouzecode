# [desc] Enquête sur une session : frise des tours, tour à la loupe avec diff, histoire de la note, saturation, recherche. [/desc]
"""Service de la vue d'enquête (`/enquete/<agent_id>`). Chaque vue part de `source.charger`,
qui replie la session UNE fois par version des fichiers ; les vues coûteuses sont mémorisées
sur l'objet chargé (`memo`)."""
from .source import charger, oublier  # noqa: F401
