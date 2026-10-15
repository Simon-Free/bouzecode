# Delegated Graph WRITES for the Bureau: draft a mail, block a slot, book a meeting.
# Sibling of graph_activite.ps1 on purpose: same conventions, same proxy.
# It is a SEPARATE script so that the read-only path keeps read-only scopes. Here each
# action connects with its OWN minimal scope, like graph_activite.ps1 does.
# ASCII only, saved WITH a BOM (PowerShell 5.1 reads a BOM-less .ps1 as ANSI and breaks).
# Every action prints ONE compact JSON object on stdout. On failure: exit code 1 plus a
# JSON error object, whose `code` is what the Python side turns into TeamsAuthError.
#
# INVARIANT: action 'brouillon' NEVER sends. A message created with POST /me/messages
# lands in the Drafts folder; the human validates and sends it from Outlook. That IS the
# human validation asked for on 2026-09-21 - there is no send action in this file.
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('brouillon', 'creneau', 'reunion')]
    [string]$Action,
    # Action 'brouillon': comma separated addresses, subject, and the body read from a file
    # (a file, not the command line: no quoting hell, no command line length limit).
    [string]$Destinataires,
    [string]$Cc,
    [string]$Objet,
    [string]$CorpsPath,
    # Actions 'creneau' and 'reunion': local wall clock times, e.g. 2026-09-22T09:00:00.
    # The caller owns the window; this script never decides a date itself.
    [string]$Sujet,
    [string]$Debut,
    [string]$Fin,
    [string]$Fuseau = 'Romance Standard Time',
    # Action 'reunion' only: comma separated attendees.
    [string]$Participants
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# Same proxy handling as the Teams transport: see ps/proxy.ps1 (no-op without env vars).
. "$PSScriptRoot\proxy.ps1"
Set-BureauProxy
# Application Entra ID dediee et scopes minimaux : voir ps/graph_auth.ps1.
. "$PSScriptRoot\graph_auth.ps1"

$GraphRoot = 'https://graph.microsoft.com/v1.0'

function Write-Payload($Payload) {
    $Payload | ConvertTo-Json -Depth 20 -Compress
}

function Require-Param($Value, $Name) {
    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "Missing required parameter -$Name for action '$Action'."
    }
}

# 'a@x, b@y' -> the Graph recipient array. Empty entries are dropped: a trailing comma
# would otherwise produce a recipient with an empty address, which Graph rejects.
function To-Recipients([string]$Liste) {
    $sortie = @()
    foreach ($brut in ($Liste -split ',')) {
        $adresse = $brut.Trim()
        if ($adresse) {
            $sortie += @{ emailAddress = @{ address = $adresse } }
        }
    }
    return $sortie
}

function To-Attendees([string]$Liste) {
    $sortie = @()
    foreach ($brut in ($Liste -split ',')) {
        $adresse = $brut.Trim()
        if ($adresse) {
            $sortie += @{ emailAddress = @{ address = $adresse }; type = 'required' }
        }
    }
    return $sortie
}

function Read-Corps([string]$Chemin) {
    if ([string]::IsNullOrWhiteSpace($Chemin)) { return '' }
    return (Get-Content -LiteralPath $Chemin -Raw -Encoding UTF8)
}

try {
    switch ($Action) {

        # Deposer un brouillon. POST /me/messages CREE sans envoyer: le message atterrit
        # dans Brouillons. Il n'existe deliberement aucune action /send ici.
        'brouillon' {
            Require-Param $Destinataires 'Destinataires'
            Require-Param $Objet 'Objet'
            Connect-BureauGraph -Scopes 'Mail.ReadWrite'

            $message = @{
                subject      = $Objet
                body         = @{ contentType = 'Text'; content = (Read-Corps $CorpsPath) }
                toRecipients = (To-Recipients $Destinataires)
            }
            if (-not [string]::IsNullOrWhiteSpace($Cc)) {
                $message['ccRecipients'] = (To-Recipients $Cc)
            }
            $body = $message | ConvertTo-Json -Depth 10
            $cree = Invoke-MgGraphRequest -Method POST -Uri "$GraphRoot/me/messages" -Body $body -ContentType 'application/json'
            Write-Payload $cree
        }

        # Bloquer du temps: un evenement sans participant, marque occupe. Aucune invitation
        # ne part, donc aucune validation humaine n'est demandee (choix du 2026-09-21).
        'creneau' {
            Require-Param $Sujet 'Sujet'
            Require-Param $Debut 'Debut'
            Require-Param $Fin 'Fin'
            Connect-BureauGraph -Scopes 'Calendars.ReadWrite'

            $evenement = @{
                subject  = $Sujet
                start    = @{ dateTime = $Debut; timeZone = $Fuseau }
                end      = @{ dateTime = $Fin; timeZone = $Fuseau }
                showAs   = 'busy'
                isOnlineMeeting = $false
            }
            $body = $evenement | ConvertTo-Json -Depth 10
            $cree = Invoke-MgGraphRequest -Method POST -Uri "$GraphRoot/me/events" -Body $body -ContentType 'application/json'
            Write-Payload $cree
        }

        # Organiser une reunion Teams: invitations envoyees par Graph, lien de jointure
        # rendu dans onlineMeeting.joinUrl.
        'reunion' {
            Require-Param $Sujet 'Sujet'
            Require-Param $Debut 'Debut'
            Require-Param $Fin 'Fin'
            Require-Param $Participants 'Participants'
            Connect-BureauGraph -Scopes 'Calendars.ReadWrite'

            $evenement = @{
                subject               = $Sujet
                start                 = @{ dateTime = $Debut; timeZone = $Fuseau }
                end                   = @{ dateTime = $Fin; timeZone = $Fuseau }
                attendees             = (To-Attendees $Participants)
                isOnlineMeeting       = $true
                onlineMeetingProvider = 'teamsForBusiness'
            }
            $corps = Read-Corps $CorpsPath
            if ($corps) {
                $evenement['body'] = @{ contentType = 'Text'; content = $corps }
            }
            $body = $evenement | ConvertTo-Json -Depth 10
            $cree = Invoke-MgGraphRequest -Method POST -Uri "$GraphRoot/me/events" -Body $body -ContentType 'application/json'
            Write-Payload $cree
        }
    }
}
catch {
    # Meme classification que graph_activite.ps1 (version LARGE): un refus de consentement
    # Mail.ReadWrite / Calendars.ReadWrite arrive en Forbidden ou Authorization_RequestDenied.
    # Sans ces deux motifs, le Python le prendrait pour une panne quelconque et l'agent ne
    # dirait pas a l'humain qu'il y a un consentement a accorder.
    $message = $_.Exception.Message
    $code = 'PowerShellFailure'
    if ($message -match 'AADSTS|InvalidAuthenticationToken|Lifetime validation failed|expired|Connect-MgGraph|authentication|Unauthorized|conditional access|Forbidden|Authorization_RequestDenied') {
        $code = 'AuthenticationError'
    }
    Write-Payload @{ error = @{ code = $code; message = $message; action = $Action } }
    exit 1
}
