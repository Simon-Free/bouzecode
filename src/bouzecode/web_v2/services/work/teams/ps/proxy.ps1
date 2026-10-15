# Fait TRAVERSER le proxy d'entreprise aux appels Graph, quand l'environnement en declare un.
#
# MESURE du 2026-08-26 15:5x sur le poste de production (PS 5.1.26100.8875), a citer avant de
# toucher a ce fichier :
#   - `HTTPS_PROXY` / `HTTP_PROXY` y valent `http://proxy.example.com:8080`,
#     `NO_PROXY` vaut `localhost,127.0.0.1,.example.com` ;
#   - `https://graph.microsoft.com/v1.0/me` repond 405 sans proxy explicite, 405 avec `-Proxy`,
#     405 via `DefaultWebProxy`, et 200 par le HttpClient .NET (le vrai chemin
#     d'`Invoke-MgGraphRequest`) : la sortie fonctionne DEJA sans reglage ;
#   - la lecture Graph (alors `ps/read_messages.ps1`, retire depuis) rendait exit 0 sans
#     aucune configuration proxy.
# Donc : RIEN n'est ecrit en dur ici, et l'absence de variable d'environnement est un NO-OP.
# Ce fichier ne fait qu'une chose : si l'environnement declare un proxy, le rendre visible au
# HttpClient de Microsoft.Graph.Authentication, que PowerShell 5.1 n'alimente pas seul.
#
# ATTENTION -- ne pas confondre avec `flow_transport.py`, qui doit CONTOURNER le proxy
# (`build_opener(ProxyHandler({}))`) parce qu'il parle a une URL Power Automate joignable en direct.
# Graph, lui, doit le TRAVERSER. Les deux reglages sont opposes : ne recopiez pas l'un chez l'autre.

function Get-BureauProxyUrl {
    foreach ($nom in @('HTTPS_PROXY', 'https_proxy', 'HTTP_PROXY', 'http_proxy')) {
        $valeur = [System.Environment]::GetEnvironmentVariable($nom)
        if ($valeur) { return $valeur.Trim() }
    }
    return $null
}

function Get-BureauProxyBypass {
    foreach ($nom in @('NO_PROXY', 'no_proxy')) {
        $valeur = [System.Environment]::GetEnvironmentVariable($nom)
        if ($valeur) {
            # `NO_PROXY` est une liste d'hotes ; `WebProxy` attend des EXPRESSIONS REGULIERES.
            # `.example.com` doit donc devenir `.*\.example\.com$`, sinon le contournement ne prend pas.
            $motifs = @()
            foreach ($hote in $valeur.Split(',')) {
                $h = $hote.Trim()
                if (-not $h) { continue }
                $echappe = [regex]::Escape($h.TrimStart('.'))
                if ($h.StartsWith('.')) { $motifs += ('.*\.' + $echappe + '$') }
                else { $motifs += ('^' + $echappe + '$') }
            }
            return $motifs
        }
    }
    return @()
}

function Set-BureauProxy {
    # Jamais d'exception : un reglage de proxy rate ne doit pas empecher un appel qui
    # passerait sans lui. On le DIT sur la sortie d'erreur et on continue.
    try {
        $url = Get-BureauProxyUrl
        if (-not $url) { return }
        $bypass = Get-BureauProxyBypass
        $proxy = New-Object System.Net.WebProxy($url, $true, $bypass)
        $proxy.Credentials = [System.Net.CredentialCache]::DefaultCredentials
        [System.Net.WebRequest]::DefaultWebProxy = $proxy
        [System.Net.HttpWebRequest]::DefaultWebProxy = $proxy
    }
    catch {
        [Console]::Error.WriteLine("PROXY_IGNORE: $($_.Exception.Message)")
    }
}
