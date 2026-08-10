# scope_guard

## Purpose
Garde-fou de **périmètre** au dispatch d'un ticket enfant. Il répond mécaniquement à deux
questions qu'aucun prompt ne garantit :

1. **Ce ticket recouvre-t-il un ticket frère déjà ouvert ?** Un manager peut dispatcher
   plusieurs écrivains sur le même livrable (cas réel : trois implémentations concurrentes
   du même service, deux jetées). La comparaison porte sur les *ancres* du prompt — tables,
   routes, chemins de modules — pondérées face au vocabulaire ordinaire.
2. **Son prompt impose-t-il la lecture seule alors que sa typologie accorde l'écriture ?**
   « READ-ONLY » en prose ne provisionne rien : un ticket read-only confié à `coder` reçoit
   `Write`/`Edit`/`Bash` et écrira du code de production.

Il **signale, il ne refuse pas** : drapeau + commentaire sur le ticket (visibles en UI) et
avertissement rendu au manager dans son `tool_result` — le seul acteur capable de corriger
le découpage. Un refus sur jugement heuristique bloquerait des dispatches légitimes.

## Usage
```python
from bouzecode.web_v2.services import scope_guard

warnings = scope_guard.review_dispatch(slug, ticket_id, prompt, typology, parent)
```
Branché sur `POST /api/dispatch` (`routes/work/fleet.py`), qui recopie `warnings` dans
`result["scope_warnings"]`. L'outil `Agent` (`backend/multi_agent/tools.py`) les ajoute au
compte rendu du manager.

Drapeaux posés sur le ticket : `scope_overlap` (liste d'ids frères) et
`readonly_mandate_unenforced` (liste d'outils d'écriture accordés).

| Module | Rôle |
|--------|------|
| `signature.py` | Réduit un prompt à son périmètre (ancres + mots distinctifs) et compare deux périmètres. |
| `overlap.py` | Trouve les tickets frères en doublon de périmètre ; seuil calibré sur des prompts réels. |
| `readonly.py` | Détecte un mandat read-only contredit par les outils réellement accordés. |
| `review.py` | Point d'entrée serveur : applique drapeaux et commentaires, rend les avertissements. |
