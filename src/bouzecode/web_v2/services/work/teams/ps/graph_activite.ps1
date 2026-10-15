# Read-only Graph access to the HUMAN's own recent activity: Outlook mail and Teams chats.
# Shares ps/proxy.ps1 and ps/graph_auth.ps1 with graph_bureau.ps1. READ-ONLY scopes, no
# send/subscribe action: this is the only Teams path left (the agent's `Teams` tool). ASCII only, saved WITH a BOM (PowerShell 5.1 reads a BOM-less .ps1 as
# ANSI and breaks on the first non-ASCII byte).
# Every action prints ONE compact JSON object on stdout. On failure: exit code 1 plus a JSON
# error object, whose `code` is what the Python side turns into TeamsAuthError.
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('mail', 'chats', 'messages', 'canaux', 'equipes', 'equipes_ids', 'agenda')]
    [string]$Action,
    # ISO 8601 UTC lower bound, e.g. 2026-08-10T00:00:00Z. Required: this script never
    # decides the window itself, the caller owns it.
    [string]$Since,
    [int]$Top = 50,
    [int]$Messages = 20,
    # Action 'messages' only: the chat whose messages are read on demand.
    [string]$ChatId,
    # Actions 'messages' AND 'mail': THE single message/mail whose FULL body is wanted.
    # The listings only ever carry a preview (Graph bodyPreview, ~250 chars), which is a
    # deliberate token budget -- this id is the way back to the whole text.
    [string]$MessageId,
    # Action 'canaux' only: read ONE team instead of enumerating /me/joinedTeams.
    # The caller (ms_activite.rapport_canaux) decomposes the global call into one
    # call per team, run in PARALLEL: each process has its own timeout, so a slow
    # team no longer kills the whole answer. $TeamName spares a /teams/{id} round
    # trip when the caller already knows the display name.
    [string]$TeamId,
    [string]$TeamName,
    # Action 'agenda' only: ISO 8601 UTC UPPER bound of the calendar view. The window is
    # [Since, Until] and both bounds are decided by the caller (ms_agenda.py).
    [string]$Until
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

# Every Graph GET goes through here so a hang names the request that expired.
function Invoke-BureauGet([string]$Uri) {
    Write-BureauEtape "GET $Uri"
    return Invoke-MgGraphRequest -Method GET -Uri $Uri
}

function Require-Param($Value, $Name) {
    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "Missing required parameter -$Name for action '$Action'."
    }
}

# Graph rejects raw spaces in $filter on some gateways: encode them, nothing else.
function Encode-Query([string]$Text) {
    return $Text.Replace(' ', '%20')
}

function Get-Text($Value) {
    if ($null -eq $Value) { return '' }
    return [string]$Value
}

# Sender display name, whatever shape Graph used (mail vs chatMessage differ).
function Get-Sender($Item) {
    try {
        if ($Item.from -and $Item.from.emailAddress) {
            $name = Get-Text $Item.from.emailAddress.name
            if ($name) { return $name }
            return Get-Text $Item.from.emailAddress.address
        }
        if ($Item.from -and $Item.from.user) {
            return Get-Text $Item.from.user.displayName
        }
    }
    catch { }
    return ''
}

