# distant/

## Purpose
Raccord entre les tickets du serveur web et `bouzecode.remote` (execution sur Rundeck rec) :
un lancement accepte pose un run `kind="remote"`, le watchdog le suit, rapatrie le resultat,
clot le run et laisse le reveil ordinaire prevenir le parent.

## Usage
- `runs.py` : `ajouter(slug, ticket, resultat, mode)`, `est_distant(run)`, `vivacite(run)`
  (`running|delivered|crashed`, lue sur le run, jamais sur un process), `terminer(...)`,
  `etiquette(run)` / `preuves(run)` (digest de reveil), `vue_passage(run)` (Bureau).
- `suivi.py` : `suivre_tickets(slug, rows)`, appele par `wake.tick` ; `suivre` au plus une
  fois par `CADENCE_S` (30 s) et par execution, `recuperer` a la fin ; echec = ticket
  `crashed` + signalement ; fin d'agent maitrisee sans livraison (refus du modele, fin
  forcee, lue dans `resultat.json`) = `idle_no_delivery`, refus signale par `refus_modele`.
- `rapport.py` : `issue_de_l_agent(resultat)` (via `close_reasons`), raison d'echec et
  `reponse.md` lue par le digest.
- `retour.py` : `preparer(slug, ticket, branches)` — worktree local de chaque branche
  rapatriee (emplacement de `worktrees.provision`), `ticket.worktree` pour le depot principal
  (integrate suit le chemin local), `ticket.worktrees_secondaires` pour les autres.
- `noeuds.py` : noeuds `remote/<ticket>` de l'arbre de flotte.
