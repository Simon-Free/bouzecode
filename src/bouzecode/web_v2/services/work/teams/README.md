# teams/ — accès Microsoft Graph en LECTURE

## Purpose
La frontière process vers Graph : l'outil `Teams` de l'agent (et `Mails`, `Canaux`) lit les
messages de l'humain via `ms_activite.py` → `graph_transport.PowerShellTransport` →
`ps/graph_activite.ps1`. Rien n'écrit dans Teams : l'ancien pont vers le chat (sonnette,
sondage, abonnement push, flux Power Automate) a été retiré, l'écriture étant obsolète.

## Usage
- `graph_transport.PowerShellTransport(script, runner=None, timeout=90)` : `_call(action, **params)`
  lance `script -Action <action> -Param valeur`, rend le JSON, lève `TeamsAuthError`
  (reconnexion nécessaire) ou `TeamsTransportError`.
- Tests : injecter un FAUX Teams par `runner=lambda args: (0, '{"value": []}', "")`. Lancer un
  vrai script de `ps/` sous pytest échoue (`tests/pytest_teams_etanche.py`).

## Subfolders
| Folder | Description |
|--------|-------------|
| `ps/` | scripts PowerShell Graph et leur connexion commune (`graph_auth.ps1`) |
