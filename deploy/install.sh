#!/usr/bin/env bash
# =============================================================================
# Alladin Jafar — Script d'installation Linux (systemd)
# =============================================================================
# Usage : sudo bash deploy/install.sh
#
# Ce script PRÉPARE le service. Il ne lance PAS le trading.
# Activation et démarrage sont des étapes manuelles explicites — voir
# docs/DEPLOY_LINUX.md pour la procédure complète.
#
# Invariants :
#   - Aucun secret créé automatiquement
#   - Aucun démarrage automatique sans confirmation
#   - Aucune dépendance réseau douteuse
# =============================================================================
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_USER="alladin"
DATA_DIR="/var/lib/alladin/jafar"
CONFIG_DIR="/etc/alladin"
SYSTEMD_DIR="/etc/systemd/system"

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
info()  { echo "[INFO]  $*"; }
warn()  { echo "[WARN]  $*" >&2; }
die()   { echo "[ERROR] $*" >&2; exit 1; }
ok()    { echo "[OK]    $*"; }

# -----------------------------------------------------------------------------
# Vérifications préalables
# -----------------------------------------------------------------------------
[[ "$(uname -s)" == "Linux" ]] || die "Ce script est uniquement pour Linux."
[[ $EUID -eq 0 ]] || die "À exécuter en root : sudo bash deploy/install.sh"
command -v python3 >/dev/null 2>&1 || die "Python 3 requis (python3 introuvable)."
command -v systemctl >/dev/null 2>&1 || die "systemd requis (systemctl introuvable)."

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
info "Python détecté : $PYTHON_VERSION"

# -----------------------------------------------------------------------------
# Utilisateur de service
# -----------------------------------------------------------------------------
if id "$SERVICE_USER" &>/dev/null; then
    ok "Utilisateur $SERVICE_USER existe déjà."
else
    info "Création de l'utilisateur $SERVICE_USER (sans shell, sans home)..."
    useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
    ok "Utilisateur $SERVICE_USER créé."
fi

# -----------------------------------------------------------------------------
# Répertoires de données
# -----------------------------------------------------------------------------
info "Création de $DATA_DIR ..."
mkdir -p "$DATA_DIR"
chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR"
chmod 750 "$DATA_DIR"
ok "$DATA_DIR prêt."

# -----------------------------------------------------------------------------
# Répertoire de configuration
# -----------------------------------------------------------------------------
info "Création de $CONFIG_DIR ..."
mkdir -p "$CONFIG_DIR"
chmod 750 "$CONFIG_DIR"

if [[ ! -f "$CONFIG_DIR/jafar.env" ]]; then
    cp "$REPO_DIR/deploy/alladin-jafar.env.example" "$CONFIG_DIR/jafar.env"
    chown root:alladin "$CONFIG_DIR/jafar.env"
    chmod 640 "$CONFIG_DIR/jafar.env"
    warn "IMPORTANT: Éditez /etc/alladin/jafar.env avant de démarrer le service."
    warn "           Vérifiez au minimum ALLADIN_DATA_DIR et les paramètres runtime."
else
    ok "$CONFIG_DIR/jafar.env existe déjà — non écrasé."
fi

# -----------------------------------------------------------------------------
# Permissions sur le repo
# -----------------------------------------------------------------------------
info "Ajustement des permissions sur $REPO_DIR ..."
chown -R "$SERVICE_USER:$SERVICE_USER" "$REPO_DIR"
ok "Permissions répertoire repo appliquées."

# -----------------------------------------------------------------------------
# Venv Python
# -----------------------------------------------------------------------------
VENV_DIR="$REPO_DIR/.venv"
if [[ ! -d "$VENV_DIR" ]]; then
    info "Création du venv Python dans $VENV_DIR ..."
    sudo -u "$SERVICE_USER" python3 -m venv "$VENV_DIR"
    info "Installation des dépendances..."
    sudo -u "$SERVICE_USER" "$VENV_DIR/bin/pip" install -q --upgrade pip
    sudo -u "$SERVICE_USER" "$VENV_DIR/bin/pip" install -q -e "$REPO_DIR"
    ok "Venv et dépendances installés."
else
    ok "Venv $VENV_DIR existe déjà."
    info "Mise à jour des dépendances..."
    sudo -u "$SERVICE_USER" "$VENV_DIR/bin/pip" install -q -e "$REPO_DIR"
fi

# -----------------------------------------------------------------------------
# Units systemd
# -----------------------------------------------------------------------------
info "Copie des units systemd..."
cp "$REPO_DIR/deploy/alladin-jafar-paper.service" "$SYSTEMD_DIR/"
cp "$REPO_DIR/deploy/alladin-jafar-mission-control.service" "$SYSTEMD_DIR/"
chmod 644 "$SYSTEMD_DIR/alladin-jafar-paper.service"
chmod 644 "$SYSTEMD_DIR/alladin-jafar-mission-control.service"
ok "Units copiées dans $SYSTEMD_DIR."

# Mettre à jour WorkingDirectory dans les units avec le chemin réel
sed -i "s|WorkingDirectory=/opt/alladin|WorkingDirectory=$REPO_DIR|g" \
    "$SYSTEMD_DIR/alladin-jafar-paper.service" \
    "$SYSTEMD_DIR/alladin-jafar-mission-control.service"

# Mettre à jour ExecStart avec le venv réel
sed -i "s|/opt/alladin/.venv/bin/python|$VENV_DIR/bin/python|g" \
    "$SYSTEMD_DIR/alladin-jafar-paper.service" \
    "$SYSTEMD_DIR/alladin-jafar-mission-control.service"

systemctl daemon-reload
ok "daemon-reload effectué."

# -----------------------------------------------------------------------------
# Run initial Jafar (crée le premier run si absent)
# -----------------------------------------------------------------------------
info "Vérification/création du run Jafar initial..."
if sudo -u "$SERVICE_USER" "$VENV_DIR/bin/python" -m alladin jafar new --broker crypto-public 2>/dev/null; then
    ok "Run Jafar créé."
else
    info "Un run Jafar existe déjà ou impossible de créer maintenant (réseau requis)."
    info "Vous pouvez créer manuellement : python -m alladin jafar new --broker crypto-public"
fi

# -----------------------------------------------------------------------------
# Résumé — NE PAS DÉMARRER AUTOMATIQUEMENT
# -----------------------------------------------------------------------------
echo ""
echo "============================================================"
echo " Installation terminée. Services NON démarrés."
echo "============================================================"
echo ""
echo " Prochaines étapes MANUELLES :"
echo ""
echo "  1. Vérifiez /etc/alladin/jafar.env"
echo "     ALLADIN_DATA_DIR=/var/lib/alladin/jafar"
echo ""
echo "  2. Passez le mode Jafar en PAPER si ce n'est pas fait :"
echo "     sudo -u alladin $VENV_DIR/bin/python -m alladin jafar mode PAPER --broker crypto-public"
echo ""
echo "  3. Activez et démarrez les services :"
echo "     systemctl enable alladin-jafar-paper"
echo "     systemctl enable alladin-jafar-mission-control"
echo "     systemctl start alladin-jafar-paper"
echo "     systemctl start alladin-jafar-mission-control"
echo ""
echo "  4. Vérifiez :"
echo "     systemctl status alladin-jafar-paper"
echo "     journalctl -u alladin-jafar-paper -f"
echo "     curl http://127.0.0.1:8002/api/runtime/health"
echo ""
echo " RAPPEL : le trading reste PAPER — aucun ordre Binance production."
echo "============================================================"
