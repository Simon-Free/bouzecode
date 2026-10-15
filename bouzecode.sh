#!/usr/bin/env bash
# ============================================================
# bouzecode.sh - dispatcher + launcher for bouzecode CLI (macOS / Linux)
# Sub-commands: publish, update, gui
# Usage: ./bouzecode.sh [sub-command] [args...]
#        ./bouzecode.sh              -> launch REPL
#        ./bouzecode.sh publish      -> run scripts/publish.sh
#        ./bouzecode.sh update       -> run scripts/self_update.sh
#        ./bouzecode.sh gui          -> run scripts/bouzeui.sh
# ============================================================

set -euo pipefail

# --- Colors (fall back to no-op if not a tty) --------------------------------
if [ -t 1 ]; then
    C_YELLOW=$'\033[33m'; C_GREEN=$'\033[32m'; C_CYAN=$'\033[36m'
    C_RED=$'\033[31m'; C_GRAY=$'\033[90m'; C_RESET=$'\033[0m'
else
    C_YELLOW=""; C_GREEN=""; C_CYAN=""; C_RED=""; C_GRAY=""; C_RESET=""
fi
say()  { printf '%s%s%s\n' "$1" "$2" "$C_RESET"; }

# --- Resolve repo dir (dir of this script, following symlinks) ---------------
SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
    DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
RepoDir="$(cd -P "$(dirname "$SOURCE")" && pwd)"

# --- Dispatcher: check first arg for known sub-commands ----------------------
# (case statement, not an associative array, so it works on macOS bash 3.2)
if [ "$#" -gt 0 ]; then
    scriptName=""
    case "$1" in
        publish) scriptName="publish.sh" ;;
        update)  scriptName="self_update.sh" ;;
        gui)     scriptName="bouzeui.sh" ;;
    esac
    if [ -n "$scriptName" ]; then
        scriptPath="$RepoDir/scripts/$scriptName"
        if [ ! -f "$scriptPath" ]; then
            say "$C_RED" "Script not found: $scriptPath"
            exit 1
        fi
        shift
        exec bash "$scriptPath" "$@"
    fi
fi

# --- Normal launcher flow (no sub-command matched) ---------------------------

VenvDir="$RepoDir/.venv"
PythonExe="$VenvDir/bin/python"
BouzecodeExe="$VenvDir/bin/bouzecode"
PyProject="$RepoDir/pyproject.toml"
Stamp="$VenvDir/.bouzecode_installed"

# Persisted credentials/env (macOS has no registry-style User env vars).
ConfigDir="${XDG_CONFIG_HOME:-$HOME/.config}/bouzecode"
CredFile="$ConfigDir/env"
mkdir -p "$ConfigDir"
if [ -f "$CredFile" ]; then
    # shellcheck disable=SC1090
    set -a; source "$CredFile"; set +a
fi

# Persist a KEY=VALUE into $CredFile (replacing any prior line for KEY).
persist_var() {
    local key="$1" val="$2"
    touch "$CredFile"; chmod 600 "$CredFile"
    local tmp; tmp="$(mktemp)"
    grep -v "^${key}=" "$CredFile" > "$tmp" 2>/dev/null || true
    printf '%s=%s\n' "$key" "$val" >> "$tmp"
    mv "$tmp" "$CredFile"
}

# --- 0. Proxy credentials helper ---------------------------------------------
# Returns the proxy URL on stdout.
# Optional: only used when BOUZECODE_PROXY_HOST (host:port) is set; otherwise
# the HTTPS_PROXY already present in your environment (possibly empty) is kept.
ensure_proxy_credentials() {
    if [ -z "${BOUZECODE_PROXY_HOST:-}" ]; then
        printf '%s' "${HTTPS_PROXY:-}"
        return
    fi
    if [ -z "${CP:-}" ]; then
        say "$C_YELLOW" "[bouzecode] Proxy credentials not found." >&2
        printf '  Proxy user: ' >&2
        read -r CP
        export CP
        persist_var CP "$CP"
        say "$C_GREEN" "  User saved to $CredFile." >&2
    fi
    if [ -z "${PW:-}" ]; then
        printf '  Proxy password: ' >&2
        read -rs PW; echo >&2
        export PW
        persist_var PW "$PW"
        say "$C_GREEN" "  Password saved to $CredFile." >&2
    fi
    printf 'http://%s:%s@%s' "$CP" "$PW" "$BOUZECODE_PROXY_HOST"
}

# --- 1. Locate uv ------------------------------------------------------------
find_uv() {
    if command -v uv >/dev/null 2>&1; then command -v uv; return; fi
    local parent; parent="$(dirname "$RepoDir")"
    local candidates=(
        "$RepoDir/uv"
        "$parent/uv"
        "$HOME/.local/bin/uv"
        "/opt/homebrew/bin/uv"
        "/usr/local/bin/uv"
    )
    for p in "${candidates[@]}"; do
        [ -x "$p" ] && { echo "$p"; return; }
    done
    return 1
}

UvExe="$(find_uv || true)"
if [ -z "$UvExe" ]; then
    say "$C_YELLOW" "[bouzecode] uv not found - installing automatically..."
    proxyUrl="$(ensure_proxy_credentials)"
    export HTTP_PROXY="$proxyUrl" HTTPS_PROXY="$proxyUrl"
    curl -LsSf https://astral.sh/uv/install.sh | sh || \
        say "$C_RED" "[bouzecode] Auto-install via astral.sh failed."
    # uv installer adds to ~/.local/bin
    [ -d "$HOME/.local/bin" ] && export PATH="$HOME/.local/bin:$PATH"
    UvExe="$(find_uv || true)"
    if [ -z "$UvExe" ]; then
        say "$C_RED" "uv still not found after install attempt. Install manually from https://astral.sh/uv or place a 'uv' binary next to the repo."
        exit 1
    fi
    say "$C_GREEN" "[bouzecode] uv installed at $UvExe"
