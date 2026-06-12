# Cahier des charges — BouzéqUI v2

## Le user et son produit

L'utilisateur pilote des agents bouzecode sur plusieurs projets. Son quotidien :
il **shoote des tickets**, laisse tourner, et revient. À son retour il a besoin de
répondre en 10 secondes à : *où dois-je agir ?* Puis, ticket par ticket : *le travail
est-il bon ?* Et quand un agent a ramé : *où est passé le temps et les tokens ?*

## Parcours utilisateurs

**P1 — Tour de contrôle.** J'ouvre `/`. Je vois mes projets, chacun avec ses compteurs :
agents en cours, questions en attente de réponse, tickets à relire, validations KO.
Je clique le projet qui a un badge orange → je tombe sur la page projet, section
« actions requises » en tête. *(Critère : zéro navigation pour savoir où agir.)*

**P2 — Shooter un ticket.** Sur la page projet : titre + prompt + modèle (menu
déroulant alimenté par le registry) → « Créer & lancer ». Le ticket apparaît « en
cours » avec son run. *(Critère : < 15 s entre l'idée et l'agent lancé.)*

**P3 — Relire un résultat.** Ticket « à relire » → lien vers la session : conversation,
onglet **Fichiers modifiés** (diffs colorés). Je commente le ticket (« # TODO renomme X »,
« refais la partie Y ») → « Envoyer au modèle » relance l'agent avec mon commentaire.
Ou je coche « terminé ». *(Critère : la boucle relecture → correction ne quitte pas la page.)*

**P4 — Valider (CI/CD léger).** Sur le ticket : boutons « Valider : tests » et
« Valider : refacto ». Chacun lance un agent vérificateur dans le cwd du projet qui
termine par `VERDICT: OK|KO`. Le verdict s'affiche en badge sur le ticket et remonte
dans les compteurs projet. *(Critère : verdict lisible sans ouvrir la session.)*

**P5 — Autopsie d'une session lente.** Session → onglet **Tours** : un tableau par appel
LLM — heure, Δ durée, tokens in/out, cache lu/écrit, % de cache hit, outils appelés, coût.
Je repère le tour anormal (Δ long, cache hit bas) → clic → drill-down : le payload exact
envoyé, item par item (system / user / assistant / tool result), chacun étiqueté
**cached / new-cache / fresh** avec tokens estimés et aperçu lisible, plus la réponse du
modèle rendue proprement. *(Critère : diagnostiquer une perte de cache sans ouvrir un JSON.)*

**P6 — Relire du code.** `/files` : je choisis le projet (déroulant), j'explore l'arbre,
les fichiers sont colorés (pygments serveur). *(Critère : lisible comme un éditeur, zéro CDN.)*

**P7 — Un LLM consomme le serveur.** `GET /api/schema` décrit toutes les routes.
Tout endpoint de lecture renvoie du JSON structuré ; `/blocks?plain=1` renvoie les
messages en texte brut (sans HTML) pour analyse par un agent.

## Choix OSS — minimiser le code écrit

| Besoin | Choix | Pourquoi |
|---|---|---|
| Éditeur / diffs riches | **Monaco** via jsdelivr (déjà utilisé par la v1) | le navigateur passe le proxy système sans souci (seuls pip/npm/httpx exigent NTLM) ; fallback pygments/diff unifié si CDN indisponible |
| Coloration (fallback) | **pygments** (déjà dans le venv via rich) | rendu serveur, marche offline |
| Diffs (fallback) | **difflib** (stdlib) | toujours affichable |
| Analyse cache/payload | **`web.context_viewer`** (v1, réutilisé) | fait exactement P5, déjà débuggé |
| Cycle de vie agents | **`web.runner`/`ipc`/`pending`** (v1, réutilisés) | éprouvés |
| Web | **Flask + Jinja** (déjà dep) | pages serveur, JS minimal |
| Écartés | CodeMirror, diff2html, htmx | redondants avec Monaco / gain marginal vs JS vanilla < 200 lignes/page |

## Modèle de données (`~/.bouzecode/web_v2/`)

- `projects.json` — `[{name, path}]`
- `tickets/<slug>.json` — `[{id, title, prompt, created_at, done, comments:[{at, text, sent}],
  runs:[{agent_id, kind: work|validate_tests|validate_refacto, model, started_at, verdict}]}]`
- Statut ticket dérivé : en cours → à relire → validé → terminé.

## API (consommable par un LLM — voir GET /api/schema)

| Route | Rôle |
|---|---|
| `GET /api/projects` | projets + compteurs d'actions requises |
| `POST /api/projects` | ouvrir un projet `{name, path}` |
| `GET /api/projects/<name>/agents` | agents du projet (cwd ⊂ path) + statut |
| `GET/POST /api/projects/<name>/tickets` | tickets / créer (`{title, prompt, model, launch}`) |
| `POST /api/tickets/<slug>/<id>/comments` | commenter `{text, send}` (send → continue l'agent) |
| `POST /api/tickets/<slug>/<id>/validate` | `{kind: tests|refacto, model}` |
| `POST /api/tickets/<slug>/<id>/done` | basculer terminé |
| `GET /api/sessions/<key>/blocks?after=N[&plain=1]` | conversation (HTML ou texte) + statut |
| `GET /api/sessions/<key>/turns` | tableau des appels LLM (durées, tokens, cache, coût) |
| `GET /api/sessions/<key>/turns/<n>` | drill-down payload annoté cache + réponse |
| `GET /api/sessions/<key>/files[?raw=1]` | diffs des fichiers modifiés (raw → before/after pour Monaco) |
| `GET /api/tickets/<slug>/<id>/results` | MR détectées dans la session, branche, commits depuis création, fichiers |
| `GET /api/files/tree·content?root=<project>` | explorateur (pygments si `hl=1`) |
| `GET /api/models` | modèles du registry (menu déroulant) |

## Tickets — kanban et résultats

Les tickets s'affichent en colonnes (à faire / en cours / à relire / validé / terminé).
Les statuts intermédiaires sont **dérivés** des runs et verdicts ; seul terminé est un
choix utilisateur → le drag-and-drop n'agit que vers/depuis « terminé », le reste se
pilote par les actions (relancer, valider). Le panneau « Résultats » d'un ticket montre
les **liens MR/PR détectés** dans le texte de la session (sortie `git push` GitLab/GitHub),
la branche courante du projet et les commits depuis la création du ticket — best-effort
sans configuration ; une intégration API GitLab (créer la MR depuis l'UI) reste possible
en v2.2 si un token est fourni.

## Hors périmètre v2.2 (assumé)

Création de MR via l'API GitLab (nécessite un token), édition/sauvegarde de fichiers
depuis l'UI, auth multi-utilisateur.
