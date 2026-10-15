# Spécification utilisateur — BouzéqUI v3

> Réécrite le 2026-09-23 à partir de trois audits de code (`docs/refonte_ui/audit_*.md`) et des
> arbitrages de l'utilisateur. Remplace la spec v2.2 (archivée dans
> `docs/archive/SPEC_web_v2_v2.2.md`). **Ce document fait foi pour l'UI ; `GET /api/schema`
> fait foi pour l'API.**

---

## 0. Pour qui, pour quoi

L'utilisateur pilote une flotte d'agents de code sur plusieurs dépôts. Il **note** ce qu'il y a à
faire, le **lance** sur des agents, **s'en va**, puis **revient**. À son retour il doit répondre en
10 secondes à *« qu'est-ce qui m'attend ? »*, puis traiter chaque point sans changer de page :
répondre à une question, relire une livraison, relancer un agent planté.

Trois pages, trois rôles, et aucun recouvrement :

| Page | Rôle | Question à laquelle elle répond |
|---|---|---|
| **Bureau** `/` (= `/bureau`) | Accueil. Ce qui m'attend, puis mon travail rangé par chantier. | « Où dois-je agir ? Qu'est-ce que j'ai à faire ? » |
| **Agents** `/conversations` | Lire et suivre les agents en détail : fil, récap, fichiers, coûts. Lancer une conversation libre. | « Que fait / qu'a fait cet agent ? » |
| **Profils** `/agent-builder` | Composer des profils d'agent (outils, skills, instructions). | « Qu'est-ce qu'un agent de ce type recevra ? » |

`/` redirige vers `/bureau`. `/sessions/<key>` redirige vers `/conversations?agent=<id>` (les vues
Fichiers / Tours / Coûts vivent désormais dans le panneau d'un agent). `/todo` redirige vers
`/bureau`. Les anciennes pages `/projects` et `/files` (explorateur de fichiers et ses API) ont
été RETIRÉES (lot L6, arbitrages P1 et P6) : les dépôts se gèrent depuis le dialogue « Gérer les
dépôts » (API `/api/projects`), les fichiers modifiés d'un agent depuis son panneau.

**API** (lot L6) : `GET /api/schema` est DÉRIVÉ des routes (docstrings + corps déclarés) et la
skill `bouzecode/web-api` en est régénérée ; toute erreur a la forme unique
`{"error": {"code", "message", "details"?}}` ; les alias dépréciés des anciennes routes sont
retirés ; aucune lecture (GET) ne livre de message ni ne lance de vérification — le watchdog s'en
charge à son tick.

---

## 1. Vocabulaire (unique, tenu partout — y compris dans les messages d'erreur serveur affichés)

| Mot UI | Objet technique | Définition |
|---|---|---|
| **Chantier** | macro (`/api/macros`) | Un objectif au long cours, qui peut toucher **plusieurs dépôts**. Contient des tâches. |
| **Tâche** | micro (`/api/micros`) | Ce que j'écris et que je peux confier à un agent. **Un seul champ : le brief** (markdown) ; sa 1re ligne non vide sert de libellé dans la liste (le serveur la stocke comme `titre`). Appartient à un chantier (ou à « Sans chantier »). |
| **Dépôt** | projet (`/api/projects`) | Un dépôt git enregistré. Une tâche vise **un** dépôt ; un chantier en regroupe plusieurs. |
| **Agent** | agent + ticket + session | Une exécution : un processus qui travaille sur une tâche (ou sur une conversation libre), avec sa **conversation**. Une tâche peut avoir **plusieurs passages** (un agent par passage). |
| **Sous-agent** | agent enfant | Un agent lancé par un autre agent (le « manager »). |
| **Profil** | typologie / profil | Le type d'agent : outils, skills, instructions. |
| **Assistant** | profil `bureau-assistant` | L'agent de pilotage du Bureau : il agit sur les chantiers et les tâches, il ne code pas. |

Mots **bannis** de l'UI : ticket, micro, macro, puce, TO-DO, ligne, run, typologie, manager (on dit
« agent principal »), cli, chaud, shared/worktree (voir §5.4).

**Source unique de TOUS les mots d'état** (statut de tâche, état d'agent, motif d'attente, statut de
ticket) : la table `LEXIQUE` de `services/work/lexique.py` — mot, aide (infobulle), ton, icône. Elle
est servie par `GET /api/lexique`, injectée dans chaque page (`<script id="bz-lexique">`, lu par
`static/js/lib/states.js` et `bureau/attention.js`), et appliquée aux tickets (`status_ui`,
`libelle_statut`, à côté du `status` interne de `derive_status`). Un mot par situation, le même sur
le Bureau, la page Agents et l'API (garde : `tests/test_lexique_unique.py`).

### 1.1 Lexique des états d'un agent

| Clé | Libellé | Couleur (token) | Animation | Section / groupe |
|---|---|---|---|---|
| `preparing` (provisioning, phase démarrage) | Préparation… | `--info` | pulse | En cours |
| `thinking` (phase attente modèle) | Le modèle lit ta demande… | `--info` | pulse | En cours |
| `running` | En cours | `--info` | pulse | En cours |
| `orchestrating` (fini + enfants vivants) | Attend ses sous-agents | `--info` | pulse | En cours |
| `awaiting_input` | Attend ta réponse | `--warn` | — | **À traiter** |
| `awaiting_plan_validation` | Plan à valider | `--warn` | — | **À traiter** |
| `crashed` / interrompu | Arrêté sans finir | `--danger` | — | **À traiter** |
| `launch_failed` | Lancement échoué | `--danger` | — | **À traiter** |
| `idle` (fini, processus réutilisable) | Terminé | `--ok` | — | Terminés |
| `finished` | Terminé | `--ok` | — | Terminés |
| `archived` | Archivé | `--text-3` | — | Archivés |

