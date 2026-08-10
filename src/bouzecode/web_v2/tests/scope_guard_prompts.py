# [desc] Six prompts d'un même manager : 3 rédactions d'un MÊME livrable, 3 d'un autre. [/desc]
"""Six prompts enfants tels qu'un manager en dispatche, sur un projet de démonstration.

Le jeu est construit pour reproduire la situation que le garde-fou doit voir : trois prompts
(`DIRECTE_*`) demandent EXACTEMENT le même livrable — c'est le doublon à détecter. Les trois
autres (`INDIRECTE_*`) portent sur l'autre moitié de la demande, et aucun n'implémente : c'est
le trou de couverture. Les portions purement « règles projet » sont conservées à l'identique
dans les six, car c'est justement ce texte commun qui piège une similarité naïve.
"""

_REGLES = (
    "RÈGLES PROJET STRICTES : tests AVANT correctif puis re-run ; INTERDIT "
    "unittest.mock.patch/@patch/MagicMock ; pas de try/except qui se contente de logger ; "
    "fichiers < 200 lignes ; max 5 fichiers par dossier avec un README par dossier créé ; "
    "`uv run` (jamais Poetry) ; pas de pip install -e. NE DÉPLOIE PAS. "
    "Termine par `VERDICT: OK` ou `VERDICT: KO` avec la raison."
)

DIRECTE_B = f"""TICKET B — MESURE DIRECTE Wiki (ÉCRIVAIN). Suite du cadrage précédent.
Repo : /home/dev/demo_app
App concernée : src/apps/wiki/
OBJECTIF : compter les ouvertures RÉELLES d'un .md dans le Wiki. Le seul point serveur qui
voit un fichier ouvert est la route `GET /api/file`.
À IMPLÉMENTER :
1. Nouvelle table `docs.article_views`. PIÈGE #3 : toute nouvelle table du schéma `docs.`
   DOIT recevoir un GRANT PUBLIC dès sa création (migration), sinon l'app répond 500 en PROD.
2. Hook sur la route `GET /api/file` pour enregistrer l'ouverture d'un .md.
PIÈGE #1 CONFIDENTIALITÉ : compteurs AGRÉGÉS, sans historique de lecture nominatif.
PIÈGE #2 NE PAS COMPTER L'ASSISTANT COMME LECTEUR HUMAIN : la route `GET /api/file` est aussi
appelée par l'assistant lui-même (src/apps/chatbot/) ; distingue navigation humaine et accès
machine.
LIVRABLE : migration table + GRANT PUBLIC + hook /api/file filtrant l'accès machine.
{_REGLES}"""

DIRECTE_IMPLEMENTATION = f"""MISSION IMPLÉMENTATION — ticket B : MESURE DIRECTE des
ouvertures de .md dans le Wiki.
Repo : /home/dev/demo_app — App : src/apps/wiki/
OBJECTIF : compter les ouvertures RÉELLES d'un fichier .md. Le seul point serveur qui voit un
fichier ouvert est la route `GET /api/file`. Il faut :
1. Créer une nouvelle table `docs.article_views` pour stocker les compteurs de vues.
2. Poser un hook sur la route `GET /api/file` qui incrémente le compteur quand un .md est ouvert.
PIÈGE #1 CONFIDENTIALITÉ : compteurs AGRÉGÉS par document, SANS historique nominatif.
PIÈGE #2 NE COMPTE PAS L'ASSISTANT COMME UN LECTEUR HUMAIN : grep les appelants côté assistant
src/apps/chatbot/ et distingue navigation humaine vs accès machine.
PIÈGE #3 GRANT sur les tables `docs.*` : GRANT PUBLIC dès la création, sinon 500 en PRODUCTION.
LIVRABLE : migration table `docs.article_views` avec GRANT PUBLIC, hook sur GET /api/file.
{_REGLES}"""

