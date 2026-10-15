# `ps/` — le seul code qui parle vraiment à Graph

## Purpose
Le jeton délégué vit dans le cache MSAL .NET (DPAPI), que Python ne sait pas lire :
`Connect-MgGraph` s'y reconnecte silencieusement, c'est donc PowerShell qui détient
l'authentification.

| Script | Rôle |
|---|---|
| `graph_activite.ps1` | LECTURE : mails, chats Teams, messages, canaux (outils `Mails`, `Teams`, `Canaux`) |
| `graph_bureau.ps1` | Outlook/agenda : brouillon (rien ne part), créneau, réunion |
| `graph_auth.ps1` | `Connect-BureauGraph` : scopes minimaux, application dédiée, garde des tests, réutilisation du contexte |
| `proxy.ps1` | proxy d'entreprise |

## Usage
- `Connect-BureauGraph -Scopes ...` ne reconnecte pas si le processus porte déjà un contexte
  Graph avec ces scopes (`Get-MgContext`), et refuse de se connecter quand
  `BZ_TESTS_TEAMS_INTERDIT=1` (posé par pytest).
- stdout = un objet JSON compact ; échec = code 1 + `{"error": {"code", "message", "action"}}`,
  `code = "AuthenticationError"` pour une panne de jeton.
- **ASCII pur, enregistré AVEC BOM** : PowerShell 5.1 relit un `.ps1` sans BOM en ANSI.
