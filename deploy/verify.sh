#!/usr/bin/env bash
# =============================================================================
# Alladin Jafar — Script de vérification du déploiement (SAFE, read-only)
# =============================================================================
# Usage : bash deploy/verify.sh [--health]
#
# Vérifie la cohérence des artefacts de déploiement sans écrire ni trader.
# --health : effectue aussi un appel HTTP vers /api/runtime/health (optionnel)
# =============================================================================
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY="$REPO_DIR/deploy"
MC_PORT="${MC_PORT:-8002}"
CHECK_HEALTH=false
[[ "${1:-}" == "--health" ]] && CHECK_HEALTH=true

PASS=0
FAIL=0

check() {
    local desc="$1"
    local result="$2"
    if [[ "$result" == "ok" ]]; then
        echo "[PASS] $desc"
        ((PASS++)) || true
    else
        echo "[FAIL] $desc — $result"
        ((FAIL++)) || true
    fi
}

file_exists() { [[ -f "$1" ]] && echo "ok" || echo "absent: $1"; }
contains()    { grep -qF "$2" "$1" && echo "ok" || echo "pattern absent: $2"; }
not_contains(){ grep -qF "$2" "$1" && echo "présent (interdit): $2" || echo "ok"; }

# -----------------------------------------------------------------------------
# Fichiers présents
# -----------------------------------------------------------------------------
check "alladin-jafar-paper.service présent"            "$(file_exists "$DEPLOY/alladin-jafar-paper.service")"
check "alladin-jafar-mission-control.service présent"  "$(file_exists "$DEPLOY/alladin-jafar-mission-control.service")"
check "alladin-jafar.env.example présent"              "$(file_exists "$DEPLOY/alladin-jafar.env.example")"
check "install.sh présent"                             "$(file_exists "$DEPLOY/install.sh")"

# -----------------------------------------------------------------------------
# Service PAPER — sécurité trading
# -----------------------------------------------------------------------------
PSVC="$DEPLOY/alladin-jafar-paper.service"
check "PAPER: mode PAPER"                   "$(contains "$PSVC" "--mode PAPER")"
check "PAPER: broker crypto-public"         "$(contains "$PSVC" "--broker crypto-public")"
check "PAPER: cycles infinis"               "$(contains "$PSVC" "--cycles 0")"
check "PAPER: pas de LIVE"                  "$(not_contains "$PSVC" "--mode LIVE")"
check "PAPER: EnvironmentFile"              "$(contains "$PSVC" "EnvironmentFile=")"
check "PAPER: KillSignal=SIGTERM"           "$(contains "$PSVC" "KillSignal=SIGTERM")"
check "PAPER: RestartPreventExitStatus=3"   "$(contains "$PSVC" "RestartPreventExitStatus=3")"
check "PAPER: pas de secret hardcodé"       "$(not_contains "$PSVC" "BINANCE_API_KEY=")"

# -----------------------------------------------------------------------------
# Service Mission Control
# -----------------------------------------------------------------------------
MSVC="$DEPLOY/alladin-jafar-mission-control.service"
check "MC: commande serve"                  "$(contains "$MSVC" "jafar serve")"
check "MC: broker crypto-public"            "$(contains "$MSVC" "--broker crypto-public")"
check "MC: pas de commande run"             "$(not_contains "$MSVC" "jafar run")"
check "MC: EnvironmentFile"                 "$(contains "$MSVC" "EnvironmentFile=")"
check "MC: pas de secret hardcodé"          "$(not_contains "$MSVC" "BINANCE_API_KEY=")"

# -----------------------------------------------------------------------------
# Env example
# -----------------------------------------------------------------------------
ENV="$DEPLOY/alladin-jafar.env.example"
check "ENV: ALLADIN_DATA_DIR documenté"     "$(contains "$ENV" "ALLADIN_DATA_DIR")"
check "ENV: /var/lib/alladin mentionné"     "$(contains "$ENV" "/var/lib/alladin")"
check "ENV: chmod 600 documenté"            "$(contains "$ENV" "chmod 600")"

# -----------------------------------------------------------------------------
# CLI exit code fail-closed
# -----------------------------------------------------------------------------
CLI="$REPO_DIR/src/alladin/cli.py"
check "CLI: exit 3 sur FAILED"              "$(contains "$CLI" "typer.Exit(code=3)")"

# -----------------------------------------------------------------------------
# Health check optionnel
# -----------------------------------------------------------------------------
if $CHECK_HEALTH; then
    if command -v curl >/dev/null 2>&1; then
        STATUS_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$MC_PORT/api/runtime/health" 2>/dev/null || echo "000")
        if [[ "$STATUS_CODE" == "200" || "$STATUS_CODE" == "404" ]]; then
            check "HTTP /api/runtime/health accessible (code $STATUS_CODE)" "ok"
        else
            check "HTTP /api/runtime/health" "code HTTP: $STATUS_CODE (service démarré ?)"
        fi
    else
        echo "[SKIP] curl non disponible — health check ignoré"
    fi
fi

# -----------------------------------------------------------------------------
# Résumé
# -----------------------------------------------------------------------------
echo ""
echo "Résultat : $PASS passés, $FAIL échoués"
[[ $FAIL -eq 0 ]] && echo "OK — artefacts valides." || exit 1