**Règle d'accessibilité** : un état n'est **jamais** porté par la seule couleur. Partout (Bureau,
liste d'agents, onglets, chips de sous-agents), le libellé est visible ou, en format compact, une
icône de forme distincte + libellé en infobulle (`●` en cours, `?` attend réponse, `!` arrêté,
`✓` terminé, `✕` KO).

### 1.2 Statut d'une tâche (dérivé côté serveur, jamais saisi, sauf Fait/Abandonnée)

| Statut | Quand | Libellé | Section (mode Statut) |
|---|---|---|---|
| `brouillon` | jamais lancée (ou rouverte) | À lancer (icône seule dans la section « À lancer ») | À lancer |
| `a_decider` | un agent a fini en laissant un choix à l'humain (`decision: true`), aucun agent n'attend | À décider | **À traiter** |
| `en_cours` | un agent du dernier passage travaille | En cours · *activité* | En cours |
| `a_repondre` | un agent de la tâche attend une réponse | Attend ta réponse | **À traiter** |
| `a_relire` | le dernier passage a rendu sa réponse finale | À vérifier | **À traiter** |
| `en_echec` | le dernier agent s'est arrêté sans finir, ou le lancement a échoué | Arrêté sans finir · *raison* | **À traiter** |
| `faite` | geste humain ou de l'assistant (« Valider et clore », « Marquer faite… » avec commentaire, §4.6) — ou brouillon de fusion dont la branche a été intégrée (archivage automatique tracé, §4.6) | Faite | Archivées |
| `abandonnee` | geste humain ou de l'assistant (« Abandonner », « Doublon de… », « Caduque… », §4.6) | Abandonnée — **Doublon** / **Caduque** quand c'est le motif | Archivées |

### 1.3 Ce que l'utilisateur doit faire (motif → catégorie → action)

Le statut dit où en est la tâche ; l'écran, lui, dit **ce qu'il faut faire**. Le serveur
(`services/work/lexique.py::motif_attente`) donne à chaque tâche ou point hors tâche qui attend un
geste un **motif** (`motif`, `categorie` dans `/api/lignes` et `/api/inbox`) ; le motif fixe le mot
de la ligne, et la catégorie le groupe de « À traiter ».

| État réel (backend) | Motif | Mot sur la carte | Catégorie (groupe) | Action attendue, sur la carte |
|---|---|---|---|---|
| agent `awaiting_input` (tâche ou hors tâche) | `question` | Attend ta réponse | **Décider** | options en boutons + réponse libre · Voir l'agent · Arrêter |
| agent `awaiting_plan_validation` | `plan` | Plan à valider | **Décider** | plan rendu + options (valider / refuser) + réponse libre |
| tâche `decision: true` (clôture d'un agent), aucun agent | `point` | À décider | **Décider** | **Noter ma décision…** (ajoutée au brief, tâche close, Annuler) · Confier à un agent… · Abandonner |
| passage `launch_failed` (dépôt, git, venv, API), ticket hors tâche en échec de lancement | `lancement` | Lancement échoué | **Action manuelle requise** | cause affichée · **Corriger et relancer…** (dialogue : autre dépôt / environnement) · Abandonner (hors tâche : Relancer) |
| passage `crashed` sans réponse finale (erreur API, process mort, aucun agent démarré) ; conversation libre arrêtée | `plante` | Arrêté sans finir | **Reprendre un agent arrêté** | raison · **Continuer…** (même agent, si joignable) · Relancer (agent neuf) · Abandonner |
| passage `crashed` tué à la demande (`killed_by: server`), ou lancement arrêté à ta demande pendant la préparation | `arrete` | Arrêté par toi | **Reprendre un agent arrêté** | idem, sans parler de plantage |
| passage `missing` (fiche d'agent ou ticket perdus), tâche lancée sans ticket | `introuvable` | Agent introuvable | **Reprendre un agent arrêté** | Relancer · Abandonner |
| passage `finished` / `idle` (réponse finale rendue) | `livraison` | À vérifier | **Vérifier et clore** | résumé du passage · **Valider et clore** (Annuler) · Renvoyer avec un retour… · Intégrer (branche non intégrée) · Voir le travail · Voir l'agent |

Une tâche `a_decider` née de la clôture d'un agent (`micro_suites` la relie au ticket qui l'a laissée) porte `decision_source` = `{ticket_id, slug, titre, agent_id, resume, rapport_html}` : la carte affiche un dépliant « Réponse finale de l'agent … » (aperçu du résumé, réponse complète au dépli, lien vers la conversation). Sans source retrouvable (tâche créée à la main), seul le texte générique reste.

Restent hors de ces groupes : `preparing`, `thinking`, `running`, `orchestrating` (En cours, rien à
faire), et les **réponses non livrées** à un agent (bandeau « Renvoyer », §3).

---

## 2. Règles transverses de feedback (non négociables, testées)

Ces règles s'appliquent à **toute** interaction de **toutes** les pages.

**R1 — Tout geste a un signal immédiat (< 100 ms).** Clic sur un bouton d'action : le bouton passe
en état occupé (`aria-busy`, désactivé, libellé d'action en cours, spinner). Saisie validée : le
champ se verrouille. Il n'existe aucune action silencieuse.

**R2 — Toute attente > 300 ms montre un indicateur** à l'endroit où le résultat apparaîtra :
spinner dans le bouton, squelette dans la liste, ou barre de progression par étapes pour un
lancement d'agent.

**R3 — Toute action se conclut par un résultat visible** : soit le changement lui-même à l'écran,
bien visible (l'élément créé apparaît, surligné 2 s, et défile dans la vue), soit un **toast**
(`role=status`, bas droite, 4 s) quand le changement se produit hors vue (ex. la tâche passe dans
une autre section : « Tâche classée faite — Annuler »).

**R4 — Toute erreur est dite, là où l'on regarde, en français, avec une issue.** Erreur de champ :
sous le champ. Erreur d'action : toast d'erreur persistant (✕ pour fermer) avec « Réessayer » quand
c'est pertinent. Erreur de chargement : état d'erreur dans la zone + « Réessayer ». Jamais de
`catch(){}` muet, jamais d'`alert()`/`confirm()` natifs, jamais de réponse HTTP 200 `ok:false`
présentée comme un succès. Le texte saisi par l'utilisateur n'est **jamais perdu** sur erreur.

**R5 — Pas de double action.** Un bouton occupé ne se re-déclenche pas ; Entrée répétée dans un
champ en cours d'envoi est ignorée ; les boutons d'option d'une question se verrouillent tous au
premier clic.

**R6 — Les actions destructrices ou irréversibles** passent par une confirmation stylée
(`ui.confirm`) **ou** par un « Annuler » de 10 s dans le toast (préféré pour archiver / classer).
Supprimer un chantier : confirmation qui dit ce que deviennent ses tâches.

**R7 — Le serveur injoignable se voit.** Si deux rafraîchissements consécutifs échouent, un
bandeau « Connexion au serveur perdue — nouvel essai dans Ns » apparaît en haut de page ; il
disparaît seul au retour, et les vues se rafraîchissent aussitôt.

**R8 — Rien ne change sous les yeux sans raison, rien ne reste figé.** Les vues vivantes (Bureau,
liste d'agents, conversation ouverte) se rafraîchissent seules (poll ≤ 5 s quand un agent tourne
sur la vue, ≤ 15 s sinon, pause quand l'onglet navigateur est caché). Le rafraîchissement ne
détruit jamais un champ en cours d'édition, ni l'élément sous le pointeur.

**R9 — Le travail s'enregistre tout seul.** Le brief d'une tâche s'enregistre automatiquement à la
frappe (≈ 800 ms), à la perte de focus et avant de lancer / quitter : indicateur discret
« Enregistrement… » → « Enregistré » ; en erreur, message à côté + nouvel essai automatique, texte
jamais perdu ; la dernière frappe gagne. Pas de bouton Enregistrer / Annuler, pas de garde
« modifications non enregistrées » — sauf si un envoi est encore en vol quand on quitte la page.
(Les formulaires ponctuels — description d'un chantier, profil, contexte de l'assistant — gardent
un bouton Enregistrer explicite avec « • modifié ».)

**R10 — Tout est faisable au clavier** : éléments d'action focusables, focus visible, Échap ferme
les tiroirs / menus / dialogues et annule un glisser-déposer (exception : dans le tiroir de
l'assistant qui travaille, Échap **interrompt** son tour, comme dans Claude Code, §4.10), pas d'action accessible uniquement au
survol ou au glisser (toute poignée de glisser est un bouton qui ouvre l'alternative au clavier).

**R11 — Aucune maintenance silencieuse** : une ouverture de page ne supprime, n'archive ni ne
déplace rien sans le dire.

**R12 — Le titre de l'onglet navigateur** dit la page et le nombre de points qui m'attendent :
`(3) Bureau — bouzecode`.

---

## 3. Chrome commun

- **Barre de navigation** : marque · **Bureau** (avec pastille du nombre de points « À traiter ») · **Agents**
  (pastille du nombre d'agents en cours) · **Profils**. Le lien « API » sort de la navigation
  principale (pied de page « API · schéma »).
- **Zone de bandeaux** (empilés, composant `.banner`) :
  - *API indisponible* (rouge) : cause lisible + « Revérifier » (occupé pendant la sonde ; résultat
    « Revérifié à HH:MM — toujours indisponible » ou disparition du bandeau).
  - *Serveur en dérive de version* (ambre) : « Redémarrer » → confirmation → progression
    « Redémarrage… (Ns) » → rechargement automatique ; erreur HTTP du redémarrage = toast d'erreur
    immédiat, pas d'attente inutile.
  - *Connexion perdue* (R7).
  - *Réponses non livrées* (Bureau) : « N réponses n'ont pas atteint leur agent — Renvoyer »
    (progression « Renvoi 1/N… », résultat par réponse).
- **Toasts** : pile bas-droite, succès 4 s, erreur persistante, action optionnelle (Annuler /
  Réessayer / Ouvrir).
- **Thème** : **clair (mode jour, fond blanc) par défaut**, même si le système est en sombre ; le
  bouton ◐ passe au sombre et ce choix explicite est mémorisé (`bz.theme.choix`). Le chargement
  d'une page n'écrit jamais de préférence. Contraste AA dans les deux thèmes ; aucune ressource
  externe (pas de Google Fonts, pas de CDN).

---

## 4. Bureau (`/bureau`, page d'accueil)

### 4.1 Disposition

Une seule vue à la fois, **deux modes de tri** entre lesquels on bascule (« Trier par : Statut |
Chantier », mémorisé, défaut Statut). Chaque tâche n'apparaît **qu'une fois**, quel que soit le mode.
Thème clair par défaut.

```
Bureau                        Trier par [Statut | Chantier]   [Rechercher…  / ]
À TRAITER 4
  Décider 2 — Un agent attend ta réponse, la validation de son plan, ou t'a laissé un choix.
    ? Question   Brancher la base                                                  DEMODB
                 Quelle base de données dois-je cibler ?  [PostgreSQL] [SQLite]  [réponse libre…] [Répondre]
    ? Question   Choisir le format (agent arrêté)                                   DEMODB
                 Quel format d'export ?  [réponse libre…] [Répondre] [Continuer…] [Classer sans réponse…]
    ◆ Décision   Garder le séparateur « ; » ?                                      DEMODB
                 Aucun agent n'attend : note ta décision, ou confie-la à un agent.
                 ▸ Réponse finale de l'agent a1b2c3d4 — « J'ai corrigé le login… »  [Ouvrir la conversation]
                 [Noter ma décision…] [Confier à un agent…] [Abandonner]
  Vérifier et clore 1 — L'agent a rendu sa réponse finale : vérifie, puis clos ou renvoie.
    ✓ À vérifier Lister les requêtes lentes  Exploration faite, 3 fichiers modifiés   DEMODB
                 [Valider et clore] [Renvoyer avec un retour…] [Intégrer] [Voir le travail]
  Reprendre un agent arrêté 1
    ! Planté     Migrer les dates   L'agent s'est arrêté sans réponse finale        DEMODB
                 [Continuer…] [Relancer] [Abandonner]
EN COURS 1
  ● En cours   Migrer les vues            lit views.py                               DEMODB
À LANCER 7
  ○ Brouillon  Documenter le schéma                                                  Sans chantier
  [+ Ajouter une tâche…]  [dans : Chantier ▾]
▸ ARCHIVÉES (8)
                                                                                 (💬) ← bouton flottant
```

### 4.2 Ce qui t'attend

Ce qui attend un geste est rangé par **ce que l'utilisateur doit faire** (§1.3) — quatre groupes,
chacun titré par un verbe et une phrase d'explication : **Décider** · **Action manuelle requise** ·
**Reprendre un agent arrêté** · **Vérifier et clore**. Un groupe vide n'est pas affiché.

**Question d'un agent arrêté.** Une question reste dans « À traiter » tant qu'elle n'a pas de
réponse, même si le process de l'agent est arrêté (la conversation, elle, existe toujours). La
carte porte `agent_vivant` (process debout ou non) :
- agent **vivant** : gestes inchangés, [Répondre] [Ouvrir la conversation] ; la réponse part à chaud.
- agent **arrêté** : l'humain choisit, rien n'est classé d'office —
  [Répondre] (la réponse relance l'agent), **[Continuer…]** (reprise de la même conversation avec
  un message optionnel), **[Classer sans réponse…]** (commentaire optionnel).
Classer appelle `POST /api/agents/<id>/question/archive {comment}` : la paire
(agent, date de la question) est inscrite dans `question_archives` ; la question disparaît de
l'accueil, des lignes du Bureau et de la file des décisions (cartes `question_agent` ouvertes de
l'agent passées `moot`, non rouvertes par l'ingestion). Refus 409 `agent_alive` si l'agent vit,
404 `not_waiting` s'il n'attend rien. Une NOUVELLE question du même agent (autre date) réapparaît.

Le point est porté **par la tâche elle-même** : la ligne est **surlignée** (teinte selon le motif),
son état dit en un mot explicite (« Question », « Plan à valider », « Décision », « Lancement
impossible », « Planté », « Arrêté par toi », « À vérifier », « Vérif. KO » — l'explication complète
en infobulle), sa ligne secondaire dit pourquoi (raison, résumé du passage, « aucun agent
n'attend »). Sous la ligne, une **bande d'action toujours visible** — repliée ou non, sans survol —
porte l'action attendue : la question et ses options, ou les gestes du motif (§1.3), l'action
principale en tête. On agit **sur la carte**, dans les deux modes, sans déplier. Chaque geste suit
R1–R6 (bouton occupé, toast de résultat, « Annuler » quand il classe la tâche).

Les points **sans tâche** (conversation libre ou sous-agent qui pose une question, conversation libre
arrêtée, lancement hors tâche échoué) sont des lignes à part, de même forme et dans le même groupe,
avec leur bande (question, Continuer, Relancer, « Ouvrir la conversation »).

### 4.3 Les deux modes

- **Statut** : sections **À traiter** (tâches et points hors tâche qui attendent un geste, groupés
  par catégorie §4.2, par urgence dans chaque groupe) · **En cours** · **À lancer** (brouillons, avec « + Ajouter une tâche… » et le choix du
  chantier) · **Archivées** (repliée, dépliée à la demande, mémorisé). Chaque tâche rappelle son
  chantier en étiquette discrète. Compteur par section.
- **Chantier** : un bloc par chantier ; ses tâches triées par urgence (celles qui t'attendent en
  tête, surlignées) ; ses tâches archivées repliées en bas (« ▸ N archivées ») ; « + Ajouter une
  tâche… ». En tête, un bloc **Hors chantier** seulement s'il y a des points d'agents sans tâche ;
  en bas « Sans chantier », puis « Chantiers archivés » (replié) ; « + Nouveau chantier ».
- **Recherche** (brief, sans accents ni casse, `/` pour focus, Échap pour vider) : filtre les deux
  modes pareil ; rien trouvé → un seul message.
- Compteur de la nav et titre de l'onglet (R12) inchangés.

### 4.4 Chantier

- En-tête : titre (clic = replier/déplier), dépôts (chips), compteurs (« 2 en cours · 1 à relire »),
  menu **⋯** (accessible au clavier) : Renommer · Décrire · Dépôts… · Mettre en pause / Reprendre ·
  Archiver · Supprimer.
- **Décrire** : description markdown commune, rappelée dans le prompt de chaque tâche du chantier.
  Éditeur avec Enregistrer / Annuler.
- **Dépôts…** : liste des dépôts enregistrés avec cases à cocher (ajout / retrait immédiats,
  chacun avec feedback). Le premier dépôt du chantier est le **dépôt par défaut** de ses tâches.
- **Supprimer** : confirmation « Ses N tâches iront dans “Sans chantier” ».
- **Réordonner** : glisser la poignée ⠿ (§4.9) **et** « Monter / Descendre » dans le menu ⋯, ou
  flèches ↑ ↓ sur la poignée (une place, le focus reste), ou Entrée sur la poignée (dialogue
  « Déplacer le chantier… » : avant quel chantier / en dernier).
- **+ Nouveau chantier** : champ en ligne ; Entrée crée ; le chantier apparaît en haut, surligné,
  prêt à recevoir sa première tâche (focus dans « Ajouter une tâche »).

### 4.5 Tâche — ligne repliée (légère)

`état en un mot (icône + texte coloré, sans pastille) · libellé · UNE ligne secondaire discrète
(ce qui t'attend, sinon l'activité de l'agent, sinon la raison d'un échec ; pour une tâche classée
avec un motif, pourquoi : « Faite par « X » — fait au tour de retours du 25/09 (commentaire de
l'assistant, 25/09 03:12) », « Doublon de « Y » — … (ton commentaire, …) », « Caduque — … »)` ; en mode Statut,
l'étiquette du chantier à droite. Dépôt, date, nombre de passages : dans l'infobulle et le détail.
Une seule séparation fine entre lignes, pas de cadres imbriqués. La **ligne entière** déplie. Une
tâche qui t'attend a sa bande d'action (§4.2) sous la ligne ; une tâche qui n'attend rien montre
son action principale au survol / focus (« Lancer » pour un brouillon, « Voir l'agent » en cours),
qui disparaît quand la tâche est dépliée : on ne voit jamais deux « Lancer » à la fois. Poignée
⠿ de déplacement au survol / focus (toujours visible au doigt).

Une tâche en cours, qui attend une réponse ou à vérifier, à laquelle une **précision a été
transmise** (§4.6, §4.10) montre sous sa ligne la dernière : « ✎ Précision transmise à 14:32 —
pas encore lue par l'agent » puis « — lue par l'agent » (« (tour interrompu) » si elle a coupé son
tour ; « non lue (agent arrêté) » s'il s'est arrêté avant). Le passage à « lue » se fait sans
recharger, dès que l'agent l'a relevée.

### 4.6 Tâche — dépliée

1. **Ce qui t'attend** : la bande d'action (§4.2) reste en tête ; puis la **barre d'actions** du
   statut (seulement si la tâche n'attend rien de toi) et le menu ⋯.
2. **Brief** : un seul champ, enregistré automatiquement (R9). Sa 1re ligne est le libellé.
   Une tâche créée par un agent avec un titre distinct montre ce titre en tête du brief.
3. **Dépôt** : liste déroulante des dépôts enregistrés (effet immédiat).
4. **Passages** : pour chaque agent lancé sur la tâche, du plus récent au plus ancien : état en
   direct, activité, **récap** (fait / reste à faire / à décider), fichiers modifiés, liens
   « Ouvrir la conversation », « Intégrer » (si livrable non intégré), et le **retour** donné.
   Chaque point **reste à faire** / **à décider** dit ce qu'il est devenu, sous son texte :
   - « → tâche créée : *Titre* · *statut actuel* » (« → tâche déjà ouverte : … » quand le point
     était déjà porté par une tâche ouverte du chantier) ; le titre est un lien qui **montre la
     tâche** dans le Bureau (recherche levée, chantier et archives dépliés au besoin, tâche
     dépliée, surlignée, défilée dans la vue) ;
   - sinon « Aucune tâche créée pour ce point. » + **Créer la tâche** : elle naît brouillon (ou
     décision, pour un point « à décider ») dans le chantier et le dépôt du passage, avec le brief
     que l'agent avait écrit pour ce point ; puis elle est montrée. Un second clic ne crée rien.
   Le lien est **enregistré par le serveur** (le pont de clôture note, pour chaque point déclaré
   dans la réponse finale, la tâche créée ou déjà ouverte ; « Créer la tâche » aussi) : renommer
   la tâche ne le casse pas. Seules les clôtures antérieures à ce lien se rattachent à une tâche
   dont le titre est exactement le texte du point (même chantier d'abord).
   Seule une clôture **acceptée** ouvre des tâches : une réponse finale refusée (validateur, ou
   rendue dans le même lot qu'un outil dont l'agent n'a pas encore lu le résultat) n'en ouvre
   aucune — l'agent redéclare ses points à la clôture suivante. Un agent réveillé qui clôt de
   nouveau (retour de test, compte rendu de ses sous-agents) ouvre les points de ce nouveau tour.
5. Menu **⋯** : « Déplacer vers… » (autre chantier ; même dialogue que la poignée), puis, sur une
   tâche ouverte, **« Marquer faite… »**, **« Doublon de… »**, **« Caduque… »** (ci-dessous). Pas
   de sélecteur de chantier visible.
6. **Barre d'actions** d'une tâche qui n'attend rien de toi (les autres : gestes du motif, §1.3) :

| Statut | Actions |
|---|---|
| Brouillon | **Lancer** (le seul) · Abandonner |
| En cours | **Voir l'agent** · Arrêter · Ajouter une consigne… |
| Faite / Abandonnée | **Rouvrir** (repasse en Brouillon, historique conservé) |

Plus de bouton pour marquer une tâche « décision » : les décisions viennent des agents.

**Ajouter une consigne…** (et la même chose dite à l'assistant, §4.10) : la consigne est ajoutée
au brief, dans la section **« Précisions ajoutées »** (datée ; toute relance future la reçoit), ET
transmise à l'agent du dernier passage, qu'il travaille, attende une réponse, attende ses
sous-agents ou soit au repos :
- **en plein tour** : elle est lue à sa **prochaine étape** (après le lot d'outils en cours), sans
  rien casser de son travail ; toast « Consigne ajoutée au brief — l'agent la lira à sa prochaine
  étape » ;
- **au repos** (ou en attente de ses sous-agents) : il est **réveillé** avec elle ;
- tâche close, agent planté ou disparu : elle reste au brief, rien n'est relancé (le toast le dit).

L'agent la reçoit comme un message de l'utilisateur, avec son origine et l'heure (« [Précision de
l'utilisateur, relayée par l'assistant du Bureau — 14:32] ») et la consigne de la reporter dans sa
note Methodology comme un changement de consigne. La ligne montre ensuite si elle a été lue (§4.5).

**Brouillon de fusion devenu sans objet.** Un brouillon qui vise l'intégration d'une branche
d'agent — « Fusionner / Intégrer / Merger la branche agent/XXXX… » — porte sa **cible** (branche
et ticket), posée à sa création : `branche_cible` donnée, sinon la branche `agent/<id>` nommée
dans son titre ou son brief, sinon « la branche … <id> » dans son titre. Quand cette branche est
intégrée (outil Environment de l'agent, bouton « Intégrer », ou intégration constatée au tick du
serveur pour une branche déjà intégrée), le brouillon est **classé Faite automatiquement**, avec
une trace visible sur sa ligne et dans son brief : « Archivée automatiquement : branche
agent/XXXX intégrée le 24/09/2026 à 21:18. » Jamais une tâche lancée, en cours ou déjà liée à un
agent ; et une tâche **rouverte** après un tel archivage n'est plus jamais archivée d'office.
(R11 reste vrai : rien ne se fait à l'ouverture d'une page, et l'archivage se dit.)

Classer une tâche (Faite ou Abandonnée) **archive automatiquement ses tickets et les conversations de ses agents** (sous-agents compris), de façon réversible ; **Rouvrir** les restaure, sauf ce que l'utilisateur avait archivé lui-même. Toast : « Tâche classée faite — N agents archivés — Annuler ».

**Classer sans lancer, en disant pourquoi** (menu ⋯, et le même geste pour l'assistant, §4.10).
Beaucoup de tâches de suite n'ont pas besoin d'agent : le point a été fait par une autre tâche
(souvent la tâche principale, à son tour de retours), il est ouvert deux fois, ou il n'a plus
d'objet. Trois gestes, un dialogue chacun (tâche liée, puis **Commentaire** — « où c'est fait,
pourquoi… », visible sur la carte) :
- **Marquer faite…** → Faite ; « Fait par la tâche » optionnel (liste des tâches, celles du
  chantier d'abord) ;
- **Doublon de…** → Abandonnée, mot « Doublon » ; la tâche gardée est **obligatoire** (sinon le
  dialogue le dit, rien n'est envoyé) ;
- **Caduque…** → Abandonnée, mot « Caduque ».

Le motif, le commentaire, la tâche liée, **l'auteur** (toi, l'assistant ou un agent) et la date sont
enregistrés par le serveur et affichés sur la ligne (§4.5), dans Archivées comme partout.
Toast « « Titre » : Doublon de « X » — Annuler » ; **Annuler** = **Rouvrir** : la tâche repart en
Brouillon et le classement reste dans l'historique, daté (« — rouverte 25/09 10:00 par toi »),
visible dans le détail sous « Classements ». On peut ensuite la reclasser. Une tâche déjà classée
se rouvre avant d'être reclassée. **Jamais sur une tâche dont un agent travaille** (en cours,
attend une réponse, préparation) : les trois entrées sont désactivées, avec la raison au survol
(« arrête-le ou attends sa livraison ») ; le serveur refuse de même (409 `agent_actif`, message
qui nomme l'agent et le geste à faire). Une livraison à vérifier (agent fini) peut être classée.

**Classement par l'agent principal d'un ticket (outil `TachesProjet`).** L'agent PRINCIPAL d'un
ticket, quel que soit son profil, dispose de l'outil `TachesProjet` (toujours actif,
`FRAMEWORK_ALWAYS_ON`). Un **sous-agent** — reconnu à son agent parent (`BOUZECODE_PARENT` non vide hors
`dispatcher:` et hors tâche lancée par le Bureau `BOUZECODE_BRIEF_HUMAIN=1`, ou profondeur
`BOUZECODE_AGENT_DEPTH` / `_depth` > 0) — n'en a **aucune** action : l'outil est retiré de ses outils
(`enabled_tools_for_profile`, `disable_tool` au chargement) et refuse `reserve_a_l_agent_principal` s'il
est appelé quand même. Le sous-agent rend compte dans son rapport ; c'est le principal qui décide et
agit sur la TODO. Actions du principal :
- **lecture** : `lister` et `rechercher` (`texte` cherché dans titre + brief) rendent titre, brief,
  statut et chantier des tâches **de son périmètre** : les chantiers rattachés au projet du ticket
  qui le porte (`BOUZECODE_TICKET_SLUG`) et les tâches lancées sur ce dépôt — jamais toute la base ;
- **classement seul** : `marquer_faite`, `marquer_doublon` (avec `de`), `marquer_caduque`, chacun
  avec un `commentaire` **obligatoire** disant d'où vient la résolution (ticket, commit…). Le
  commentaire est préfixé côté serveur de sa signature (« [agent X · ticket Y] ») et l'auteur
  enregistré est `agent` : la carte affiche « commentaire d'un agent ». Même refus que ci-dessus
  si un agent travaille sur la tâche ; refus `hors_perimetre` pour une tâche d'un autre projet ;
- **exploration** : `explorer` rend la liste des projets (dépôts du registre, le sien marqué
  `le_mien`) et la liste des chantiers, **ceux rattachés à son dépôt en premier**
  (`rattache_a_mon_depot`) ;
- **ranger SA tâche** : `ranger_ma_tache` rattache la tâche de SON ticket (`BOUZECODE_TICKET_ID`, lien
  micro ↔ ticket) à un chantier existant (`chantier` = id ou titre), ou crée le chantier
  (`creer_chantier=true`, `chantier_titre`, `chantier_brief`, `chantier_projets` — défaut : son
  dépôt) puis l'y rattache. Garde-fous : un `task_id` autre que sa tâche → refus `pas_ta_tache` ;
  pas de tâche liée à son ticket → `aucune_tache_en_cours` ; un chantier au titre proche existe
  déjà (similarité ou inclusion, accents/casse ignorés) → refus `chantier_proche_existe` avec les
  candidats ; le brief du chantier créé est préfixé de la signature « [agent X · ticket Y] » ;
- `creer`, `lancer`, `relancer`, `clore`, `repondre`, `deplacer` (d'une autre tâche), `preciser`,
  les décisions restent **réservés à l'assistant du Bureau** (`Taches`) : refus
  `action_reservee_au_bureau` ;
- sans projet rattaché, l'outil répond « aucun chantier rattaché » (ok, liste vide), sans erreur.

### 4.7 Lancer / relancer une tâche (itérations)

- **Lancer** ouvre un panneau de confirmation compact : dépôt (obligatoire, pré-rempli depuis la
  tâche ou le chantier — si aucun, le choix est exigé ici), profil, environnement, et **l'aperçu du
  prompt final** (repliable). Bouton « Lancer l'agent ». Le brief en attente d'enregistrement est
  enregistré **avant** l'aperçu et avant le lancement ; si cet enregistrement échoue, rien ne part
  et le dialogue le dit (jamais d'agent parti sur l'ancien brief).
- **Où tourne l'agent ?** (même dialogue, nouvel agent seulement ; l'assistant reste la voie
  privilégiée) : **Sur ce poste** (défaut) ou **Sur Rundeck** — alors mode **Agent** ou **Tests
  seulement** (arguments pytest exigés AVANT tout appel, case « navigateur » cochée par défaut).
  Les **fichiers non suivis** du dépôt (`GET /api/projects/<slug>/fichiers-non-suivis`, service de
  l'outil `Projets`) sont listés en cases à cocher, ceux désignés par les mots du titre cochés
  d'office ; un secret est affiché grisé, jamais transmis ; binaires, gros fichiers et `temp_*`
  sont comptés, pas listés ; une lecture en échec est dite sans bloquer. Plus les **projets
  secondaires**. Le tout part dans le champ `execution` de `…/lancer|relancer`
  (docs/specs/assistant_execution.md) — au premier lancement seulement s'il n'est pas ordinaire,
  à chaque relance (sinon le serveur reprendrait l'exécution mémorisée). Refus Rundeck
  (`cible_indisponible`, `lancement_impossible`) : dit dans le dialogue avec l'issue « Sur ce
  poste ». Lancé sur Rundeck : toast avec l'exécution et les fichiers NON transmis ; le passage
  montre le lien de l'exécution et ces fichiers refusés.
- Pendant le lancement : la tâche passe immédiatement en « Préparation… » avec la progression par
  étapes servie par le serveur (tâche créée ✓ → préparation de l'environnement → démarrage de
  l'agent → le modèle lit la demande) ; toast « Agent lancé — Ouvrir ».
- **Échec de lancement** (dépôt inconnu, git, venv, API) : la tâche **reste Brouillon** (jamais
  « lancée » à tort), l'erreur est affichée sur la tâche et en toast, le brief est intact.
- **Renvoyer avec un retour…** : champ « Qu'est-ce qui ne va pas / qu'est-ce qui manque ? ». Le
  retour est ajouté à l'historique de la tâche. Le prompt du nouveau passage est assemblé par le
  serveur à partir de : titre + brief + description du chantier + **récap de chaque passage
  précédent** (FinalAnswer : fait / reste / à décider, branche, fichiers) + tous les retours donnés.
  L'aperçu est montré avant l'envoi.
  - Si l'agent du dernier passage est **encore joignable** (processus vivant ou réveillable), le
    choix par défaut est « Continuer avec le même agent » (le retour lui est envoyé dans sa
    conversation, contexte et cache conservés) ; l'autre choix « Nouvel agent (contexte assemblé) »
    reste disponible.
  - Sinon : nouvel agent avec le contexte assemblé.
- **Arrêter** (agent en cours) : confirmation courte ; « Arrêt… » puis l'état devient « Arrêté » ;
  la tâche passe « En échec » (arrêt volontaire) avec Continuer / Relancer.
- **Abandonner** une tâche en cours arrête d'abord son agent (confirmation qui le dit).
- **Rouvrir** une tâche lancée dont l'agent tourne encore est interdit (bouton absent) : il faut
  l'arrêter d'abord. On ne peut jamais avoir deux agents actifs sur la même tâche.

### 4.8 Créer une tâche

- Champ « + Ajouter une tâche… » : en bas de chaque chantier (mode Chantier) ou de « À lancer »
  (mode Statut, avec le choix du chantier). Entrée crée ; Maj+Entrée = retour à la ligne. **Tout le
  texte va dans le brief** (sa 1re ligne devient le libellé). Pendant la création : champ
  verrouillé ; ensuite la tâche apparaît surlignée, **dépliée**, focus dans le brief ; le champ
  d'ajout est vidé. Échec : texte conservé, erreur sous le champ.
- Dépôt par défaut = premier dépôt du chantier.

### 4.9 Déplacer : glisser-déposer et alternatives

Une tâche change de **chantier** (l'ordre des tâches dans un chantier est l'urgence, pas un
rangement manuel) ; un chantier change de **place**. Tout passe par la **poignée ⠿**, un bouton :

- **Glisser** (souris, stylet ou doigt — événements pointeur ; au doigt, glisser depuis la poignée
  déplace, glisser ailleurs fait défiler). Dès que le geste démarre :
  - mode Chantier : **tous les chantiers se replient** le temps du geste (seuls les en-têtes
    restent, chacun une cible en pointillé) et la page se recale pour garder le chantier d'origine
    sous le pointeur ; « Hors chantier », « + Nouveau chantier » et les chantiers archivés
    s'effacent. Un chantier replié reste une cible ; survolé ~0,7 s, il **s'entrouvre** pour
    montrer son contenu, puis se referme quand on le quitte ;
  - mode Statut : un **plateau** « Déposer dans… » liste les chantiers actifs et « Sans chantier »
    (le chantier actuel est marqué) ;
  - un **fantôme** suit le pointeur : ce qu'on déplace et où ça ira (« Déposer dans « X » »,
    « Déjà dans « X » », « Avant / Après « X » » pour un chantier) ; la cible survolée est
    encadrée ; pour un chantier, un **trait d'insertion** avant ou après la cible ;
  - près du haut ou du bas de la fenêtre, la page **défile seule** (plus vite près du bord) ; dans
    le plateau, c'est le plateau qui défile ;
  - **Échap** (ou un geste interrompu) annule : rien n'est envoyé, toast « Déplacement annulé » ;
    relâcher hors d'une cible : « Rien n'a bougé ».
  - Le rafraîchissement automatique est différé pendant le geste (R8).
- **Au dépôt** : la tâche (ou le chantier) affiche « Déplacement… » pendant l'appel (R1/R2), puis
  toast « Tâche déplacée dans « X » » / « Chantier « X » déplacé » avec **Annuler** (10 s), et
  l'élément déplacé est surligné à sa nouvelle place ; un chantier replié le reste. Erreur :
  toast avec « Réessayer ».
- **Sans glisser** : clic ou Entrée sur la poignée d'une tâche → dialogue « Déplacer vers… »
  (flèches ↑ ↓ pour choisir, chantier actuel désactivé) ; aussi dans le menu ⋯ de la tâche. Poignée
  d'un chantier : flèches ↑ ↓ (une place), Entrée → « Déplacer le chantier… ». Les annonces du
  geste passent par une région `aria-live`.

### 4.10 Assistant (tiroir)

- Ouvert par le **bouton flottant** en bas à droite (icône de discussion, « Ouvrir l'assistant »,
  pastille quand l'assistant attend ta réponse ; la page garde une marge basse pour qu'il ne masque
  rien) et par `Ctrl+J` ; focus dans le champ à l'ouverture ; Échap ferme et rend le focus au
  bouton ; fermeture ne perd pas le brouillon.
- En-tête : « Assistant » + sélecteur de conversation (historique : titre + date) + « Nouvelle ».
- Fil : mêmes rendus que le panneau d'un agent (streaming, outils, questions).
- **Écho immédiat** du message envoyé (bulle grise « envoi… » → normale une fois livrée), champ
  verrouillé pendant l'envoi seulement, indicateur « L'assistant réfléchit… » jusqu'au premier
  token.
- **On lui parle pendant qu'il travaille**, comme à Claude Code : le champ reste actif pendant
  qu'il réfléchit ou appelle des outils. Le message s'affiche aussitôt « en attente — l'assistant
  le lira à sa prochaine étape — Annuler », et lui est livré à sa **prochaine frontière de tour**
  (après le lot d'outils en cours), sans attendre la fin de son travail ; l'écho passe alors à
  « lu ». S'il finit avant, le message est son tour suivant. Pas d'interruption implicite.
- **Interrompre** (bouton à côté d'Envoyer, visible pendant qu'il travaille, et **Échap**) coupe
  le tour en cours, appel au modèle compris, en quelques dixièmes de seconde. Rien n'est perdu :
  sa note et les résultats d'outils déjà obtenus restent, aucun tour ne reste à moitié écrit
  (le texte coupé n'est pas gardé). Il repart **aussitôt** avec les messages en attente ; sans
  message, il s'arrête et attend. Toast « Assistant interrompu : il repart avec ton message ».
- Quand tu lui donnes une **précision sur une tâche déjà lancée** (« finalement le fichier doit
  s'appeler X »), il la transmet à l'agent concerné (§4.6 « Ajouter une consigne… », ses
  sous-agents aussi s'ils sont concernés) et le dit en une ligne. Il **interrompt** l'agent
  seulement si la précision change la direction du travail : l'agent repart alors aussitôt avec.
  Le même geste existe pour les agents entre eux (outil `MessageAgent`, paramètre `interrompre`).
- Reprendre une conversation passée puis écrire **continue cette conversation**.
- **Contexte perso** (réglage) : bouton ⚙ dans l'en-tête → panneau avec la zone de texte,
  Enregistrer (occupé → « Enregistré — pris en compte à la prochaine conversation »).
- L'assistant agit **sur les mêmes objets que l'écran** (chantiers, tâches, agents) ; toute action
  qu'il fait est visible sur le Bureau au rafraîchissement suivant (≤ 5 s), et le Bureau se
  rafraîchit immédiatement quand un tour de l'assistant se termine.
- Il ne lance jamais un agent sans que la tâche existe : il crée ou complète la tâche, puis la
  lance (ce qui relie l'agent à la tâche).
- **Suivi d'un chantier** (« fais-moi le point sur le chantier X : quelles suites restent
  vraiment à faire ? », « des follow-ups ? ») : il commence par la **vision d'ensemble** du
  chantier (outil `Taches`, action `vue_ensemble`), qui rend en un appel, pour chaque tâche, son
  statut, **qui l'a créée et quand** (toi, l'assistant, la clôture de tel agent sur tel ticket,
  ou un agent lancé hors tâche), le brief résumé, ses agents et leur état, pour une tâche livrée
  le récap (fait / reste / à décider), la branche intégrée et le commit livré, ses précisions et
  retours, puis des **rapprochements** : titres ou briefs très proches, suites ouvertes par une
  livraison reprise depuis (retour envoyé, nouvelle clôture), relecture qui double une carte « À
  vérifier », même session qui a ouvert des suites à plusieurs clôtures. Puis il **agit sans
  attendre** : il marque ce qui est fait ailleurs, en double ou caduc (§4.6 « Classer sans
  lancer », commentaire signé « l'assistant »), **lance les vraies suites** en regroupant celles
  qui touchent les mêmes fichiers dans une seule tâche, laisse les **décisions** à l'utilisateur
  (elles demandent un choix humain), et rend compte : chaque marquage avec son commentaire, les
  tâches lancées, les décisions restantes. Tout se défait par « Rouvrir » (carte, ou lui). Il ne
  marque jamais une tâche dont un agent travaille et ne crée pas de nouvelle suite pour ce qu'il
  vient lui-même de déléguer.
- **Clôture sans déclaration de tâches** : son profil porte `require_taches: false`, donc
  `FinalAnswer` accepte sa clôture sans `taches_terminees` ni `taches_restantes` (il tient déjà
  la TODO via `Taches`). S'il les fournit, elles sont validées et prises en compte comme pour
  tout agent. Pour tous les autres profils, les deux champs restent obligatoires (même vides).
- **Reprise du fil après un contexte neuf** : au début d'une conversation ou au premier tour
  après un `/clear` (le contexte reste bien vidé), le prompt de l'assistant lui impose de
  recharger l'état du Bureau avant de répondre, dans un même lot : `Flotte()` (agents en cours
  avec leur `ticket_id`/`agent_id`, cartes « À traiter »), `Taches(action="lister")` (tâches en
  cours et lancées en attente de réveil) et `Decisions(action="lister")` (ce qui attend
  l'humain). Ces outils sont exposés au profil `bureau-assistant` ; aucune autre consigne de
  rechargement n'existe dans les autres profils.
- **Arbitrage en clair** : quand l'assistant a besoin d'une décision de l'humain (tâche en
  brouillon à valider, question d'agent à relayer, carte de décision), il écrit la question en
  clair dans le chat : (1) la question en une phrase (pour une question d'agent, son texte
  complet, pas seulement son id), (2) son contexte (tâche id + titre, ticket, agent source, ce
  qui a été mesuré, pourquoi la décision est nécessaire), (3) les options connues et leur
  conséquence, sans trancher à la place de l'humain. Un brouillon, une carte du Bureau, un
  simple id ou un message générique (« une décision attend ta réponse ») ne remplacent jamais
  ce texte. Consigne propre au profil
  `bureau-assistant` (test `tests/backend/profiles/test_bureau_assistant_arbitrage_en_clair.py`).
- **Ses quatre missions** (prompt `backend/profiles/builtin/bureau-assistant.yaml`) :
  1. **Tenir la TODO à jour** : il part des tâches existantes (`Taches`, `ResteAFaire`,
     `Chantiers`), les croise avec Outlook (`Mails`, `Agenda` en lecture : réunions tenues →
     actions, rendez-vous à venir → échéances), Teams (`Teams`, `Canaux`) et les fichiers que tu
     désignes (`Read`, `Glob`, `Grep`, lecture seule), puis propose ajouts et mises à jour en
     brouillon, dédoublonnés, chacun avec sa source. Rien n'est inventé.
  2. **Déléguer et suivre** : tout travail technique part à un agent ; son seul travail technique
     est de choisir les **projets** (outil `Projets` : dépôts enregistrés, état git, fichiers non
     suivis), la **cible** (`local` par défaut, `rundeck` via `bouzecode.remote`, sinon refus
     `cible_indisponible`) et les **fichiers non suivis** à transmettre (secrets jamais proposés).
     Ces choix forment le champ `execution` du lancement (docs/specs/assistant_execution.md),
     mémorisé sur la tâche, posé sur le ticket et injecté dans le prompt de l'agent. Il suit au
     niveau statut (`Flotte`, réveils « [Réveil du Bureau] », `Flotte(attendre_s=N)` borné à 600 s).
  3. **Remonter les problèmes** : bloqué → `AskUserQuestion` ; à connaître mais il continue →
     `Signaler` (consigne commune à l'assistant, au manager et au codeur). Les signalements de
     tous les agents, à toute profondeur, arrivent dans « À traiter » (carte `signalement`,
     urgence selon la gravité, acquittable) et dans le digest de réveil de chaque ancêtre.
  4. **Ne pas trancher** les décisions ; répondre court, **en français**, citer tâche (id court +
     titre), ticket et agent. Une livraison se désigne par sa tâche et son ticket, jamais par un
     SHA de commit ni un nom de branche git (bruit pour l'humain).
- **Dans le terminal** : `bouzecode --assistant` (ou `/assistant` en cours de session) lance le
  même assistant hors du serveur. Il reçoit une identité `tui:<id>` : les tâches qu'il lance lui
  sont rattachées (parent du ticket), il les suit avec `Flotte(attendre_s=N)` (pas de réveil
  automatique hors web), et les signalements de sa lignée s'affichent au-dessus du prompt.
  Lancer exige le serveur web : sinon il le dit (« lance bouzeui.ps1 »), la tâche reste brouillon.
- **Sous-agents récursifs** : tout agent peut lancer des sous-agents (`Agent`), jusqu'à
  `max_agent_depth` (défaut 4 ; au-delà refus explicite). L'isolation de l'enfant est choisie par
  le parent sur le besoin réel (`shared` par défaut, `worktree` pour des écrivains parallèles,
  `worktree_venv` s'il touche aux dépendances). Un enfant qui finit réveille son parent direct,
  qui réveille le sien. Un sous-agent arrêté dont aucun parent vivant ne peut s'occuper apparaît
  dans « À traiter ».

---

## 5. Agents (`/conversations`)

### 5.1 Disposition

Liste à gauche (redimensionnable), panneau à droite avec onglets d'agents ouverts, barre de
lancement en tête du panneau.

### 5.2 Liste des agents

- Groupes : **À traiter** (attend réponse, plan à valider, arrêté sans finir, lancement échoué) ·
  **En cours** · **Terminés** · **Archivés** (replié, chargé à la demande). Compteur par groupe.
- Carte **sur deux lignes, sans cadre** (filet fin entre les cartes, léger surlignage pour « À
  traiter ») : le **titre**, puis **une seule ligne** = état en texte coloré (icône + mot) · la
  précision la plus utile (erreur de lancement, sinon question posée, sinon activité en cours,
  sinon agent principal ou tâche liée). Heure, dépôt, branche, tâche liée et identifiant sont
  **au survol** (et dans l'en-tête du panneau). Le menu ⋯ n'apparaît qu'au survol / focus.
  Sous-agents repliables sous leur agent principal (« 3 sous-agents · 1 en cours · 1 arrêté »).
- Menu **⋯** par carte (clavier) : Ouvrir · Copier l'identifiant · Archiver / Restaurer.
- **Archiver** : effet immédiat (la carte part dans Archivés) + toast « Archivé — Annuler » 10 s.
  Archiver un agent en cours demande confirmation et l'arrête d'abord.
- **Restaurer** depuis le groupe Archivés.
- Recherche : filtre instantané sur les titres chargés + recherche plein texte (Entrée ou 400 ms)
  avec état « Recherche… », « Aucun résultat pour … », croix d'effacement ; résultats focusables.
- Défilement infini avec « Chargement de la suite… ».
- Plus d'auto-purge ni d'auto-archivage silencieux au chargement (R11).

### 5.3 Panneau d'un agent

- **En-tête** : état en texte, titre, puis une ligne de méta discrète (dépôt · branche · modèle ·
  ↗ tâche), actions : **Arrêter** (si actif) · **Continuer** / **Relancer** (si arrêté ; leur
  différence est dans leurs infobulles, pas dans un paragraphe permanent) · ⋯ (copier l'id, chemin
  de session, télécharger la session, archiver).
- **Onglets d'agents ouverts** : icône d'état seule (libellé lu par les lecteurs d'écran et en
  infobulle) + titre tronqué, point « nouveau » discret, × visible au survol / focus / onglet actif.
- Aide permanente réduite au strict nécessaire : les raccourcis clavier sont en infobulle des
  champs ; la barre de lancement garde des chips discrètes (seul « choisir un dépôt » reste
  marqué).
- **Onglets** : **Fil** · **Récap** (activé dès qu'un récap existe ; se met à jour si l'agent en
  produit un nouveau) · **Fichiers modifiés** (diffs) · **Coûts & tours** (tableau par appel LLM,
  drill-down payload annoté cached/new-cache/fresh — ex-P5 ; lien « Ouvrir l'enquête complète » et
  « Enquêter » sur chaque ligne → §5.5).
- **Fil** : messages rendus, streaming token par token, thinking repliable, outils repliables,
  marqueurs de sous-agents cliquables, bouton « ↓ Nouveaux messages » quand on a remonté.
  Chargement initial : squelette. Agent introuvable : « Cet agent n'existe plus (archivé ou
  supprimé) » + Restaurer si archivé.
- **Question / plan** : bloc en bas du fil, options (verrouillées au premier clic, sans écraser le
  brouillon du champ), réponse libre.
- **Champ de message** (toujours présent) : Entrée envoie, Maj+Entrée saut de ligne, IME respecté.
  - Agent en attente ou terminé-réutilisable : envoi direct ; **écho optimiste immédiat** ;
    rafraîchissement accéléré jusqu'à la réponse.
  - Agent en cours : le message **attend** (« lu à sa prochaine étape — Annuler | Interrompre et
    envoyer maintenant ») et lui est livré à sa prochaine frontière de tour, après le lot
    d'outils en cours. Jamais d'interruption sans geste explicite.
  - Agent arrêté/terminé non réutilisable : le champ propose « Continuer avec ce message » (relance
    la même conversation) — l'envoi crée la reprise.
- **Arrêter** : bouton explicite (plus de Ctrl+C global), « Arrêt… » → état « Arrêté ».
- Onglets du panneau : icône d'état + titre + pastille « nouveau » si l'onglet inactif a reçu du
  contenu ; fermeture au clavier ; les onglets inactifs pollent au ralenti.

### 5.4 Lancer une conversation libre

- Champ « Nouvelle conversation… » + ligne de **chips toujours visibles** : `dans [dépôt ▾]` ·
  `profil [default ▾]` · `environnement [Dépôt principal ▾]`. **Aucun dépôt deviné** : tant qu'aucun
  n'est choisi, le chip affiche « choisir un dépôt » en ambre et l'envoi demande le choix (le texte
  est conservé). Le dernier dépôt utilisé est proposé *et affiché* (mémorisé).
- Environnement (libellés) : **Dépôt principal** (shared) · **Copie isolée** (worktree) · **Copie
  isolée + dépendances** (worktree+venv) ; si le serveur bascule d'office (deux agents sur le même
  dépôt), un toast le dit.
- Envoi : bouton occupé, puis **un onglet s'ouvre immédiatement** sur l'agent en préparation, avec
  la progression par étapes ; toast « Agent lancé ». Échec (y compris en arrière-plan) : l'onglet
  affiche « Lancement échoué : raison » + « Réessayer » ; le texte reste récupérable.
- **Gérer les dépôts…** (dans le menu du chip dépôt) : dialogue Ajouter (nom, chemin, description),
  modifier la description, retirer, dossiers écartés (restaurer). Ajout → le dépôt est aussitôt
  sélectionnable et sélectionné.

---

### 5.5 Enquête (`/enquete/<agent_id>`)

But : comprendre **pourquoi un agent déraille**, ou **ce qui sature son contexte**, sans ouvrir de
JSON. Page dédiée (hors navigation principale), atteinte depuis « Coûts & tours ».

- **Tours** : frise d'un appel LLM par ligne — barre empilée cache lu / écrit au cache / plein
  tarif + sortie, marqueurs (message d'entrée, relance, rappel à l'ordre, erreur d'outil, question,
  sous-agent, clôture acceptée/refusée, note compactée, cache raté, saut de contexte) ; filtre
  « seulement les tours anormaux » ; `j`/`k` ou `←`/`→` pour naviguer. À droite, le tour à la
  loupe : chiffres de l'API, **le premier élément qui casse le préfixe** et pourquoi (nouveau,
  ajout en fin de N caractères, modifié à telle position — avant/après), chaque élément du payload
  (tokens, statut de cache, état par rapport au tour précédent, texte intégral à la demande), les
  éléments retirés, la réponse du modèle (réflexion, texte, appels d'outils et leurs entrées,
  résultats) et les appels annexes du tour. Permalien, export JSON du payload brut.
- **Note de travail** : courbe de la taille de la note par tour, compactions marquées, chaque ajout
  tour par tour (texte ajouté, texte des appels Methodology, ce qui a disparu à une compaction),
  recherche dans la note.
- **Saturation** : composition du contexte par tour (prompt système, note — prose, note — extraits
  de code, résultats d'outils, messages), et les 20 plus gros morceaux d'un tour (la note est
  découpée par section « ## »), chacun menant à l'élément.
- **Recherche** dans toute la session (note, payloads sans doublons, réponses, résultats d'outils).
- Permaliens : `#tour-103`, `#tour-103/element-1`, `#note`, `#saturation-103`, `#recherche-<mots>`.
- Mesures honnêtes : les tokens par élément sont des **estimations** ; les chiffres de l'API
  (plein tarif, cache lu, écrit) font foi et sont affichés à part. La note, qui voyage dans un bloc
  système, n'est comptée qu'une fois.

## 6. Profils (`/agent-builder`)

- **Maître/détail** : à gauche « Mes profils » (éditables) et « Fournis » (🔒 lecture seule),
  « + Nouveau profil », « Depuis le catalogue… ». À droite l'éditeur.
- Éditeur : nom, description, **capacités** par préréglage (Lecture seule · Code · Orchestration) +
  « Personnaliser » (cases, outils système masqués), skills (chips + recherche), instructions
  (zone large), « Avancé » (garde-fous avec leur valeur par défaut affichée, modèle).
- **Aperçu du prompt calculé en direct** (colonne droite, recalcul 400 ms après la dernière
  modification, squelette pendant le calcul, taille en tokens). Jamais périmé.
- Barre d'actions collante : **Enregistrer** (désactivé tant que rien n'a changé), Dupliquer, ⋯
  (Exporter, Importer, Mettre à jour les plugins de ce profil, Supprimer). « • modifié » + garde de
  navigation. Profil fourni : seul « Dupliquer pour modifier ».
- Un outil / skill du profil absent du catalogue est **affiché** (« introuvable ») et conservé à
  l'enregistrement, jamais supprimé en silence.
- **Bibliothèque** (lien secondaire) : Skills (éditeur avec nom verrouillé pour une skill existante,
  alerte « existe déjà » à la création) et Plugins (installer depuis GitLab/dossier avec
  progression, mettre à jour).
- « Utiliser ce profil » : ouvre Agents avec le profil présélectionné.

---

## 7. Critères d'acceptation testés

Chaque règle R1–R12 et chaque parcours ci-dessous a au moins un test **Playwright sur le bac à
sable** (`tests/sandbox/`, faux LLM piloté par scénario, aucun appel réseau externe) :

| # | Parcours | Preuve attendue |
|---|---|---|
| U1 | Arriver sur `/` | redirige vers `/bureau` ; mode Statut (« À traiter » en tête, groupé par ce qu'il faut faire) visible < 2 s (squelette avant) ; bascule Statut / Chantier mémorisée ; aucune tâche en double |
| U2 | Créer un chantier, lui ajouter des dépôts, le décrire, le renommer, le réordonner (glisser avec trait d'insertion, flèches sur la poignée, menu), l'archiver, le supprimer | feedback à chaque geste, Annuler après un réordonnancement, état persistant après rechargement |
| U3 | Créer une tâche (le texte va dans le brief), l'éditer (enregistrement automatique), changer son dépôt | idem ; aucune perte de saisie sur erreur serveur simulée ; texte conservé au rechargement |
| U4 | **Vérifier un travail rendu** : lancer une tâche → agent → réponse finale → « À vérifier » sous « Vérifier et clore » → Voir le travail → **Valider et clore** (Annuler) | progression visible, statut mis à jour **sans recharger**, action sur la carte sans déplier |
| U5 | **Débloquer à la main** : lancer sans dépôt / avec dépôt inconnu (refus, reste Brouillon) ; lancement impossible en fond (dépôt disparu) → « Lancement impossible » sous « Action manuelle requise » → **Corriger et relancer…** | refus explicite ; cause affichée ; l'agent repart sur le dépôt corrigé |
| U6 | **Décider** : un agent pose une question → réponse sur la carte (option puis texte libre) ; un plan à valider ; une décision laissée par un agent → **Noter ma décision…** (précision du brief, tâche close, Rouvrir) | la question apparaît sous « Décider » sans recharger, sans déplier ; l'agent reprend ; la décision est dans le brief |
| U7 | Renvoyer avec un retour | le prompt du passage 2 contient le récap du passage 1 et le retour |
| U8 | **Reprendre un agent arrêté** : planté (erreur API) → « Planté » ; arrêté à ta demande → « Arrêté par toi » ; **Continuer…** / **Relancer** | raison affichée, groupe « Reprendre un agent arrêté » ; les deux voies fonctionnent |
| U9 | Arrêter un agent en cours | confirmation, « Arrêt… », état Arrêté |
| U18 | **Ranger** : glisser une tâche vers un chantier dans une longue liste (chantiers compactés, défilement automatique), dans un chantier replié (qui s'entrouvre au survol), sur le plateau du mode Statut ; Échap annule ; au clavier (Entrée sur la poignée → « Déplacer vers… ») | rien d'envoyé sur Échap ; « Déplacement… » puis toast avec Annuler ; tâche dans le bon chantier |
| U10 | Assistant : créer une tâche, la lancer, message pendant qu'il travaille (en attente, Annuler), reprise d'historique | tâche visible sur le Bureau, historique continué |
| U20 | **Suivre ce qu'un agent a laissé** : un agent clôt avec un « reste à faire » et un « à décider » → sur son passage, chaque point dit « → tâche créée : … · statut » ; le lien montre la tâche ; un point sans tâche propose « Créer la tâche » | les tâches désignées sont celles créées à la clôture (lien enregistré, tient au renommage) ; statut à jour ; la tâche montrée est dépliée et dans la vue |
| U22 | **Classer sans lancer** : menu ⋯ → « Doublon de… » (tâche gardée obligatoire), « Marquer faite… », « Caduque… » avec un commentaire ; Annuler depuis le toast ; une tâche dont l'agent travaille | toast avec Annuler ; la ligne (Archivées) dit « Doublon de « X » — commentaire (ton commentaire, 25/09 03:12) » ; un classement de l'assistant est signé « commentaire de l'assistant » ; Annuler rouvre et l'historique garde le classement daté ; entrées désactivées avec la raison, serveur 409 |
| U23 | **Point sur un chantier par l'assistant** : « fais-moi le point sur le chantier X » | il appelle la vision d'ensemble, marque (avec commentaire) ce qui est fait ailleurs / en double / caduc, lance les vraies suites, laisse les décisions, rend compte ; tout visible sur le Bureau et réversible |
| U21 | **Brouillon de fusion archivé seul** : un brouillon « Fusionner la branche agent/XXXX » attend ; l'agent intègre lui-même sa branche | le brouillon passe dans Archivées sans geste, sa ligne dit « Archivée automatiquement : branche … intégrée le … » ; une tâche lancée qui vise la même branche n'est pas touchée |
| U19 | **Parler pendant le travail** : écrire à l'assistant pendant qu'il appelle des outils ; Interrompre (Échap) un long streaming ; Interrompre avec un message en attente ; l'assistant transmet une précision à l'agent d'une tâche en cours (ajout, puis interruption) ; un agent au repos est réveillé ; « Ajouter une consigne… » | message « lu » à la prochaine étape, AVANT la fin du travail ; résultats d'outils gardés ; l'agent voit la précision (heure, origine) à sa frontière de tour et en tient compte ; brief complété (« Précisions ajoutées ») ; carte « transmise à HH:MM — lue par l'agent » |
| U11 | Agents : lancer une conversation libre (avec et sans dépôt choisi), suivre le streaming, envoyer un message, répondre à une question, ouvrir un sous-agent | onglet ouvert au lancement, écho optimiste, streaming visible |
| U12 | Archiver / Annuler / Restaurer une conversation | toast Annuler, groupe Archivés |
| U13 | Récap, Fichiers modifiés, Coûts & tours dans le panneau | chargement puis contenu, erreurs avec Réessayer |
| U17 | Enquête : frise, tour avec rupture du préfixe, navigation clavier, note, saturation, recherche | squelette puis contenu, erreur visible avec Réessayer |
| U14 | Profils : créer, personnaliser, aperçu live, enregistrer, dupliquer un fourni, supprimer | aperçu jamais périmé, garde « modifié » |
| U15 | Serveur coupé pendant l'usage | bandeau « connexion perdue », retour automatique |
| U16 | Chaque page | zéro erreur console, navigation clavier complète, aucune ressource externe chargée |

Et au niveau unitaire (vitest) : `lib/ui.js` (busy, api, toast, confirm, dirty), `lib/states.js`
(lexique), et une **garde** qui interdit `fetch(` hors de `lib/ui.js` / `lib/poll.js`, `alert(`,
`confirm(`, `catch (_) {}` vides dans `static/js/`.
