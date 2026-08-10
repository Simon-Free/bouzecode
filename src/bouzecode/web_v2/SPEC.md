# Cahier des charges — BouzéqUI v2

## Le user et son produit

L'utilisateur pilote des agents bouzecode sur plusieurs projets. Son quotidien :
il **shoote des tickets**, laisse tourner, et revient. À son retour il a besoin de
répondre en 10 secondes à : *où dois-je agir ?* Puis, ticket par ticket : *le travail
est-il bon ?* Et quand un agent a ramé : *où est passé le temps et les tokens ?*

## Parcours utilisateurs

**P1 — RETIRÉ (pages web projets).** Les pages `/projects` et `/p/<slug>` n'existent plus :
l'UI est entièrement centrée sur `/conversations` (P8). Les **API** `/api/projects*` et
`/api/tickets*` restent servies — elles alimentent le sélecteur de projet de `/conversations`
et sont consommées par les agents.

**P2 — Shooter un ticket.** `POST /api/projects/<slug>/tickets` (titre + prompt + modèle)
crée le ticket et lance son run. *(Critère : < 15 s entre l'idée et l'agent lancé.)* Depuis
l'UI, ce parcours passe par la barre « nouvelle conversation » de `/conversations` (P9).

**P3 — Relire un résultat.** Depuis la session : conversation, onglet **Fichiers modifiés**
(diffs colorés, rendus serveur + Monaco). Je commente le ticket (« # TODO renomme X »,
« refais la partie Y ») → « Envoyer au modèle » relance l'agent avec mon commentaire.
Ou je coche « terminé ». *(Critère : la boucle relecture → correction ne quitte pas la page.)*

**P4 — Valider (CI/CD léger).** `POST /api/tickets/<slug>/<id>/validate {model?}` lance un agent
vérificateur sur le diff du ticket (worktree si le ticket est isolé, sinon le projet) qui termine
par `VERDICT: OK|KO`. Le verdict est porté par le run du ticket et remonte dans les compteurs de
`/api/projects`. **Une seule sorte de validation** : le paramètre `kind: tests|refacto` n'existe
plus. Le lancement est MANUEL (ou décidé par un manager) — cf. P10.
*(Critère : verdict lisible sans ouvrir la session.)*

**P5 — Autopsie d'une session lente.** Session → onglet **Tours** : un tableau par appel
LLM — heure, Δ durée, tokens in/out, cache lu/écrit, % de cache hit, outils appelés, coût.
Je repère le tour anormal (Δ long, cache hit bas) → clic → drill-down : le payload exact
envoyé, item par item (system / user / assistant / tool result), chacun étiqueté
**cached / new-cache / fresh** avec tokens estimés et aperçu lisible, plus la réponse du
modèle rendue proprement. *(Critère : diagnostiquer une perte de cache sans ouvrir un JSON.)*

**P6 — RETIRÉ (explorateur de fichiers).** La page `/files` et les routes `/api/files/*` ont
été supprimées. Relire du code se fait par l'onglet **Fichiers modifiés** d'une session
(P3), qui reste servi par Monaco vendorisé.

**P7 — Un LLM consomme le serveur.** `GET /api/schema` décrit toutes les routes `/api/`.
Le schéma est **dérivé de `app.url_map`** (méthode + règle) et non saisi à la main : il ne
peut donc pas décrire une route disparue ni ignorer une route ajoutée. Tout endpoint de
lecture renvoie du JSON structuré ; `/blocks?plain=1` renvoie les messages en texte brut
(sans HTML) pour analyse par un agent. *(Critère : un agent découvre et appelle une route
sans lire le code — la description donne les paramètres attendus et la forme de la réponse.)*

**P8 — Boîte de réception des conversations.** J'ouvre `/` : je tombe sur `/conversations`,
la page d'accueil. La barre latérale liste mes conversations racines (les managers) et
**remonte en tête celles qui attendent une réponse de moi** ; les sous-agents d'une
conversation s'ouvrent en onglets sous leur manager. *(Critère : la première chose que je
vois en arrivant, c'est ce qui m'attend, sans filtrer ni chercher.)*