try {
    #  A single item asked for BY ID makes the window meaningless: the caller already
    #  knows it exists. Requiring $Since there would force the python side to invent a
    #  fake bound just to be allowed to read one mail.
    if (-not $MessageId) { Require-Param $Since 'Since' }

    switch ($Action) {

        # Amorce de la decomposition : UNE seule requete, aucun message lu. L'action
        # 'equipes' existante liste aussi TOUS les canaux (N+1 requetes) : trop lourde
        # pour simplement savoir quelles equipes paralleliser.
        'equipes_ids' {
            Connect-BureauGraph -Scopes 'Team.ReadBasic.All'
            $trouvees = @()
            $suivant = "$GraphRoot/me/joinedTeams"
            while ($suivant) {
                $page = Invoke-BureauGet $suivant
                foreach ($equipe in @($page.value)) {
                    $identifiant = Get-Text $equipe.id
                    if (-not $identifiant) { continue }
                    $trouvees += @{ id = $identifiant; equipe = Get-Text $equipe.displayName }
                }
                $suivant = [string]$page.'@odata.nextLink'
            }
            Write-Payload @{ value = $trouvees; has_more = $false }
        }

        'canaux' {
            # Un canal d'equipe n'est PAS un chat : /me/chats ne le voit pas, donc une
            # demande postee dans un canal etait structurellement invisible (constat du
            # 2026-09-13). Chemin : /me/joinedTeams -> /teams/{id}/channels ->
            # /teams/{tid}/channels/{cid}/messages, filtre localement sur la fenetre
            # (Graph ne filtre pas les messages de canal cote serveur).
            # LISTER ses equipes/canaux ne demande que Team.ReadBasic.All +
            # Channel.ReadBasic.All (consentement UTILISATEUR). Seule la lecture des
            # MESSAGES exige ChannelMessage.Read.All (consentement ADMIN). On tente donc
            # le scope lourd, et s'il est refuse on retombe sur les scopes legers : la
            # LISTE des canaux reste rendue. Avant, c'etait tout ou rien et l'humain
            # n'obtenait meme pas la liste de ses propres canaux (constat du 2026-09-13).
            $messagesOK = $true
            try {
                Connect-BureauGraph -Scopes 'ChannelMessage.Read.All', 'Team.ReadBasic.All', 'Channel.ReadBasic.All'
            }
            catch {
                $messagesOK = $false
                Connect-BureauGraph -Scopes 'Team.ReadBasic.All', 'Channel.ReadBasic.All'
            }
            # Decomposition par equipe (2026-09-21) : quand l'appelant fournit -TeamId,
            # on NE fait PAS /me/joinedTeams et on ne lit QUE cette equipe. Cote Python,
            # `rapport_canaux` lance un appel par equipe EN PARALLELE, chacun dans son
            # propre process avec son propre timeout : une equipe lente ne fait plus
            # perdre toute la reponse (3 timeouts a 90s = zero canal, constat du 2026-09-21).
            $equipes = @()
            if ($TeamId) {
                $nomEquipe = $TeamName
                if (-not $nomEquipe) {
                    # L'appelant connait presque toujours le nom (il vient de 'equipes_ids') :
                    # ce repli n'existe que pour un appel manuel, et il ne doit pas lever.
                    try { $nomEquipe = Get-Text (Invoke-BureauGet "$GraphRoot/teams/$TeamId").displayName }
                    catch { $nomEquipe = $TeamId }
                }
                $equipes += @{ id = $TeamId; displayName = $nomEquipe }
            }
            else {
                $suivant = "$GraphRoot/me/joinedTeams"
                while ($suivant) {
                    $page = Invoke-BureauGet $suivant
                    foreach ($equipe in @($page.value)) {
                        if (-not (Get-Text $equipe.id)) { continue }
                        $equipes += $equipe
                    }
                    $suivant = [string]$page.'@odata.nextLink'
                }
            }
            $canaux = @()
            $canauxRestants = $false
            foreach ($equipe in $equipes) {
                if ($canaux.Count -ge $Top) { $canauxRestants = $true; break }
                $liste = $null
                # Une seule equipe non lisible (droits, equipe archivee) ne doit pas
                # emporter toute la reponse : on la saute, on ne leve pas.
                try { $liste = Invoke-BureauGet "$GraphRoot/teams/$($equipe.id)/channels" }
                catch { continue }
                foreach ($canal in @($liste.value)) {
                    if ($canaux.Count -ge $Top) { $canauxRestants = $true; break }
                    $canalId = Get-Text $canal.id
                    if (-not $canalId) { continue }
                    $reponse = $null
                    if ($messagesOK) {
                        # Un canal dont les messages sont refuses reste LISTE : l'humain
                        # doit pouvoir aller y regarder lui-meme.
                        try { $reponse = Invoke-BureauGet "$GraphRoot/teams/$($equipe.id)/channels/$canalId/messages?`$top=$Messages" }
                        catch { $reponse = $null }
                    }
                    $recent = @()
                    foreach ($message in @($reponse.value)) {
                        $created = Get-Text $message.createdDateTime
                        if (-not $created) { continue }
                        if ([datetime]$created -lt [datetime]$Since) { continue }
                        $body = ''
                        if ($message.body) { $body = Get-Text $message.body.content }
                        $recent += @{
                            id      = Get-Text $message.id
                            created = $created
                            sender  = Get-Sender $message
                            body    = $body
                        }
                    }
                    # Un canal SANS message recent reste dans la liste : le retirer
                    # empechait de repondre "voici tes canaux" quand la fenetre est calme.
                    $canaux += @{
                        id       = "$($equipe.id)/$canalId"
                        equipe   = Get-Text $equipe.displayName
                        canal    = Get-Text $canal.displayName
                        messages = $recent
                    }
                }
            }
            Write-Payload @{ value = $canaux; has_more = $canauxRestants; messages_indisponibles = (-not $messagesOK) }
        }

        'equipes' {
            # La LISTE seule : aucun message lu, donc aucun droit admin requis. Graph
            # filtre deja /me/joinedTeams et /teams/{id}/channels sur ce dont l'humain est
            # membre (un canal prive ou partage dont il n'est pas membre n'est pas rendu),
            # donc "les canaux dans lesquels je suis" se lit sans privilege particulier.
            Connect-BureauGraph -Scopes 'Team.ReadBasic.All', 'Channel.ReadBasic.All'
            $equipes = @()
            $suivant = "$GraphRoot/me/joinedTeams"
            while ($suivant) {
                $page = Invoke-BureauGet $suivant
                foreach ($equipe in @($page.value)) {
                    if (-not (Get-Text $equipe.id)) { continue }
                    $equipes += $equipe
                }
                $suivant = [string]$page.'@odata.nextLink'
            }
            $rendus = @()
            foreach ($equipe in $equipes) {
                $canauxEquipe = @()
                $suivantCanaux = "$GraphRoot/teams/$($equipe.id)/channels"
                while ($suivantCanaux) {
                    $liste = $null
                    # Une equipe illisible (archivee, droits) ne doit pas emporter la reponse.
                    try { $liste = Invoke-BureauGet $suivantCanaux }
                    catch { break }
                    foreach ($canal in @($liste.value)) {
                        $canalId = Get-Text $canal.id
                        if (-not $canalId) { continue }
                        $canauxEquipe += @{
                            id    = "$($equipe.id)/$canalId"
                            canal = Get-Text $canal.displayName
                            type  = Get-Text $canal.membershipType
                        }
                    }
                    $suivantCanaux = [string]$liste.'@odata.nextLink'
                }
                $rendus += @{
                    id     = Get-Text $equipe.id
                    equipe = Get-Text $equipe.displayName
                    canaux = $canauxEquipe
                }
            }
            Write-Payload @{ value = $rendus }
        }

        'mail' {
            Connect-BureauGraph -Scopes 'Mail.Read'
            if ($MessageId) {
                #  ONE mail, wanted WHOLE: `body` instead of `bodyPreview`, no window
                #  filter, and /me/messages (not the inbox folder) so an archived or
                #  moved mail is still reachable by the id the listing handed out.
                $selectUn = 'id,subject,receivedDateTime,body,webLink,isRead,from'
                $uri = "$GraphRoot/me/messages/$MessageId`?`$select=$selectUn"
                $item = Invoke-BureauGet $uri
                $corps = ''
                if ($item.body) { $corps = Get-Text $item.body.content }
                Write-Payload @{ value = @(@{
                    id       = Get-Text $item.id
                    subject  = Get-Text $item.subject
                    received = Get-Text $item.receivedDateTime
                    sender   = Get-Sender $item
                    body     = $corps
                    web_link = Get-Text $item.webLink
                    is_read  = [bool]$item.isRead
                }) }
                break
            }
            $select = 'id,subject,receivedDateTime,bodyPreview,webLink,isRead,from'
            $filter = Encode-Query "receivedDateTime ge $Since"
            $uri = "$GraphRoot/me/mailFolders('inbox')/messages?`$filter=$filter&`$select=$select&`$top=$Top&`$orderby=receivedDateTime%20desc"
            $mails = @()
            $suivant = $uri
            $reste = $false
            # Graph pagine : une seule page rendait 50 mails couvrant 3 jours pour une
            # fenetre de 30 demandee (mesure du 2026-09-09). On suit @odata.nextLink
            # jusqu'a $Top, et on DIT s'il restait quelque chose derriere.
            while ($suivant) {
                $page = Invoke-BureauGet $suivant
                foreach ($item in @($page.value)) {
                    if ($mails.Count -ge $Top) { break }
                    $mails += @{
                        id       = Get-Text $item.id
                        subject  = Get-Text $item.subject
                        received = Get-Text $item.receivedDateTime
                        sender   = Get-Sender $item
                        preview  = Get-Text $item.bodyPreview
                        web_link = Get-Text $item.webLink
                        is_read  = [bool]$item.isRead
                    }
                }
                $suivant = [string]$page.'@odata.nextLink'
                if ($mails.Count -ge $Top) {
                    $reste = [bool]$suivant
                    break
                }
            }
            Write-Payload @{ value = $mails; has_more = $reste }
        }

        'agenda' {
            # READ-ONLY calendar view of the human's own agenda (Calendars.Read). calendarView
            # expands recurring meetings into occurrences, which a plain /events does not.
            # Times are asked in UTC (Prefer header) so the Python side never guesses a zone.
            Require-Param $Until 'Until'
            Connect-BureauGraph -Scopes 'Calendars.Read'
            $select = 'id,subject,start,end,location,organizer,isOnlineMeeting,onlineMeeting,webLink,isCancelled,showAs,isAllDay'
            $uri = "$GraphRoot/me/calendarView?startDateTime=$Since&endDateTime=$Until&`$select=$select&`$orderby=start/dateTime&`$top=$Top"
            $entete = @{ Prefer = 'outlook.timezone="UTC"' }
            $evenements = @()
            $suivant = $uri
            $reste = $false
            while ($suivant) {
                $page = Invoke-BureauGet $suivant -Headers $entete
                foreach ($item in @($page.value)) {
                    if ($evenements.Count -ge $Top) { break }
                    $lieu = ''
                    if ($item.location) { $lieu = Get-Text $item.location.displayName }
                    $organisateur = ''
                    if ($item.organizer -and $item.organizer.emailAddress) { $organisateur = Get-Text $item.organizer.emailAddress.name }
                    $jointure = ''
                    if ($item.onlineMeeting) { $jointure = Get-Text $item.onlineMeeting.joinUrl }
                    $evenements += @{
                        id        = Get-Text $item.id
                        subject   = Get-Text $item.subject
                        start     = (Get-Text $item.start.dateTime) + 'Z'
                        end       = (Get-Text $item.end.dateTime) + 'Z'
                        location  = $lieu
                        organizer = $organisateur
                        join_url  = $jointure
                        web_link  = Get-Text $item.webLink
                        cancelled = [bool]$item.isCancelled
                        all_day   = [bool]$item.isAllDay
                        show_as   = Get-Text $item.showAs
                    }
                }
                $suivant = [string]$page.'@odata.nextLink'
                if ($evenements.Count -ge $Top) {
                    $reste = [bool]$suivant
                    break
                }
            }
            Write-Payload @{ value = $evenements; has_more = $reste }
        }

        'chats' {
            Connect-BureauGraph -Scopes 'Chat.Read'
            # /me/chats cannot be filtered on message dates: we take the most recently
            # updated chats, then filter their messages locally on createdDateTime.
            $uri = "$GraphRoot/me/chats?`$top=$Top&`$orderby=lastMessagePreview/createdDateTime%20desc"
            $ouverts = @()
            $suivant = $uri
            $chatsRestants = $false
            while ($suivant) {
                $page = Invoke-BureauGet $suivant
                foreach ($chat in @($page.value)) {
                    if ($ouverts.Count -ge $Top) { break }
                    if (-not (Get-Text $chat.id)) { continue }
                    $ouverts += $chat
                }
                $suivant = [string]$page.'@odata.nextLink'
                if ($ouverts.Count -ge $Top) {
                    $chatsRestants = [bool]$suivant
                    break
                }
            }
            # One GET per chat used to cost ~0.43s each: 30 chats = 13s of the 14s answer
            # (measured 2026-09-09). Graph JSON batching carries 20 sub-requests per
            # round-trip, so the same 30 chats now cost 2 round-trips (~2s), and $select
            # stops Graph from shipping every unused field of every message.
            $select = 'id,createdDateTime,from,body'
            $reponses = @{}
            for ($debut = 0; $debut -lt $ouverts.Count; $debut += 20) {
                $fin = [Math]::Min($debut + 19, $ouverts.Count - 1)
                $requetes = @()
                for ($rang = $debut; $rang -le $fin; $rang++) {
                    $chatId = Get-Text $ouverts[$rang].id
                    $requetes += @{
                        id     = "$rang"
                        method = 'GET'
                        url    = "/chats/$chatId/messages?`$top=$Messages&`$select=$select"
                    }
                }
                try {
                    $corps = @{ requests = $requetes } | ConvertTo-Json -Depth 5
                    $lot = Invoke-MgGraphRequest -Method POST -Uri "$GraphRoot/`$batch" -Body $corps -ContentType 'application/json'
                    foreach ($reponse in @($lot.responses)) {
                        $reponses["$($reponse.id)"] = $reponse
                    }
                }
                catch {
                    # A whole batch can fail where single requests succeed (throttling, or a
                    # tenant that refuses /$batch): fall back to one GET per chat for THIS
                    # slice rather than dropping twenty chats from the answer.
                    for ($rang = $debut; $rang -le $fin; $rang++) {
                        $chatId = Get-Text $ouverts[$rang].id
                        try {
                            $solo = Invoke-BureauGet "$GraphRoot/chats/$chatId/messages?`$top=$Messages&`$select=$select"
                            $reponses["$rang"] = @{ status = 200; body = $solo }
                        }
                        catch {
                            # Single unreadable chat (deleted, or no permission on a meeting
                            # chat): skipped, the other chats keep their answer.
                        }
                    }
                }
            }
            $chats = @()
            for ($rang = 0; $rang -lt $ouverts.Count; $rang++) {
                $chat = $ouverts[$rang]
                $reponse = $reponses["$rang"]
                if (-not $reponse) { continue }
                # A single unreadable chat answers with its own HTTP status inside the batch:
                # it must not lose the whole answer.
                if ([int]$reponse.status -ge 300) { continue }
                $recent = @()
                foreach ($message in @($reponse.body.value)) {
                    $created = Get-Text $message.createdDateTime
                    if (-not $created) { continue }
                    if ([datetime]$created -lt [datetime]$Since) { continue }
                    $body = ''
                    if ($message.body) { $body = Get-Text $message.body.content }
                    $recent += @{
                        id      = Get-Text $message.id
                        created = $created
                        sender  = Get-Sender $message
                        body    = $body
                    }
                }
                if ($recent.Count -eq 0) { continue }
                $chats += @{
                    id       = Get-Text $chat.id
                    topic    = Get-Text $chat.topic
                    kind     = Get-Text $chat.chatType
                    messages = $recent
                }
            }
            Write-Payload @{ value = $chats; has_more = $chatsRestants }
        }
        'messages' {
            #  On demand: the listing above trims bodies and drops old messages, so the
            #  model needs a way BACK to what it was told it did not read.
            Require-Param $ChatId 'ChatId'
            Connect-BureauGraph -Scopes 'Chat.Read'
            $select = 'id,createdDateTime,from,body'
            $lus = @()
            if ($MessageId) {
                #  A precise message is wanted WHOLE: no window filter here, the caller
                #  already knows this message exists and asked for it by id.
                $uri = "$GraphRoot/chats/$ChatId/messages/$MessageId`?`$select=$select"
                $message = Invoke-BureauGet $uri
                $corps = ''
                if ($message.body) { $corps = Get-Text $message.body.content }
                $lus += @{
                    id      = Get-Text $message.id
                    created = Get-Text $message.createdDateTime
                    sender  = Get-Sender $message
                    body    = $corps
                }
            }
            else {
                $uri = "$GraphRoot/chats/$ChatId/messages?`$top=$Messages&`$select=$select"
                $page = Invoke-BureauGet $uri
                foreach ($message in @($page.value)) {
                    $created = Get-Text $message.createdDateTime
                    if (-not $created) { continue }
                    if ([datetime]$created -lt [datetime]$Since) { continue }
                    $corps = ''
                    if ($message.body) { $corps = Get-Text $message.body.content }
                    $lus += @{
                        id      = Get-Text $message.id
                        created = $created
                        sender  = Get-Sender $message
                        body    = $corps
                    }
                }
            }
            Write-Payload @{ value = $lus }
        }
    }
}
catch {
    $message = $_.Exception.Message
    $code = 'PowerShellFailure'
    if ($message -match 'AADSTS|InvalidAuthenticationToken|Lifetime validation failed|expired|Connect-MgGraph|authentication|Unauthorized|conditional access|Forbidden|Authorization_RequestDenied') {
        $code = 'AuthenticationError'
    }
    Write-Payload @{ error = @{ code = $code; message = $message; action = $Action } }
    exit 1
}
