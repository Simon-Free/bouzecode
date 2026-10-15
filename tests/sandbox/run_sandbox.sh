#!/usr/bin/env bash
# ============================================================================
# Bac à sable bouzeui v2 : web_v2 + FAUX LLM, dans un HOME jetable.
#
#   tests/sandbox/run_sandbox.sh start [--seed] [--fresh]   démarre (idempotent)
#   tests/sandbox/run_sandbox.sh stop                       arrête tout
#   tests/sandbox/run_sandbox.sh status                     état + URLs
#   tests/sandbox/run_sandbox.sh seed                       (re)peuple les données
#   tests/sandbox/run_sandbox.sh start --snapshot [--test]  HOME seedé restauré (instantané)
#   tests/sandbox/run_sandbox.sh start --reseed [--test]    force seed complet + instantané
#   --test (ou BZ_E2E=1) : faux LLM sans latence (sauf [scn:slow]/[scn:hang])
#
# Variables : BZ_SANDBOX_HOME (/tmp/bz-sandbox), BZ_UI_PORT (5056), MOCK_LLM_PORT (5099),
#             MOCK_LLM_LATENCY (0.8 s avant le 1er token).
#
# GARANTIES
#  - Le serveur démarre sous `env -i` : AUCUNE variable du shell appelant n'est héritée
#    (ni ANTHROPIC_AUTH_TOKEN, ni OPENROUTER_KEY, ni PREPROD_ENDPOINT, ni proxy corporate).
#    Les agents héritent de l'env du serveur → ils ne connaissent que le faux LLM.
#  - Le dépôt n'a PAS de `.env` (retiré) : `ui/cli.py::_load_repo_dotenv` ne charge rien.
#    Le script REFUSE de démarrer si un `.env` réapparaît à la racine du dépôt.
#  - Python = `.venv/bin/python` directement, JAMAIS `uv run`/`uv sync` : `uv.lock` et
#    `[tool.uv.index]` pointent sur l'Artifactory corporate, injoignable ici.
# ============================================================================
set -euo pipefail

REPO="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="$REPO/.venv/bin/python"
SB="${BZ_SANDBOX_HOME:-/tmp/bz-sandbox}"
# N'importe quel port : `backend/multi_agent/tools.py` lit BOUZECODE_WEB_BASE_URL (posé par
# `web_v2 --port`) pour les outils Agent / MessageAgent (vérifié : sous-agents lancés sur 5556).
UI_PORT="${BZ_UI_PORT:-5056}"
LLM_PORT="${MOCK_LLM_PORT:-5099}"
# Mode TEST (`start --test` ou BZ_E2E=1) : faux LLM sans latence ni délai entre fragments,
# sauf si l'appelant les fixe explicitement. [scn:slow] et [scn:hang] gardent leurs PROPRES
# délais (delay=SLOW_DELAY / latency=45 portés par le scénario) : ce sont eux qui servent à
# tester le streaming et les phases d'attente. Le mode manuel (démo) garde 0,8 s / 0,02 s.
TEST_MODE="${BZ_E2E:-0}"
for _a in "$@"; do [ "$_a" = "--test" ] && TEST_MODE=1; done
if [ "$TEST_MODE" = 1 ]; then
    : "${MOCK_LLM_LATENCY:=0}"
    : "${MOCK_LLM_CHUNK_DELAY:=0}"
fi
LATENCY="${MOCK_LLM_LATENCY:-0.8}"
RUN="$SB/.run"
LOCAL_BIN="$HOME/.local/bin"
# Chromium de Playwright installé dans le VRAI home : visible des agents malgré HOME isolé.
PW_BROWSERS="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}"
[ -d "$PW_BROWSERS" ] || PW_BROWSERS=""

log() { printf '[sandbox] %s\n' "$*"; }

# Environnement MINIMAL et explicite, partagé par le mock, le serveur et le seed.
SBENV=(env -i
    HOME="$SB" USER="${USER:-sandbox}" LANG=C.UTF-8 LC_ALL=C.UTF-8 TERM=dumb
    PATH="$LOCAL_BIN:$REPO/.venv/bin:/usr/local/bin:/usr/bin:/bin"
    PYTHONPATH="$REPO/src"
    ANTHROPIC_BASE_URL="http://127.0.0.1:$LLM_PORT"
    ANTHROPIC_API_KEY="sk-mock-sandbox"
    NO_PROXY="127.0.0.1,localhost" no_proxy="127.0.0.1,localhost"
    BOUZECODE_SANDBOX=1
    ${PW_BROWSERS:+PLAYWRIGHT_BROWSERS_PATH="$PW_BROWSERS"}
    MOCK_LLM_PORT="$LLM_PORT" MOCK_LLM_LATENCY="$LATENCY"
    ${MOCK_LLM_CHUNK_DELAY:+MOCK_LLM_CHUNK_DELAY="$MOCK_LLM_CHUNK_DELAY"}
    ${MOCK_LLM_SLOW_DELAY:+MOCK_LLM_SLOW_DELAY="$MOCK_LLM_SLOW_DELAY"}
    MOCK_LLM_USAGE_SEMANTICS="${MOCK_LLM_USAGE_SEMANTICS:-gateway}"
    BOUZECODE_USAGE_INPUT_INCLUDES_CACHE_WRITE="$([ "${MOCK_LLM_USAGE_SEMANTICS:-gateway}" = anthropic ] && echo 0 || echo 1)"
    GIT_AUTHOR_NAME=sandbox GIT_AUTHOR_EMAIL=sandbox@localhost
    GIT_COMMITTER_NAME=sandbox GIT_COMMITTER_EMAIL=sandbox@localhost)

alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }

wait_http() {  # url, secondes
    local url="$1" n="${2:-30}"
    for _ in $(seq 1 $((n * 5))); do
        curl -s -o /dev/null --max-time 1 "$url" && return 0
        sleep 0.2
    done
    return 1
}

kill_tree() {  # pidfile
    local f="$1"
    alive "$f" || { rm -f "$f"; return 0; }
    local pid; pid="$(cat "$f")"
    pkill -TERM -P "$pid" 2>/dev/null || true
    kill -TERM "$pid" 2>/dev/null || true
    for _ in $(seq 1 25); do kill -0 "$pid" 2>/dev/null || break; sleep 0.2; done
    kill -KILL "$pid" 2>/dev/null || true
    rm -f "$f"
}

kill_agents() {
    # Agents spawnés par le serveur : leur ligne de commande contient notre HOME sandbox
    # (--session-file $SB/…). On ne tue QUE ceux-là.
    local pids
    pids="$(pgrep -f -- "--session-file $SB/" || true)"
    [ -n "$pids" ] && { log "arrêt de $(echo "$pids" | wc -w) agent(s)"; kill -TERM $pids 2>/dev/null || true; }
    return 0
}

preflight() {
    [ -x "$PY" ] || { echo "venv absent : $PY" >&2; exit 1; }
    if [ -e "$REPO/.env" ]; then
        echo "REFUS : $REPO/.env existe — il contient de vrais secrets et serait chargé par les agents." >&2
        exit 1
    fi
    command -v git >/dev/null || PATH="$LOCAL_BIN:$PATH"
    if ! "$LOCAL_BIN/git" --version >/dev/null 2>&1 && ! command -v git >/dev/null; then
        echo "git introuvable (ni dans le PATH ni dans $LOCAL_BIN)" >&2; exit 1
    fi
    for port in "$UI_PORT" "$LLM_PORT"; do
        if curl -s -o /dev/null --max-time 1 "http://127.0.0.1:$port/" && ! alive "$RUN/ui.pid" && ! alive "$RUN/llm.pid"; then
            echo "port $port déjà pris par un autre process" >&2; exit 1
        fi
    done
}

cmd_start() {
    local seed=0 fresh=0 snapshot=0 reseed=0
    for a in "$@"; do
        case "$a" in
            --seed) seed=1 ;; --fresh) fresh=1 ;;
            --snapshot) snapshot=1 ;; --reseed) snapshot=1; reseed=1 ;;
        esac
    done
    if [ "$snapshot" = 1 ]; then cmd_snapshot "$reseed"; return; fi
    if [ "$fresh" = 1 ]; then cmd_stop; rm -rf "$SB"; fi
    preflight
    mkdir -p "$SB" "$RUN" "$SB/.bouzecode"
    # Modèle par défaut du code = gateway préprod : la garde d'environnement refuserait tout
    # lancement. Le bac à sable fixe un modèle `anthropic`, servi par le faux LLM.
    [ -f "$SB/.bouzecode/config.json" ] || \
        printf '{"model": "%s"}\n' "${BZ_SANDBOX_MODEL:-claude-opus-5}" >"$SB/.bouzecode/config.json"

    if alive "$RUN/llm.pid"; then log "faux LLM déjà lancé (pid $(cat "$RUN/llm.pid"))"
    else
        "${SBENV[@]}" "$PY" "$REPO/tests/sandbox/mock_llm_server.py" >"$RUN/mock_llm.log" 2>&1 </dev/null &
        echo $! >"$RUN/llm.pid"
        wait_http "http://127.0.0.1:$LLM_PORT/health" 20 || { echo "faux LLM KO, voir $RUN/mock_llm.log" >&2; exit 1; }
        log "faux LLM   : http://127.0.0.1:$LLM_PORT  (pid $(cat "$RUN/llm.pid"))"
    fi

    if [ "$seed" = 1 ] && [ ! -f "$SB/.seeded" ]; then
        cmd_seed_offline
    fi

    if alive "$RUN/ui.pid"; then log "bouzeui déjà lancé (pid $(cat "$RUN/ui.pid"))"
    else
        # `exec` : la sous-shell DEVIENT le serveur (même pid) et ne garde pas le stdout de
        # l'appelant ouvert — sans lui, `run_sandbox.sh start | tail` ne rendait jamais la main.
        ( cd "$SB" && exec "${SBENV[@]}" "$PY" -m bouzecode.web_v2 --port "$UI_PORT" ) >"$RUN/web.log" 2>&1 </dev/null &
        echo $! >"$RUN/ui.pid"
        wait_http "http://127.0.0.1:$UI_PORT/api/version" 60 || { echo "bouzeui KO, voir $RUN/web.log" >&2; exit 1; }
        log "bouzeui   : http://127.0.0.1:$UI_PORT  (pid $(cat "$RUN/ui.pid"))"
    fi

    if [ "$seed" = 1 ] && [ ! -f "$SB/.seeded_live" ]; then
        "${SBENV[@]}" BZ_UI="http://127.0.0.1:$UI_PORT" "$PY" "$REPO/tests/sandbox/seed.py" live
        touch "$SB/.seeded_live"
    fi
    log "HOME sandbox : $SB   logs : $RUN/"
}

