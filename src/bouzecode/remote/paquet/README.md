# paquet

## Purpose
Ce qui part sur la VM et ce qui en revient : bundle git de la branche, diff non commite, archive des
fichiers non suivis acceptes, manifeste ; puis reimport du bundle produit par l'agent.

## Usage
- `construire_paquet(run_id, mode, commande, {slug: depot}, {slug: [fichiers]}, dossier)`.
- `trier_fichiers_non_suivis(depot, chemins, seuil_octets)` : refuse `.env*`, cles, `.exe`, liens, > seuil.
- `importer_bundle_resultat(depot, bundle, branche_distante, "agent/<ticket>")`.