fi
say "$C_CYAN" "[bouzecode] uv: $UvExe"

# --- 2. Load .env (proxy, credentials) -- BEFORE any network ops -------------
EnvFile="$RepoDir/.env"
if [ -f "$EnvFile" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line#"${line%%[![:space:]]*}"}"   # ltrim
        [ -z "$line" ] && continue
        [ "${line:0:1}" = "#" ] && continue
        [[ "$line" != *"="* ]] && continue
        key="${line%%=*}"
        val="${line#*=}"
        val="${val%\"}"; val="${val#\"}"           # strip surrounding quotes
        export "$key=$val"
    done < "$EnvFile"
    say "$C_GRAY" "[bouzecode] loaded .env"
fi

# --- 3. corporate env (proxy + API key) -- BEFORE any network ops -----------------
proxyUrl="$(ensure_proxy_credentials)"
if [ -n "$proxyUrl" ]; then
    export HTTP_PROXY="$proxyUrl"
    export HTTPS_PROXY="$proxyUrl"
fi
export NO_PROXY="${NO_PROXY:-localhost,127.0.0.1}"
# TLS verification stays ON. For a corporate proxy CA, set SSL_CERT_FILE /
# REQUESTS_CA_BUNDLE, or BOUZECODE_CA_BUNDLE (in .env), copied here.
# Dev machines only: BOUZECODE_TLS_INSECURE=1 (logged).
if [ -n "${BOUZECODE_CA_BUNDLE:-}" ] && [ -f "$BOUZECODE_CA_BUNDLE" ]; then
    export REQUESTS_CA_BUNDLE="${REQUESTS_CA_BUNDLE:-$BOUZECODE_CA_BUNDLE}"
    export SSL_CERT_FILE="${SSL_CERT_FILE:-$BOUZECODE_CA_BUNDLE}"
fi
export PYTHONIOENCODING="utf-8"

# --- 4. Ensure venv ----------------------------------------------------------
if [ ! -x "$PythonExe" ]; then
    say "$C_CYAN" "[bouzecode] creating venv..."
    ( cd "$RepoDir" && "$UvExe" venv --python 3.13 "$VenvDir" )
fi

# --- 5. Install / update deps if pyproject changed ---------------------------
needInstall=1
if [ -f "$Stamp" ] && [ -x "$BouzecodeExe" ]; then
    # -nt: pyproject newer than stamp -> reinstall
    if [ ! "$PyProject" -nt "$Stamp" ]; then
        needInstall=0
    fi
fi

if [ "$needInstall" -eq 1 ]; then
    say "$C_CYAN" "[bouzecode] syncing deps (editable install)..."
    installExit=0
    installOutput="$( cd "$RepoDir" && "$UvExe" pip install --python "$PythonExe" -e . 2>&1 )" || installExit=$?
    printf '%s\n' "$installOutput"

    if [ "$installExit" -ne 0 ]; then
        if printf '%s' "$installOutput" | grep -qiE 'os error 32|being used by another process|utilis. par un autre processus'; then
            echo
            say "$C_YELLOW" "[bouzecode] L'executable bouzecode est verrouille (une instance tourne deja)."
            say "$C_YELLOW" "[bouzecode] Fermez l'instance en cours puis relancez la commande."
            echo
            exit 0
        else
            say "$C_RED" "[bouzecode] echec de l'installation des deps (exit $installExit)."
            exit 1
        fi
    else
        touch "$Stamp"
    fi
fi

# --- 6. Ensure ripgrep is available ------------------------------------------
if ! command -v rg >/dev/null 2>&1; then
    say "$C_YELLOW" "[bouzecode] ripgrep (rg) not found, installing via brew..."
    if command -v brew >/dev/null 2>&1; then
        brew install ripgrep >/dev/null 2>&1 || true
    fi
    if command -v rg >/dev/null 2>&1; then
        say "$C_GREEN" "[bouzecode] ripgrep installed."
    else
        say "$C_YELLOW" "[bouzecode] ripgrep install failed. Grep will use fallback (slower)."
        say "$C_YELLOW" "  Install manually: brew install ripgrep"
    fi
fi

# --- 7. API key check --------------------------------------------------------
# Map ANTHROPIC_AUTH_TOKEN -> ANTHROPIC_API_KEY if not already set
if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -n "${ANTHROPIC_AUTH_TOKEN:-}" ]; then
    export ANTHROPIC_API_KEY="$ANTHROPIC_AUTH_TOKEN"
fi

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    echo
    say "$C_YELLOW" "[bouzecode] ANTHROPIC_API_KEY not found."
    echo
    printf '  Paste your Anthropic API key (sk-ant-...): '
    read -r key
    key="$(printf '%s' "$key" | tr -d '[:space:]')"
    if [ -z "$key" ]; then
        say "$C_RED" "  No key provided. Exiting."
        exit 1
    fi
    export ANTHROPIC_API_KEY="$key"
    persist_var ANTHROPIC_API_KEY "$key"
    say "$C_GREEN" "  Key saved to $CredFile."
    say "$C_GRAY" "  (It will persist across sessions -- no need to re-enter next time.)"
    echo
fi

# --- 8. Launch ----------------------------------------------------------------
echo
say "$C_GREEN" "=== bouzecode ==="
echo "Repo:  $RepoDir"
echo

exec "$BouzecodeExe" "$@"