**P9 — Lancer une conversation depuis un projet choisi.** Depuis `/conversations` je tape mon
intention et je choisis le projet dans le sélecteur : `POST /api/dispatch {prompt, project_slug}`
crée le ticket et lance l'agent. Le titre du ticket est la première ligne du prompt ; la
typologie et le modèle viennent du choix explicite (défaut `default`). L'environnement est demandé
par `isolation` : `shared` (défaut, dépôt principal), `worktree` (worktree git seul, sans venv) ou
`worktree+venv` ; deux agents `shared` sur le même dépôt → le second est basculé en `worktree`
d'office. `defer=true` répond dès le ticket créé, worktree et spawn partent en fond.
**Aucune déduction LLM** : sans `project_slug`, la réponse est
`needs_project` + la liste des projets ouverts, que le front présente comme un choix à faire.
*(Critère : ce qui est lancé est ce qui a été demandé — jamais un projet deviné.)*

**P10 — La décision appartient au manager ; le serveur ne garde que le filet.** La chaîne
automatique travail → test-gate → validation → merge a été **retirée**
(cf. `docs/design_p10_orchestration.md`). Quand un agent termine, son hook `on_completion`
appelle toujours `POST /api/tickets/<slug>/<ticket_id>/completed`, mais celui-ci se contente de
clore le run et de signaler un crash : plus de test-gate, plus de validateur spawné d'office,
plus de merge automatique, plus de boucle de rework plafonnée. Validation et intégration sont
demandées explicitement (`/validate`, `/integrate`) par le manager ou par moi. Ce qui reste
automatique : la **détection de crash** (watchdog `wake`, tick de fond), le **réveil du parent**
quand ses enfants ont fini, la **récolte du WIP** et le **faucheur de worktrees**.
*(Critère : aucun agent mort ne laisse un ticket bloqué en silence — mais rien n'est mergé
sans que quelqu'un l'ait demandé.)*

**P11 — Composer un agent.** `/agent-builder` : je choisis outils, skills et hooks dans le
catalogue de bouzecode, j'écris un complément de prompt, et je vois le **system prompt
complet calculé** avant de sauver le profil. *(Critère : je sais ce que l'agent recevra
avant de le lancer, pas après.)*

**P12 — Suivre un agent token par token.** Pendant qu'un agent répond, la conversation
affiche son texte en cours de production sans attendre la fin du tour. *(Critère : je vois
que ça avance, et quoi, sans ouvrir de log.)*