# Instantané du seed : `start --snapshot` restaure un HOME seedé depuis
# ~/.cache/bz-sandbox/seed-<empreinte>.tar.zst (quelques secondes) ; à défaut (ou `--reseed`),
# joue le seed complet, attend que le parc soit AU REPOS, arrête tout (plus aucun processus
# d'agent : l'archive ne doit contenir aucun « en cours » sans processus), archive, puis
# redémarre. L'empreinte et la réécriture des chemins sont dans snapshot.py.
# Attend que les agents de CE HOME aient fini d'écrire leur session avant d'archiver.
wait_agents_gone() {
    for _ in $(seq 1 50); do
        pgrep -f -- "--session-file $SB/" >/dev/null || return 0
        sleep 0.2
    done
    pkill -KILL -f -- "--session-file $SB/" 2>/dev/null || true
    sleep 0.5
}

cmd_snapshot() {
    local reseed="${1:-0}" archive t0 fp
    fp="$("$PY" "$REPO/tests/sandbox/snapshot.py" fingerprint)"
    archive="$HOME/.cache/bz-sandbox/seed-$fp.tar.zst"
    [ -n "${BZ_SNAPSHOT_DIR:-}" ] && archive="$BZ_SNAPSHOT_DIR/seed-$fp.tar.zst"
    if [ "$reseed" = 1 ] || [ ! -f "$archive" ]; then
        log "instantané absent ou périmé → seed complet puis archive ($archive)"
        t0=$(date +%s)
        cmd_stop; rm -rf "$SB"
        cmd_start --seed
        "$PY" "$REPO/tests/sandbox/snapshot.py" wait-idle "http://127.0.0.1:$UI_PORT" 240
        cmd_stop
        wait_agents_gone
        "$PY" "$REPO/tests/sandbox/snapshot.py" create "$SB" "$(( $(date +%s) - t0 ))" "$fp"
    else
        cmd_stop
        "$PY" "$REPO/tests/sandbox/snapshot.py" restore "$SB" "$archive"
    fi
    cmd_start
}

cmd_seed_offline() {
    mkdir -p "$SB"
    "${SBENV[@]}" "$PY" "$REPO/tests/sandbox/seed.py" offline
    touch "$SB/.seeded"
}

cmd_seed() {
    cmd_seed_offline
    if alive "$RUN/ui.pid"; then
        "${SBENV[@]}" BZ_UI="http://127.0.0.1:$UI_PORT" "$PY" "$REPO/tests/sandbox/seed.py" live
        touch "$SB/.seeded_live"
    else
        log "serveur arrêté : seul le seed hors-ligne a été joué (relance avec start --seed pour le seed live)"
    fi
}

cmd_stop() {
    kill_tree "$RUN/ui.pid"
    kill_agents
    kill_tree "$RUN/llm.pid"
    # `restart` enchaîne sur un start : le serveur refuse un port encore lié (garde
    # anti-double instance), on attend donc que NOS ports soient réellement libérés.
    for port in "$UI_PORT" "$LLM_PORT"; do
        for _ in $(seq 1 50); do
            curl -s -o /dev/null --max-time 0.3 "http://127.0.0.1:$port/" || break
            sleep 0.2
        done
    done
    log "arrêté"
}

cmd_status() {
    alive "$RUN/llm.pid" && log "faux LLM   : UP   (pid $(cat "$RUN/llm.pid")) http://127.0.0.1:$LLM_PORT" || log "faux LLM   : DOWN"
    alive "$RUN/ui.pid" && log "bouzeui   : UP   (pid $(cat "$RUN/ui.pid")) http://127.0.0.1:$UI_PORT" || log "bouzeui   : DOWN"
    log "agents vivants : $(pgrep -fc -- "--session-file $SB/" || true)"
}

case "${1:-start}" in
    start) shift || true; cmd_start "$@" ;;
    stop) cmd_stop ;;
    restart) shift || true; cmd_stop; cmd_start "$@" ;;
    status) cmd_status ;;
    seed) cmd_seed ;;
    *) echo "usage: $0 start [--seed] [--fresh] [--snapshot] [--reseed] [--test] | stop | restart | status | seed" >&2; exit 2 ;;
esac
