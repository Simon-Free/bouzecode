#!/usr/bin/env bash
# ============================================================================
# Rejouer seulement ce qui a changé — les trois niveaux de tests, dans l'ordre du moins
# cher au plus cher :
#   1. vitest --changed            JS unitaire : graphe d'imports des modules modifiés
#   2. pytest --testmon            Flask test client + backend : couverture de code Python
#                                  (même processus : testmon voit tout ce qui est exécuté)
#   3. pytest --only-changed --ff  bout en bout (navigateur + bac à sable) : chaque fichier
#                                  déclare ce qu'il couvre (marqueur `couvre`), car le JS
#                                  et le serveur tournent hors du processus de test.
#
#   scripts/test_changed.sh                 modifs non commitées
#   scripts/test_changed.sh --ref develop   + les commits de la branche depuis develop
#   scripts/test_changed.sh --all           tout rejouer (et rafraîchir la base testmon)
#   scripts/test_changed.sh --no-e2e        sans le niveau 3
#
# Le niveau 3 démarre UN bac à sable restauré depuis l'instantané du seed PAR PAGE (Bureau,
# Agents, Profils : ports 5556-5558 / 5599-5597, HOME /tmp/bz-sb-changed-*), en mode test
# (faux LLM sans latence), et les arrête à la sortie quoi qu'il arrive.
# Python = .venv/bin/python, JAMAIS `uv run` (index uv injoignable).
# ============================================================================
set -uo pipefail

REPO="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$REPO/.venv/bin/python"
WEB="$REPO/src/bouzecode/web_v2"
export PATH="$HOME/.local/bin:$PATH"

REF="" ALL=0 E2E=1
while [ $# -gt 0 ]; do
    case "$1" in
        --ref) REF="${2:?--ref demande une référence git}"; shift ;;
        --ref=*) REF="${1#--ref=}" ;;
        --all) ALL=1 ;;
        --no-e2e) E2E=0 ;;
        -h|--help) sed -n 2,23p "$0"; exit 0 ;;
        *) echo "option inconnue : $1" >&2; exit 2 ;;
    esac
    shift
done

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ECHECS=()

# --- 1. vitest -----------------------------------------------------------------------
say "1/3 vitest $([ "$ALL" = 1 ] && echo '(tout)' || echo "--changed ${REF:-(non commité)}")"
(
    cd "$WEB" || exit 1
    if [ "$ALL" = 1 ]; then npx vitest run
    elif [ -n "$REF" ]; then npx vitest run --changed "$REF" --passWithNoTests
    else npx vitest run --changed --passWithNoTests
    fi
) || ECHECS+=("vitest")

# --- 2. pytest --testmon -------------------------------------------------------------
#  testmon garde sa base dans .testmondata (racine du dépôt, ignorée par git). Le premier
#  run rejoue tout pour la construire. Il ne connaît pas les références git : --ref est
#  sans effet ici, il compare à SON dernier run.
#  Deux pièges de testmon, d'où la ligne de commande :
#   - il DÉSACTIVE sa sélection dès qu'un `-m` est présent ; or `addopts` en impose un
#     (`-m 'not web and not ui'`) → `-o addopts=""`, et on désigne les dossiers à la main ;
#   - il plante sans le cacheprovider (KeyError 'lf') → jamais `-p no:cacheprovider` ici.
say "2/3 pytest --testmon (web_v2 hors bout en bout, backend)"
TESTMON=(--testmon)
[ "$ALL" = 1 ] && TESTMON=(--testmon-noselect)
(
    cd "$REPO" || exit 1
    "$PY" -m pytest -q -o addopts="" "${TESTMON[@]}" -n 8 \
        "$WEB/tests" tests/web_v2 tests/backend \
        --ignore="$WEB/tests/e2e_sandbox" --ignore="$WEB/tests/playwright"
    rc=$?
    [ "$rc" = 5 ] && rc=0   # 5 = aucun test sélectionné : rien n'a bougé, ce n'est pas un échec
    exit "$rc"
) || ECHECS+=("pytest --testmon")

# --- 3. bout en bout -----------------------------------------------------------------
if [ "$E2E" = 1 ]; then
    say "3/3 bout en bout $([ "$ALL" = 1 ] && echo '(tout)' || echo "--only-changed ${REF:-(non commité)}")"
    PAGES=("bureau 5556 5599" "agents 5557 5598" "profils 5558 5597")
    sb() {  # page ui llm action…
        BZ_SANDBOX_HOME="/tmp/bz-sb-changed-$1" BZ_UI_PORT="$2" MOCK_LLM_PORT="$3" \
            "$REPO/tests/sandbox/run_sandbox.sh" "${@:4}"
    }
    arreter() { for p in "${PAGES[@]}"; do set -- $p; sb "$1" "$2" "$3" stop >/dev/null 2>&1; done; }
    trap arreter EXIT
    T0=$(date +%s)
    for p in "${PAGES[@]}"; do
        set -- $p
        sb "$1" "$2" "$3" start --snapshot --test | grep -E "instantané|snapshot|bouzeui|seed\] fini" \
            || { ECHECS+=("bac à sable $1"); }
    done
    echo "bacs à sable prêts en $(( $(date +%s) - T0 )) s"
    SEL=(--only-changed${REF:+=$REF})
    [ "$ALL" = 1 ] && SEL=()
    (
        cd "$REPO" || exit 1
        BZ_E2E_URL_BUREAU=http://127.0.0.1:5556 \
        BZ_E2E_URL_AGENTS=http://127.0.0.1:5557 \
        BZ_E2E_URL_PROFILS=http://127.0.0.1:5558 BZ_E2E_HOME_PROFILS=/tmp/bz-sb-changed-profils \
            "$PY" -m pytest -q -m "web or not web" --ff \
                "$WEB/tests/e2e_sandbox" "$WEB/tests/playwright" "${SEL[@]}"
        rc=$?
        [ "$rc" = 5 ] && rc=0
        exit "$rc"
    ) || ECHECS+=("bout en bout")
fi

say "bilan"
if [ ${#ECHECS[@]} -eq 0 ]; then echo "tout est vert"; exit 0; fi
printf 'en échec : %s\n' "${ECHECS[@]}"
exit 1
