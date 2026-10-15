#!/usr/bin/env bash
# ============================================================
# bouzeui.sh - one-shot launcher for bouzeui (Flask web UI for bouzecode)
# Ensures uv is available, keeps .venv in sync, then launches the app.
# Usage: ./bouzeui.sh [port]   (default port 5056)
# `-v2` is still accepted but has no effect: the old `bouzecode.web` UI was
# removed, only web_v2 remains.
# ============================================================
set -euo pipefail

if [ -t 1 ]; then C_CYAN=$'\033[36m'; C_GREEN=$'\033[32m'; C_GRAY=$'\033[90m'; C_YELLOW=$'\033[33m'; C_RESET=$'\033[0m'
else C_CYAN=""; C_GREEN=""; C_GRAY=""; C_YELLOW=""; C_RESET=""; fi

RepoDir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VenvDir="$RepoDir/.venv"
PythonExe="$VenvDir/bin/python"
PyProject="$RepoDir/pyproject.toml"
Stamp="$VenvDir/.bouzeui_installed"

UseV2=0; PortArg=""
for arg in "$@"; do
    if [ "$arg" = "-v2" ]; then UseV2=1
    elif [[ "$arg" =~ ^[0-9]+$ ]]; then PortArg="$arg"; fi
done
if [ "$UseV2" -eq 1 ]; then BouzeuiModule="bouzecode.web_v2"; else BouzeuiModule="bouzecode.web.app"; fi

# --- 1. Locate uv ------------------------------------------------------------
UvExe=""
if command -v uv >/dev/null 2>&1; then UvExe="$(command -v uv)"
else
    for p in "$(dirname "$RepoDir")/uv" "$RepoDir/uv" "$HOME/.local/bin/uv" "/opt/homebrew/bin/uv" "/usr/local/bin/uv"; do
        [ -x "$p" ] && { UvExe="$p"; break; }
    done
fi
[ -z "$UvExe" ] && { echo "uv not found. Install from https://astral.sh/uv or place a 'uv' binary next to demo/." >&2; exit 1; }
printf '%s[bouzeui] uv: %s%s\n' "$C_CYAN" "$UvExe" "$C_RESET"

# --- 2. Ensure venv ----------------------------------------------------------
if [ ! -x "$PythonExe" ]; then
    printf '%s[bouzeui] creating venv...%s\n' "$C_CYAN" "$C_RESET"
    ( cd "$RepoDir" && "$UvExe" venv --python 3.13 "$VenvDir" )
fi

# --- 3. Install / update deps if pyproject changed --------------------------
needInstall=1
if [ -f "$Stamp" ] && [ ! "$PyProject" -nt "$Stamp" ]; then needInstall=0; fi
if [ "$needInstall" -eq 1 ]; then
    printf '%s[bouzeui] syncing deps (editable install)...%s\n' "$C_CYAN" "$C_RESET"
    if ( cd "$RepoDir" && "$UvExe" pip install --python "$PythonExe" -e "." ); then
        touch "$Stamp"
    else
        printf '%s[bouzeui] install failed (exe locked by an agent?) - fallback PYTHONPATH=src%s\n' "$C_YELLOW" "$C_RESET"
    fi
fi
export PYTHONPATH="$RepoDir/src"

# --- 4. Load .env ------------------------------------------------------------
# Prefer the repo .env; fall back to a sibling demo_application/.env if present.
EnvFile="$RepoDir/.env"
[ -f "$EnvFile" ] || EnvFile="$(dirname "$RepoDir")/demo_application/.env"
if [ -f "$EnvFile" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line#"${line%%[![:space:]]*}"}"
        [ -z "$line" ] && continue; [ "${line:0:1}" = "#" ] && continue; [[ "$line" != *"="* ]] && continue
        key="${line%%=*}"; val="${line#*=}"; val="${val%\"}"; val="${val#\"}"
        export "$key=$val"
    done < "$EnvFile"
    printf '%s[bouzeui] loaded .env (%s)%s\n' "$C_GRAY" "$EnvFile" "$C_RESET"
fi

# --- 5. network env (proxy + API) -----------------------------------------------
# Proxy and API endpoints come from your shell or .env (HTTP_PROXY, HTTPS_PROXY,
# NO_PROXY, ANTHROPIC_BASE_URL); nothing is hard-coded here.
export NO_PROXY="${NO_PROXY:-localhost,127.0.0.1}"
# TLS verification stays ON. For a corporate proxy CA, set SSL_CERT_FILE /
# REQUESTS_CA_BUNDLE, or BOUZECODE_CA_BUNDLE (in .env), copied here.
# Dev machines only: BOUZECODE_TLS_INSECURE=1 (logged).
if [ -n "${BOUZECODE_CA_BUNDLE:-}" ] && [ -f "$BOUZECODE_CA_BUNDLE" ]; then
    export REQUESTS_CA_BUNDLE="${REQUESTS_CA_BUNDLE:-$BOUZECODE_CA_BUNDLE}"
    export SSL_CERT_FILE="${SSL_CERT_FILE:-$BOUZECODE_CA_BUNDLE}"
fi
export PYTHONIOENCODING="utf-8"
if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -n "${ANTHROPIC_AUTH_TOKEN:-}" ]; then
    export ANTHROPIC_API_KEY="$ANTHROPIC_AUTH_TOKEN"
fi

# --- 5b. Chrome DevTools MCP (browser automation for the frontend agent) -----
# Poses the env var the chrome_devtools launcher reads at tool registration.
# Enables the mcp__chrome-devtools__* tools for agents spawned from the web UI
# (the CLI flag --enable-chrome-devtools does the same for `bouzecode`).
export BOUZECODE_ENABLE_CHROME_DEVTOOLS="1"

# --- 6. Launch ---------------------------------------------------------------
if [ -n "$PortArg" ]; then port="$PortArg"; else port="5056"; fi
echo
if [ "$UseV2" -eq 1 ]; then printf '%s=== bouzeui v2 ===%s\n' "$C_GREEN" "$C_RESET"; else printf '%s=== bouzeui ===%s\n' "$C_GREEN" "$C_RESET"; fi
echo "Repo: $RepoDir"
echo "URL : http://127.0.0.1:$port"
echo
cd "$RepoDir"
exec "$PythonExe" -m "$BouzeuiModule" --port "$port"