**P13 — Archiver sans rien perdre.** Je retire du board un ticket ou une conversation dont
je n'ai plus besoin, et je peux le récupérer. **Rien n'est jamais effacé** : un ticket
archivé reste dans son store, une conversation archivée part dans une corbeille
(déplacement d'artefacts) ou dans un registre de soft-delete qui l'exclut des listes.
*(Critère : nettoyer mon écran n'est jamais une décision irréversible.)*

## Choix OSS — minimiser le code écrit

| Besoin | Choix | Pourquoi |
|---|---|---|
| Éditeur / diffs riches | **Monaco vendorisé** dans `static/vendor/monaco/` (copie figée de monaco-editor 0.52.0), **aucun CDN** | marche hors ligne et derrière un proxy restrictif ; servi avec un cache navigateur long car immuable ; fallback pygments/diff unifié si le vendor est absent |
| Coloration (fallback) | **pygments** (déjà dans le venv via rich) | rendu serveur, marche offline |
| Diffs (fallback) | **difflib** (stdlib) | toujours affichable |
| Analyse cache/payload | **`web_v2.runtime.context_viewer`** | fait exactement P5, déjà débuggé |
| Cycle de vie agents | **`web_v2.runtime`** (`runner`, `ipc`, `pending`, `state_streams`, `warmpool`) | éprouvés |
| Web | **Flask + Jinja** (déjà dep) | pages serveur, JS minimal |
| Écartés | CodeMirror, diff2html, htmx | redondants avec Monaco / gain marginal vs JS vanilla < 200 lignes/page |

Le paquet `bouzecode.web` (v1) a été **supprimé** : tout ce code vit désormais sous
`web_v2/runtime/`. Aucune dépendance à la v1 ne subsiste.

## Modèle de données (`~/.bouzecode/web_v2/`)

- `projects.json` — `[{name, slug, path, description}]` (`description` ≤ 200 car., affichée
  dans le sélecteur de projet de `/conversations`)
- `tickets/<slug>.json` — `[{id, title, prompt, created_at, done, comments:[{at, text, sent}],
  runs:[{agent_id, kind: work|validate|merge, model, started_at, verdict}]}]`
  (`validate_tests` / `validate_refacto` sont d'anciens `kind` encore lus dans les tickets
  historiques, mais plus jamais écrits)
- Statut ticket dérivé : en cours → à relire → validé → terminé.

## API (consommable par un LLM)

**La liste qui fait foi est `GET /api/schema`**, dérivée de `app.url_map` : c'est la seule
qui ne peut pas devenir périmée. Le tableau ci-dessous n'en est qu'un rappel des routes
structurantes.

| Route | Rôle |
|---|---|
| `GET /api/schema` | toutes les routes `/api/`, avec paramètres et forme de réponse |
| `GET /api/projects` | projets + compteurs d'actions requises |
| `POST /api/projects` | ouvrir un projet `{name, path}` |
| `GET /api/projects/<slug>/agents` | agents du projet (cwd ⊂ path) + statut |
| `GET/POST /api/projects/<slug>/tickets` | tickets / créer (`{title, prompt, model?, typology?, isolation?, launch?, defer?}`) |
| `POST /api/tickets/<slug>/<id>/comments` | commenter `{text, send}` (send → continue l'agent) |
| `POST /api/tickets/<slug>/<id>/validate` | `{model?}` → spawne le validateur (plus de `kind`) |
| `POST /api/tickets/<slug>/<id>/integrate` | merge du worktree dans la base, sur demande (P10) |
| `POST /api/tickets/<slug>/<id>/done` | basculer terminé |
| `GET /api/sessions/<key>/blocks?after=N[&plain=1]` | conversation (HTML ou texte) + statut |
| `GET /api/sessions/<key>/turns` | tableau des appels LLM (durées, tokens, cache, coût) |
| `GET /api/sessions/<key>/turns/<n>` | drill-down payload annoté cache + réponse |
| `GET /api/sessions/<key>/files[?raw=1]` | diffs des fichiers modifiés (raw → before/after pour Monaco) |
| `GET /api/tickets/<slug>/<id>/results` | MR détectées dans la session, branche, commits depuis création, fichiers |
| `GET /api/models` | modèles du registry (menu déroulant) |
| `GET /api/agents/tree` | arbre des conversations, attentes d'input en tête (P8) |
| `POST /api/dispatch` | `{prompt, project_slug}` → ticket créé et agent lancé ; `needs_project` sans projet (P9) |
| `POST /api/tickets/<slug>/<ticket_id>/completed` | hook `on_completion` : fait avancer la chaîne travail→validation→merge (P10) |
| `GET /api/builder/catalog·agents`, `POST /api/builder/preview` | agent-builder : catalogue et system prompt calculé (P11) |
| `GET /api/sessions/<key>/partial` | texte assistant du tour en cours, token par token (P12) |
| `POST /api/conversations/archive`, `POST /api/sessions/<key>/restore` | archivage réversible d'une conversation (P13) |
| `POST /api/tickets/<slug>/<ticket_id>/archive·unarchive` | archivage réversible d'un ticket (P13) |

## Tickets — statuts et résultats

Le kanban de tickets vivait sur la page projet, retirée avec P1 : il n'y a plus de vue
tickets dans l'UI. Les statuts restent **dérivés** des runs et verdicts côté serveur
(`GET /api/projects/<slug>/tickets`), et seul « terminé » est un choix utilisateur
(`POST /api/tickets/<slug>/<id>/done`). `GET /api/tickets/<slug>/<id>/results` expose les
**liens MR/PR détectés** dans le texte de la session (sortie `git push` GitLab/GitHub), la
branche courante du projet et les commits depuis la création du ticket — best-effort sans
configuration.

## Hors périmètre v2.2 (assumé)

Création de MR via l'API GitLab (nécessite un token), édition/sauvegarde de fichiers
depuis l'UI, auth multi-utilisateur, exploration libre du système de fichiers (ex-P6).
