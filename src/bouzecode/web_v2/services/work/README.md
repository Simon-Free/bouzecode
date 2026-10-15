# services/work/

## Purpose
Le modèle "travail" : projets ouverts dans l'UI, tickets par projet et leur machine à états.

## L'état d'un ticket (lot L2, spec ticketing §3-§4)

UN état persisté, `ticket.state`, écrit par `ticket_fsm` SEUL (toute paire état × événement
absente de `fsm/etats.TRANSITIONS` → 409 `transition_refusee`, état courant dans `details`) :
`created, provisioning, launch_failed, running, awaiting_input, delivered, idle_no_delivery,
stopped, integrating, conflict, closed, abandoned`, précisé par `state_reason {code, message,
at, details?}`. `archived_at` reste un attribut orthogonal. Chaque transition écrit un
événement du journal (`ticket_events`), dans la même transaction ; les runs vivent dans la
table `runs` (au plus un run ouvert, garanti sous verrou : `/launch` en vol → 409 `deja_actif`) ;
`version` (verrou optimiste) refuse l'écriture d'un instantané périmé (409 `version_obsolete`).

Arbitrages : (1) tout geste qui crée un NOUVEAU run (lancement, relance, `merge_fix` sur un
conflit) passe par `provisioning` — c'est la bascule sous verrou qui garantit C10 ; les gestes
qui reprennent le MÊME run (message, réponse) vont droit à `running`. (2) « Conflit résolu,
prêt à intégrer » = `conflict{conflit_resolu}` ; intégrer rejoue `conflict_cleared` puis
`integrate_started`. (3) Un manager qui clôt son tour pendant que ses enfants travaillent reste
`running{attend_enfants}` (run `awaiting_children`) : il sera réveillé.

Qui écrit quoi : les ROUTES (gestes : lancer, clore, rouvrir, intégrer), le HOOK de fin
d'agent (`/completed` → `constats.fin_de_run`), le WATCHDOG (`constats.constater` : question,
réponse, fin de run sans hook, process mort, lancement figé), le RUNTIME (`runner` signale une
reprise chaude, une réponse poussée, un kill : `runs_ticket.signaler`). Aucune lecture n'écrit.
`close_reasons.issue_de_fin` est la SEULE table livré / non livré (C14).

Correspondance des anciens drapeaux (`fsm/correspondance.py`, migration de boot) — dans
l'ordre de priorité de l'ancien libellé, la première règle qui s'applique gagne :

| Ancien drapeau | state | state_reason.code |
|---|---|---|
| `worktree.state` integrated / cleaned | closed | integre |
| `ephemeral` + `reaped` | closed | ephemere |
| `crashed` | stopped | crashed |
| `worktree.state` needs_attention (non clos) | delivered | merge_bloque |
| `closure_blocked` | delivered | cloture_bloquee |
| `uncommitted` / `recolte_bloquee` | delivered | livraison_non_commitee |
| `launch_failed` « arrêté pendant la préparation » | stopped | arret_preparation |
| `launch_failed` | launch_failed | lancement_echoue |
| `done` + `closed.outcome = abandoned` | abandoned | abandonne |
| `done` | closed | accepte |
| `launching` sans run (récent / > 30 min) | provisioning / launch_failed | — / lancement_interrompu |
| `worktree.state` conflict / conflict_resolved | conflict | conflit / conflit_resolu |
| aucun run | created | — |
| `awaiting_reply`, run ouvert, run `remote` en cours | running (confirmé sur le vrai process au boot) | — |
| run `remote` en échec | stopped | crashed |
| dernier run `completed` (ou `validate*` hérité) | delivered | — |

`arret_demande` devient un événement du journal (`arret_demande` / `arret_leve`), `reaped` et
`worktree.state` retiré deviennent `worktree.retire_at` ; les anciens champs sont gardés sous
`legacy`, rien n'est supprimé.

## Horodatages : une forme écrite, deux formes lues (`services/horodatage.py`)

