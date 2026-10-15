# Connexion Graph des scripts du Bureau : application Entra ID dediee et scopes minimaux.
# ASCII only, saved WITH a BOM (PowerShell 5.1 reads a BOM-less .ps1 as ANSI).
#
# Dot-source (comme ps/proxy.ps1) puis `Connect-BureauGraph -Scopes ... [-Legacy ...] [-Quiet]`.
#
# Application : `BOUZECODE_GRAPH_CLIENT_ID` + `BOUZECODE_GRAPH_TENANT_ID` designent
# l'application inscrite par le projet (Connect-MgGraph -ClientId -TenantId). Sans elles, on
# retombe sur l'application partagee "Microsoft Graph Command Line Tools" et on le DIT sur la
# sortie d'erreur (ligne GRAPH_APP_PARTAGEE). Un ClientId sans TenantId est refuse : une
# application mono-locataire ne s'ouvre pas sur le point d'entree commun.
#
# Scopes : chaque script demande le minimum de son action (ex. Chat.Read pour lire,
# ChatMessage.Send pour poster, au lieu de Chat.ReadWrite). Repli documente :
# `BOUZECODE_GRAPH_LEGACY_SCOPES=1` rend les anciens scopes (-Legacy) le temps que le nouveau
# consentement soit donne.

function Get-BureauGraphScopes([string[]]$Scopes, [string[]]$Legacy) {
    if ($Legacy -and ([System.Environment]::GetEnvironmentVariable('BOUZECODE_GRAPH_LEGACY_SCOPES') -eq '1')) {
        return $Legacy
    }
    return $Scopes
}

function Get-BureauGraphParams([string[]]$Scopes, [string[]]$Legacy) {
    $params = @{ Scopes = (Get-BureauGraphScopes $Scopes $Legacy); NoWelcome = $true }
    $clientId = [System.Environment]::GetEnvironmentVariable('BOUZECODE_GRAPH_CLIENT_ID')
    $tenantId = [System.Environment]::GetEnvironmentVariable('BOUZECODE_GRAPH_TENANT_ID')
    if ($clientId) {
        if (-not $tenantId) {
            throw 'BOUZECODE_GRAPH_CLIENT_ID est defini sans BOUZECODE_GRAPH_TENANT_ID : renseigner le locataire de l application Entra ID dediee.'
        }
        $params['ClientId'] = $clientId.Trim()
        $params['TenantId'] = $tenantId.Trim()
    }
    else {
        [Console]::Error.WriteLine('GRAPH_APP_PARTAGEE: BOUZECODE_GRAPH_CLIENT_ID / BOUZECODE_GRAPH_TENANT_ID absents, connexion par l application partagee Microsoft Graph PowerShell.')
    }
    return $params
}

function Test-BureauGraphDejaConnecte([string[]]$Scopes) {
    # Session deja ouverte dans CE processus avec tous les scopes voulus : ne pas reconnecter.
    $context = Get-MgContext -ErrorAction SilentlyContinue
    if (-not $context) { return $false }
    foreach ($scope in $Scopes) {
        if ($context.Scopes -notcontains $scope) { return $false }
    }
    return $true
}

# Annonce l'etape en cours sur stderr : si le process pend, le cote Python relit la
# DERNIERE ligne `BZ_ETAPE:` du stderr partiel et dit quelle etape a expire.
function Write-BureauEtape([string]$Texte) {
    [Console]::Error.WriteLine("BZ_ETAPE: $Texte")
    [Console]::Error.Flush()
}

function Connect-BureauGraph {
    param(
        [Parameter(Mandatory = $true)][string[]]$Scopes,
        [string[]]$Legacy,
        [switch]$Quiet
    )
    # Garde des tests (pytest_teams_etanche.py) : sous pytest le HOME est jetable, une
    # connexion ouvrirait une fenetre de login Microsoft. On refuse AVANT Connect-MgGraph.
    if ([System.Environment]::GetEnvironmentVariable('BZ_TESTS_TEAMS_INTERDIT') -eq '1') {
        throw 'BZ_TESTS_TEAMS_INTERDIT : connexion Graph refusee sous test, injecter un faux transport.'
    }
    $params = Get-BureauGraphParams $Scopes $Legacy
    if (Test-BureauGraphDejaConnecte $params['Scopes']) { return }
    Write-BureauEtape ("connexion scopes=" + ($params['Scopes'] -join ','))
    if ($Quiet) {
        Connect-MgGraph @params -ErrorAction SilentlyContinue | Out-Null
    }
    else {
        Connect-MgGraph @params | Out-Null
    }
}