DIRECTE_ECRIVAIN = f"""MISSION (ÉCRIVAIN) : implémenter la "mesure directe" d'usage des .md
dans le Wiki = compter les ouvertures RÉELLES d'un fichier .md.
Repo : /home/dev/demo_app, app src/apps/wiki/.
- Le seul point serveur qui voit un fichier ouvert est la route `GET /api/file`.
- Il faut une nouvelle table `docs.article_views` + un hook sur cette route qui enregistre
  l'ouverture.
1. GRANT : toute nouvelle table créée dans le schéma `docs.` DOIT recevoir un GRANT PUBLIC
   DÈS SA CRÉATION (migration), sinon l'app répond 500 en prod.
2. CONFIDENTIALITÉ : compteurs AGRÉGÉS, SANS historique de lecture nominatif.
3. NE PAS COMPTER L'ASSISTANT COMME LECTEUR HUMAIN : la route `GET /api/file` est aussi appelée
   par l'assistant lui-même ; distingue la navigation humaine de l'accès machine.
LIVRABLE : la table + le hook fonctionnels, comptage agrégé fiable excluant l'assistant.
{_REGLES}"""

INDIRECTE_TICKET_A = f"""TICKET A — INVESTIGATION (READ-ONLY, aucune écriture de code produit).
Repo : /home/dev/demo_app — App : src/apps/chatbot/
OBJECTIF : mesurer la FIABILITÉ du matching entre le champ `sources` des réponses de
l'assistant et les fichiers .md réels, AVANT qu'on code la mesure indirecte.
CONTEXTE : l'assistant stocke chaque réponse dans la table `chat.conversations`, colonne `data`
(JSONB), avec un champ `sources` par message. Ce `sources` est une CHAÎNE LIBRE produite par
l'agent LLM, PAS forcément un chemin .md exact.
TÂCHES : échantillonne les valeurs `sources` réelles en base ; recense les .md existants ;
MESURE quelle PROPORTION se rattache de façon FIABLE à un .md existant (match exact, match
approximatif basename, non-matchable) ; RENDS LE CHIFFRE explicitement.
CONTRAINTE : READ-ONLY. Ne crée AUCUNE table, ne modifie AUCUN fichier de code produit.
{_REGLES}"""

INDIRECTE_READ_ONLY = f"""MISSION READ-ONLY (aucune écriture de code/fichier de production) —
INVESTIGATION préalable, ticket A.
Repo : /home/dev/demo_app — App : src/apps/chatbot/
CONTEXTE : l'assistant stocke chaque réponse dans la table `chat.conversations`, colonne `data`
(JSONB), avec un champ `sources` par message. RÉSERVE : `sources` est une CHAÎNE LIBRE.
CE QUE TU DOIS FAIRE : localiser comment l'assistant écrit `sources` ; échantillonner les VRAIES
valeurs en base réelle ; mesurer la PROPORTION qui se rattache de façon FIABLE à un fichier
.md existant du Wiki ; RENDRE LE CHIFFRE (% et stratégie de matching).
Pas d'implémentation de la mesure, c'est un autre ticket.
{_REGLES}"""

INDIRECTE_BLOQUANTE = f"""MISSION READ-ONLY (aucune écriture de code produit, aucune
migration) : investigation préalable BLOQUANTE avant d'implémenter la "mesure indirecte".
Repo : /home/dev/demo_app (src/apps/chatbot/).
CONTEXTE : l'assistant stocke chaque réponse dans `chat.conversations`, colonne `data` (JSONB),
avec un champ `sources` par message. `sources` est une CHAÎNE LIBRE produite par l'agent LLM.
CE QUE TU DOIS FAIRE : échantillonner les vraies valeurs du champ `sources` sur la base
réelle ; mesurer QUANTITATIVEMENT la proportion qui se rattache à un fichier .md EXISTANT ;
expliciter la règle de matching (exact path, basename, fuzzy) et donner le taux.
Tu peux écrire des scripts d'investigation JETABLES uniquement. N'introduis AUCUN fichier tracké.
{_REGLES}"""

MESURE_DIRECTE = (DIRECTE_B, DIRECTE_IMPLEMENTATION, DIRECTE_ECRIVAIN)
MESURE_INDIRECTE = (INDIRECTE_TICKET_A, INDIRECTE_READ_ONLY, INDIRECTE_BLOQUANTE)