Toute date persistée dans le store (`tickets.db` : `created_at`, `ticket_events.at`,
`state_reason.at`, runs, micros, précisions, signalements, décisions, tâches…) ou servie par
l'API s'écrit par `horodatage.maintenant_iso()` : **UTC, décalage explicite**
(`2026-10-06T08:12:34+00:00`). Plus aucun `datetime.now().isoformat()` naïf (un test,
`test_horodatage.py`, l'interdit dans `web_v2/` et `remote/`).

La base porte encore l'**héritage** : heures LOCALES naïves (`2026-10-06T10:12:34`), `asked_at`
locaux à décalage (`+02:00`), `started_at` du runner en `…Z`. **Aucune migration** ne les
réécrit : elles restent telles quelles et se lisent par un chemin unique.

- `lire_instant(v)` → instant UTC conscient ; une valeur **naïve = heure locale** de la
  machine (la lire comme UTC décale de 1 à 2 h — l'incident qui a fait accuser le mauvais
  process d'une écriture). Accepte aussi `Z`, séparateur espace, epoch, `datetime`.
- `age_s(v, reference=None)` : âges, TTL, fenêtres (« depuis », `< 7 jours`, lancement figé) ;
  jamais `datetime.now() - …` (TypeError dès qu'un côté porte un fuseau).
- `cle_chrono(v)` : clé de tri ; trier les chaînes brutes mélange les formes.
- `heure_locale(v, fmt)` : texte destiné à un humain, toujours en heure locale.
- Front : `static/js/time_format.js::parseInstant` lit les mêmes formes (naïf = local).

Limite connue : les `ORDER BY` SQL sur une colonne de date comparent des chaînes ; pendant les
~2 h qui suivent le passage à l'UTC, une date neuve peut se ranger avant une ancienne date
locale plus vieille. Les lecteurs qui en dépendent (dernier signe d'une ligne du Bureau)
prennent le max des instants lus, pas la dernière ligne. La clé de dédoublonnage des décisions
(`decisions.dedup_key`) lit la minute en heure locale pour retomber sur les clés existantes.

## Usage
- `ticket_fsm.py` — `transition()` (pure), `appliquer()` (persistée), `motiver()`, `events()`,
  `noter()` ; `TransitionRefusee`, `DejaActif`, `VersionObsolete`.
- `fsm/` — table des états, stockage des runs et du journal, correspondance, migration.
- `etat_ticket.py` — projection PURE de l'état : `vue()` (fiche, liste), `vue_rattachee()`
  (arbre, Bureau, inbox : `ticket_state`, `libelle_ticket`), `statut()` (mot historique).
- `constats.py` — détection → événement : `fin_de_run()` (hook), `constater()` (watchdog).
- `constats_fin.py` — `fin_de_run()` et `enfants_actifs()` (ré-exportés par `constats`) : la fin
  d'un run → livré / non livré / arrêté / en attente des enfants, crash démenti par un hook tardif.
- `runs_ticket.py` — `set_launching()`, `add_run()`, `mark_run_completed()`, `signaler()`.
- `_ligne_ticket.py` — codec d'une ligne (hydratation, écriture conditionnelle à la version).
- `projects.py` — registre `~/.bouzecode/web_v2/projects.json` : `list_projects()`,
  `add_project()`, `find()`, `agents_of()` (agents web dont cwd ⊂ path),
  `overview()` (compteurs d'actions requises par projet pour la home)
- `distant/` — runs `remote` (exécutions Rundeck) : pose, suivi par le watchdog, réveil.
- `tickets.py` — façade : CRUD tickets (`create_ticket`, `get_ticket`, `poser` — champs
  ordinaires sur la version fraîche —, `update_ticket` sous condition de version), commentaires
  (événements `comment`), `ticket_summary()`, `list_tickets()`.
- `_persistence.py` / `_store_connection.py` — store SQLite/WAL des tickets. La connexion
  est UNE par thread et par base, gardée ouverte ; chaque bloc finit par `commit` ou `rollback`.
- `_status.py` — `derive_status(ticket)` : le mot historique, PROJECTION de `ticket.state`.
- `delivery.py` — le chaînon entre « l'agent a fini » et « son travail existe quelque
  part ». En fin de run le watchdog CONSTATE seulement (`record_delivery` : tête de branche,
  `worktree.non_commites`) ; la récolte (`worktrees.harvest`, le seul commit du WIP) n'a lieu
  que juste avant un geste DEMANDÉ, aucun run vivant : intégration, nettoyage, relance
  re-isolée (`harvest_before_reclaiming` rend False si l'arbre reste sale → rien n'est
  détruit). Une récolte demandée qui échoue laisse `worktree.non_commites` et, sur un ticket
  livré, la raison `delivered{livraison_non_commitee}` (« Bloqué »)
- `cloture_ticket.py` — `clore(outcome, reason)` / `rouvrir()` : transitions `closed` /
  `abandoned` / `reopened`, idempotentes, réversibles, ne touchent jamais au worktree (C5a) ;
  clore est la porte de sortie du garde-fou de clôture
- `nettoyage.py` — `POST …/cleanup` : `preparer()` (gardes à l'instant : run vivant sur le
  vrai process, récolte propre) puis `retirer()` (worktree retiré, branche gardée) ;
  `constater_disparition()` (unarchive, C5b) ; `nettoyer_le_projet()` (suppression de projet)
- `conflits.py` — un conflit de merge est RENVOYÉ par `integration` ; le watchdog constate sa
  résolution dans le worktree (`conflict{conflit_resolu}`) et le signale, sans jamais ré-intégrer
- `interruptions_boot.py` — au boot, chaque sous-agent interrompu est signalé à son parent
  (message en file) ou à l'humain (signalement). Remplace `auto_resume` : rien n'est relancé
- `branch_rescue.py` — aucun commit d'agent ne disparaît lors d'une relance :
  `resume_on_branch()` re-sort la branche `agent/<ticket>` telle quelle (le nouvel agent
  repart du travail commité) et `drop_branch()` tague `rescue/...` le tip d'une branche
  qui porte du travail avant de la supprimer. Utilisé par `worktrees.discard_stale()` et
  `dispatch.reisolate()`, qui recréaient la branche depuis la base — donc effaçaient sa
  livraison, reflog compris.
- `awaiting.py` — ce qui réclame un geste HUMAIN, en deux listes exploitables sans lire
  un log : `agents_awaiting_answer()` (les agents bloqués sur une question, AVEC son
  texte, ses options, `allow_freetext` et `asked_at` — servi par `GET /api/agents?state=awaiting_input`)
  et `unreachable_ticket_agents()` (les tickets ouverts dont l'agent n'a plus
  d'enregistrement, donc injoignable — `GET /api/agents?state=unreachable`). Ne redérive aucune
  règle : l'attente vient de `store.agent_status`, l'introuvable de `stopped{introuvable}`.
- `activity.py` — CE QUE FAIT un agent vivant, en une phrase : `describe(status, meta)` (pur)
  rend `activity_label` (« Bash en cours depuis 3 min », « appel au modèle », « attend une
  réponse »), l'âge du dernier battement IPC et `stale` (silence > 4 min sur un « en cours »,
  signalement, jamais un verdict) ; `report()` recense la flotte pour `GET /api/agents/activity`
  (aucun git, aucun prompt, aucun agent terminé). Source vivante : `status["tools"]`, publié par
  `dag._announce_activity` au démarrage de chaque lot d'outils — le SEUL signal disponible
  pendant l'exécution d'un outil (le flux partiel est déjà effacé, la session pas encore sauvée)
- `activity_parc.py` — le recensement derrière `activity.report()` : une ligne par agent vivant
  et par ticket en lancement, rangées (attentes, silencieux, autres) ; lit le store, aucun git.
- `launch_phase.py` — la phase COURANTE d'un lancement, écrite à chaque étape :
  `set_phase()` / `clear_phase()` / `drop_phase()` / `phase_view()` (libellé rendu côté serveur,
  mots UNIQUES pour l'UI et l'API). Vocabulaire fermé : création du worktree (avec le n° d'essai
  raté), installation de l'environnement uv, démarrage de l'agent, ré-isolation. Détail de
  l'état `provisioning`, retirée par toute transition qui en sort (`ticket_fsm`)
- `worktree_disk.py` — le VRAI poste disque : les `.venv` des bacs à sable (81 Go des 104 Go
  de `~/.bouzecode` — 166 worktrees, ~1 Go chacun, jamais partagés). `inventory()` classe chaque
  venv (`agent_vivant` / `ouvert` / `terminal` / `inconnu`), `reclaim_venvs(confirm=True)`
  supprime ceux des deux dernières classes — et RIEN d'autre : un venv se refait par `uv sync`,
  le code et le travail non commité restent. ⚠️ `is_link` / `crosses_link` sont la garde
  essentielle : cet arbre contient des JONCTIONS vers les vrais dépôts
  (`worktree_sources.link_editable_sources`), et les avoir prises pour des bacs à sable a effacé
  le `.venv` du dépôt principal le 2026-07-30
- `warm_pool.py` — le SEUL chemin qui tue des process d'agents sans qu'un humain le demande :
  `sweep_warm_pool()` évince les chauds en trop (LRU sur `last_activity`, plafond
  `WARM_POOL_MAX`). Sorti de `fleet` parce que construire une vue et terminer des process sont
  deux gestes opposés — et les garder ensemble avait déjà coûté : le ménage tournait DANS le
  calcul de l'arbre, donc un simple `GET /api/agents/tree` tuait des process et la cadence
  d'éviction suivait le poll de l'interface. Appelé explicitement à la création d'un ticket lancé et au
  tick du watchdog. Inerte sous pytest (`runner.destruction_permitted`)
- `parc.py` — LA collecte du parc (`collecter`) et le relevé commun d'un agent (`releve` :
  état, question, projet, ticket) : `GET /api/agents` (`api_tickets/agents_vue`) et
  `GET /api/agents/tree` (`fleet`) en dérivent tous deux — une seule source (lot L6).
- `fleet.py` — l'arbre (`agent_tree`, mémorisé), son habillage et les archivés ;
  `fleet_noeuds.py` — les nœuds (agent, `launching/<ticket>`, `failed/<ticket>`) ;
  `fleet_arbre.py` — tri, git préchauffé, récap hérité, vivacité propagée, lexique d'un nœud.
- `fleet_cache.py` — cache des pages d'arbre : `cached(key, compute)` sert la version connue
  IMMÉDIATEMENT et recalcule en fond si elle est périmée, avec un verrou PAR CLÉ. Mesuré :
  l'arbre coûte 2,2 s (15 racines) à 9,45 s (complet) ; un verrou global faisait attendre le
  poll de l'interface derrière l'arbre complet d'un agent de monitoring
- `fleet_live.py` — `overlay(page)` relit À CHAQUE LECTURE les champs volatils
  (`VOLATILE_FIELDS` : phase de démarrage, activité) des nodes VIVANTS d'une page d'arbre
  mémorisée, et les RETIRE des nodes qui ne le sont plus. Le badge de la sidebar accusait
  sinon 6,56 s de retard sur une phase que le serveur détenait déjà (mesuré le 2026-08-04).
  Baisser le TTL a été écarté à la mesure : recalculer la page coûte 383 ms, recenser les
  agents vivants 22-64 ms — et la surcouche est exacte, là où un TTL reste un retard
- `closure_guard.py` — garde-fou de clôture d'un manager (pur, zéro I/O) :
  `refuse_closure(slug, parent, children)` refuse la clôture tant qu'un enfant a planté
  sans preuve de livraison (`child_delivered_something`), dispense les enfants
  archivés/clos/fauchés (`child_excused`), trace le blocage une seule fois
  (`delivered{cloture_bloquee}` + commentaire nommant l'enfant) ; `force_closure()` est la
  porte de sortie humaine, câblée sur `POST /api/projects/<slug>/tickets/<id>/close`
- `wake.py` / `wake_parents.py` — le watchdog (`tick`) ; réveil et clôture des managers
  (`process_wakes`) ; `wake_predicats.py` — prédicats PURS de réveil lus sur `ticket.state`
  (ré-exportés par `wake`).
- `tick_annexes.py` — gestes globaux du tick : pool chaud, DRAIN des vérifications différées des
  agents finis (jamais depuis une lecture, lot L6), rattrapage du Bureau.
- `dispatch.py` — lancement de l'agent d'un ticket déjà créé (`_launch`, `_launch_bg`), échec
  gravé ; plus aucun routage par intention (la création passe par `api_tickets/creation.py`).
- `digest_manager.py` — `digest_du_manager()` (ré-exporté par `wake_parents`) : le message qui
  réveille un manager, preuve de chaque enfant, mort-nés et questions en attente.
- `unmerged.py` — commits et fichiers de code d'une branche absents de sa base (`delivery`),
  seul git du Bureau, au tick seulement ; `unmerged_memoire.py` — ses mémoires (refs lues une
  fois par passe, comptes immuables par couple base..tip), sans aucun process.
- `taches_passage.py` — l'état d'un passage du Bureau, projection de `ticket.state`.

## Le watchdog (`wake.tick`, toutes les 8 s, serveur de référence seulement)

Il OBSERVE et SIGNALE ; il ne décide de rien (spec ticketing §5.7, principe B4). Ses constats
deviennent des transitions de `ticket_fsm` (`constats.constater`).

| Fait encore | Ne fait plus |
|---|---|
| Constater un process mort sans clôture → `stopped{crashed}` + réveil du parent | Commiter le WIP d'un agent (au crash, en fin de run, ou pendant qu'il tourne) |
| Constater une fin de run sans hook (clôture lue sur la session ou l'IPC) → `delivered` / `idle_no_delivery` / `stopped` | Relancer le codeur sur un conflit, re-merger un conflit résolu |
| Constater une question posée / répondue → `awaiting_input` / `running` | Reprendre au boot les sous-agents interrompus (`auto_resume`) |
| Constater un lancement figé (> 30 min) → `launch_failed{lancement_interrompu}` | Valider une livraison (validateur de tickets, D1) |
| Constater un conflit résolu → `conflict{conflit_resolu}` et le signaler | Évincer le pool chaud depuis une lecture |
| Réveiller un parent quand ses enfants ont fini ou bloquent sur une question | Retirer le worktree d'un ticket archivé, ou d'un arbre sale |
| Livrer la file de messages ; suivre les runs Rundeck ; faucher un ticket MERGÉ propre | Redériver un état à la lecture (cinq dérivations retirées au lot L2) |

Il ne paie la réconciliation que pour les tickets en vol (`ticket_needs_watchdog`, pur) ; les
gestes qui décident — intégrer, clore, rouvrir, nettoyer, relancer — sont des routes.
