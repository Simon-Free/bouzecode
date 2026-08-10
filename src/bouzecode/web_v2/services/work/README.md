# services/work/

## Purpose
Le modèle "travail" : projets ouverts dans l'UI et tickets par projet.

## Usage
- `projects.py` — registre `~/.bouzecode/web_v2/projects.json` : `list_projects()`,
  `add_project()`, `find()`, `agents_of()` (agents web dont cwd ⊂ path),
  `overview()` (compteurs d'actions requises par projet pour la home)
- `tickets.py` — `~/.bouzecode/web_v2/tickets/<slug>.json` : CRUD tickets,
  `add_run()` (kind work|validate|merge), `add_comment()`,
  `refresh_verdicts()` (parse `VERDICT: OK|KO` du dernier message assistant),
  `parent_agent_ids()` (agent_ids ayant réellement un ticket enfant), `VALIDATORS`
- `_persistence.py` / `_store_connection.py` — store SQLite/WAL des tickets. La connexion
  est UNE par thread et par base, gardée ouverte : l'ouvrir coûte 30 à 130 ms sur le store
  réel contre 0,03 ms une fois ouverte, et le board en ouvrait ~101 par requête. La
  réutilisation ne coûte aucune fraîcheur (hors transaction, WAL relit le dernier état
  commité à chaque instruction) ; chaque bloc finit par `commit` ou `rollback`.
- `_status.py` — `derive_status(ticket, parents_with_children=None)` (pur) :
  planté → merge bloqué → clôture bloquée → **livraison non commitée** → terminé →
  en cours → attend réponse → en attente des enfants (seulement si un enfant existe)
  → échec validation → validé → à relire
- `delivery.py` — le chaînon entre « l'agent a fini » et « son travail existe quelque
  part ». `needs_delivery_harvest()` (garde pure) et `harvest_delivery()` (action de
  `workflow.TRANSITIONS`) commitent le travail d'une livraison propre sur la branche
  `agent/<ticket>` ; si le worktree reste sale, le ticket porte `uncommitted` (→ statut
  « livraison non commitée », vivacité `stalled`). `harvest_before_reclaiming()` est
  appelée par `reaper.reap_archived()` juste avant de détruire un worktree, et
  `reopen_for_new_work()` annule le quitus de récolte quand l'agent est relancé.
  Existe parce que le seul harvest du chemin de SUCCÈS vivait dans le test-gate,
  supprimé avec la chaîne automatique : seul le harvest du CRASH avait survécu.
- `branch_rescue.py` — aucun commit d'agent ne disparaît lors d'une relance :
  `resume_on_branch()` re-sort la branche `agent/<ticket>` telle quelle (le nouvel agent
  repart du travail commité) et `drop_branch()` tague `rescue/...` le tip d'une branche
  qui porte du travail avant de la supprimer. Utilisé par `worktrees.discard_stale()` et
  `dispatch.reisolate()`, qui recréaient la branche depuis la base — donc effaçaient sa
  livraison, reflog compris.
- `awaiting.py` — ce qui réclame un geste HUMAIN, en deux listes exploitables sans lire
  un log : `agents_awaiting_answer()` (les agents bloqués sur une question, AVEC son
  texte, ses options, `allow_freetext` et `asked_at` — servi par `GET /api/agents/awaiting`)
  et `unreachable_ticket_agents()` (les tickets ouverts dont l'agent n'a plus
  d'enregistrement, donc injoignable — `GET /api/agents/unreachable`). Ne redérive aucune
  règle : l'attente vient de `store.agent_status`, l'introuvable de `liveness.MISSING`.
- `activity.py` — CE QUE FAIT un agent vivant, en une phrase : `describe(status, meta)` (pur)
  rend `activity_label` (« Bash en cours depuis 3 min », « appel au modèle », « attend une
  réponse »), l'âge du dernier battement IPC et `stale` (silence > 4 min sur un « en cours »,
  signalement, jamais un verdict) ; `report()` recense la flotte pour `GET /api/agents/activity`
  (aucun git, aucun prompt, aucun agent terminé). Source vivante : `status["tools"]`, publié par
  `dag._announce_activity` au démarrage de chaque lot d'outils — le SEUL signal disponible
  pendant l'exécution d'un outil (le flux partiel est déjà effacé, la session pas encore sauvée)
- `launch_phase.py` — la phase COURANTE d'un lancement, écrite à chaque étape :
  `set_phase()` / `clear_phase()` / `drop_phase()` / `phase_view()` (libellé rendu côté serveur,
  mots UNIQUES pour l'UI et l'API). Vocabulaire fermé : création du worktree (avec le n° d'essai
  raté), installation de l'environnement uv, démarrage de l'agent, ré-isolation. Retirée par
  `tickets.add_run` et `dispatch.record_launch_failure`
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
  d'éviction suivait le poll de l'interface. Appelé explicitement au `POST /api/dispatch` et au
  tick du watchdog. Inerte sous pytest (`runner.destruction_permitted`)
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
  `refuse_closure(slug, parent, children)` refuse `done` tant qu'un enfant a planté
  sans preuve de livraison (`child_delivered_something`), dispense les enfants
  archivés/acquittés/fauchés (`child_excused`), trace le blocage une seule fois
  (flag `closure_blocked` + commentaire nommant l'enfant) ; `force_closure()` est la
  porte de sortie humaine, câblée sur `POST /api/tickets/<slug>/<id>/done`
