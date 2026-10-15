# ui/tickets_cli/

## Purpose
`bouzecode tickets …` et `bouzecode projets …` : l'équivalent en ligne de commande de l'API
tickets, utilisable SANS le serveur web (mêmes services que les routes, appelés en process).

## Usage
```
bouzecode projets fichiers demo --indices plan          # non suivis : + proposé, ! secret
bouzecode tickets creer --projet demo --titre "b" --prompt "Ajoute b.txt" [--isolation worktree]
          [--cible rundeck --mode tests --commande-tests "tests -x" --no-navigateur]
          [--fichier notes/plan.md --fichier autre:doc.md --projets-sup autre] [--brouillon]
bouzecode tickets suivre demo <id>        # attend la fin ; code 0/3/4/5/6/7
bouzecode tickets lister [--projet demo] [--etat running,delivered] | voir demo <id>
bouzecode tickets lancer|message|stop|integrer|clore|rouvrir demo <id> ...   (--json partout)
```

Coexistence (`serveur.py`) : serveur de référence vivant (verrou du parc) → les écritures
passent par son API (jeton local) et `suivre` ne fait que lire ; sinon tout se fait en process
et `suivre` joue le pas du watchdog (constats, Rundeck, file de messages) sous le verrou.

| Fichier | Rôle |
|---|---|
| `__init__.py` | `main(argv)`, lectures, routage |
| `parseur.py` | arguments et aide |
| `gestes.py` | écritures : en process ou HTTP |
| `serveur.py` | détection du serveur, appel HTTP, `ErreurGeste` |
| `suivi.py` | `suivre`, codes de sortie |
| `rendu.py` | sortie lisible |
