#!/usr/bin/env bash
# =============================================================================
# Alladin Jafar — Backup SQLite
# =============================================================================
# Usage : bash scripts/backup_jafar_db.sh [destination_dir]
#
# Effectue un backup SQLite en ligne (sqlite3 .backup) sans arrêter le service.
# SQLite WAL mode : safe pour un backup à chaud.
#
# Par défaut, sauvegarde dans /var/lib/alladin/backups/
# Format : jafar_YYYY-MM-DD_HHMMSS.db
# =============================================================================
set -euo pipefail

DB_PATH="${ALLADIN_DATA_DIR:-/var/lib/alladin/jafar}/alladin.db"
BACKUP_DIR="${1:-/var/lib/alladin/backups}"
TIMESTAMP=$(date +%Y-%m-%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/jafar_${TIMESTAMP}.db"

info()  { echo "[INFO]  $*"; }
ok()    { echo "[OK]    $*"; }
die()   { echo "[ERROR] $*" >&2; exit 1; }

[[ -f "$DB_PATH" ]] || die "Base de données introuvable : $DB_PATH"
command -v sqlite3 >/dev/null 2>&1 || die "sqlite3 requis (apt install sqlite3)."

mkdir -p "$BACKUP_DIR"
info "Backup de $DB_PATH → $BACKUP_FILE ..."
sqlite3 "$DB_PATH" ".backup '$BACKUP_FILE'"
ok "Backup créé : $BACKUP_FILE"

# Taille
SIZE=$(du -sh "$BACKUP_FILE" | cut -f1)
info "Taille : $SIZE"

# Vérification intégrité rapide
if sqlite3 "$BACKUP_FILE" "PRAGMA integrity_check;" | grep -q "^ok$"; then
    ok "Intégrité vérifiée."
else
    echo "[WARN]  Intégrité douteuse — vérifiez manuellement." >&2
fi

echo ""
echo "Restauration (si nécessaire) :"
echo "  systemctl stop alladin-jafar-paper alladin-jafar-mission-control"
echo "  cp $DB_PATH ${DB_PATH}.before_restore"
echo "  cp $BACKUP_FILE $DB_PATH"
echo "  chown alladin:alladin $DB_PATH"
echo "  systemctl start alladin-jafar-paper alladin-jafar-mission-control"
