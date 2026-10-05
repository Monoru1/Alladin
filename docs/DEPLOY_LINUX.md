# Alladin Jafar — Déploiement Linux (systemd)

> **Périmètre** : runtime PAPER uniquement. Données publiques Binance. Aucun ordre réel.
> LIVE n'est pas raccordé et ne sera jamais activé sans procédure séparée explicite.

---

## 1. Prérequis

```bash
# Système
uname -s          # doit retourner Linux
python3 --version # 3.11+ recommandé
sqlite3 --version # pour backups
git --version

# Réseau — l'accès public Binance doit être disponible
curl -s https://api.binance.com/api/v3/ping
```

---

## 2. Créer l'utilisateur alladin

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin alladin
```

---

## 3. Cloner le repo

```bash
sudo mkdir -p /opt/alladin
sudo chown alladin:alladin /opt/alladin
sudo -u alladin git clone https://github.com/Monoru1/Alladin.git /opt/alladin
cd /opt/alladin
```

---

## 4. Créer le venv Python

```bash
sudo -u alladin python3 -m venv /opt/alladin/.venv
sudo -u alladin /opt/alladin/.venv/bin/pip install -q --upgrade pip
sudo -u alladin /opt/alladin/.venv/bin/pip install -q -e /opt/alladin
```

Vérification :

```bash
sudo -u alladin /opt/alladin/.venv/bin/python -m alladin --help
```

---

## 5. Créer /var/lib/alladin

```bash
sudo mkdir -p /var/lib/alladin/jafar
sudo mkdir -p /var/lib/alladin/backups
sudo chown -R alladin:alladin /var/lib/alladin
sudo chmod 750 /var/lib/alladin/jafar
```

---

## 6. Créer /etc/alladin/jafar.env

```bash
sudo mkdir -p /etc/alladin
sudo cp /opt/alladin/deploy/alladin-jafar.env.example /etc/alladin/jafar.env
sudo chown root:alladin /etc/alladin/jafar.env
sudo chmod 640 /etc/alladin/jafar.env
```

Éditez le fichier :

```bash
sudo nano /etc/alladin/jafar.env
```

Configuration minimale requise :

```ini
ALLADIN_DATA_DIR=/var/lib/alladin/jafar
RUNTIME_STALE_AFTER_S=120
RUNTIME_MAX_FAILURES=5
RUNTIME_BACKOFF_BASE_S=5
RUNTIME_BACKOFF_CAP_S=60
```

---

## 7. Créer le run Jafar initial

```bash
sudo -u alladin /opt/alladin/.venv/bin/python -m alladin jafar new --broker crypto-public
```

Passer en mode PAPER :

```bash
sudo -u alladin /opt/alladin/.venv/bin/python -m alladin jafar mode PAPER --broker crypto-public
```

---

## 8. Installer les units systemd

```bash
sudo cp /opt/alladin/deploy/alladin-jafar-paper.service /etc/systemd/system/
sudo cp /opt/alladin/deploy/alladin-jafar-mission-control.service /etc/systemd/system/

# Adapter les chemins si le repo n'est pas dans /opt/alladin
sudo sed -i 's|/opt/alladin|/opt/alladin|g' \
    /etc/systemd/system/alladin-jafar-paper.service \
    /etc/systemd/system/alladin-jafar-mission-control.service

sudo chmod 644 /etc/systemd/system/alladin-jafar-paper.service
sudo chmod 644 /etc/systemd/system/alladin-jafar-mission-control.service
```

---

## 9. daemon-reload

```bash
sudo systemctl daemon-reload
```

---

## 10. Activer au boot

```bash
sudo systemctl enable alladin-jafar-paper
sudo systemctl enable alladin-jafar-mission-control
```

---

## 11. Démarrer

```bash
sudo systemctl start alladin-jafar-paper
sudo systemctl start alladin-jafar-mission-control
```

---

## 12. Status

```bash
sudo systemctl status alladin-jafar-paper
sudo systemctl status alladin-jafar-mission-control
```

---

## 13. Logs

```bash
# Suivi en direct — runtime PAPER
journalctl -u alladin-jafar-paper -f

# Suivi en direct — Mission Control
journalctl -u alladin-jafar-mission-control -f

# Dernières 100 lignes
journalctl -u alladin-jafar-paper -n 100 --no-pager
```

---

## 14. Mission Control (cockpit)

Le cockpit est accessible localement :

```
http://127.0.0.1:8002/
```

Pour l'exposer via un reverse proxy (nginx recommandé) :

```nginx
location /jafar/ {
    proxy_pass http://127.0.0.1:8002/;
    proxy_set_header Host $host;
    # Pas d'authentification : read-only, mais à protéger si exposé publiquement
}
```

---

## 15. Health check

```bash
# Santé du runtime
curl http://127.0.0.1:8002/api/runtime/health

# Santé globale (broker, stale, cycle)
curl http://127.0.0.1:8002/health
```

> **IMPORTANT** : `systemctl active` ≠ Alladin healthy.
> Un service peut être `active (running)` et le runtime en état `STALE` ou `DEGRADED`
> si Binance est injoignable. Toujours vérifier `/api/runtime/health`.

Réponse healthy attendue :

```json
{
  "status": "HEALTHY",
  "provider_status": "UP",
  "consecutive_failures": 0,
  "last_heartbeat_at": "...",
  "heartbeat_stale": false
}
```

---

## 16. Stop / Restart

```bash
# Arrêt propre (SIGTERM → STOPPING → STOPPED)
sudo systemctl stop alladin-jafar-paper

# Restart
sudo systemctl restart alladin-jafar-paper

# Mission Control uniquement (sans toucher au runtime)
sudo systemctl restart alladin-jafar-mission-control
```

---

## 17. Graceful shutdown

```bash
# Envoi manuel d'un SIGTERM au processus
sudo systemctl kill --signal=SIGTERM alladin-jafar-paper

# Vérifier la transition STOPPING → STOPPED dans les logs
journalctl -u alladin-jafar-paper -n 20 --no-pager
```

---

## 18. Test de reboot

```bash
sudo reboot
# Après reboot :
sudo systemctl status alladin-jafar-paper
curl http://127.0.0.1:8002/api/runtime/health
# Vérifier positions restaurées sans duplication :
sudo -u alladin /opt/alladin/.venv/bin/python -m alladin jafar positions --broker crypto-public
```

---

## 19. Backup

```bash
# Backup manuel
bash /opt/alladin/scripts/backup_jafar_db.sh

# Backup vers répertoire spécifique
bash /opt/alladin/scripts/backup_jafar_db.sh /mnt/backup/alladin

# Cron quotidien (en root ou alladin)
# 0 3 * * * bash /opt/alladin/scripts/backup_jafar_db.sh >> /var/log/alladin-backup.log 2>&1
```

---

## 20. Upgrade

```bash
# 1. Backup avant tout
bash /opt/alladin/scripts/backup_jafar_db.sh

# 2. Arrêt propre
sudo systemctl stop alladin-jafar-paper alladin-jafar-mission-control

# 3. Pull
sudo -u alladin git -C /opt/alladin pull

# 4. Mise à jour dépendances
sudo -u alladin /opt/alladin/.venv/bin/pip install -q -e /opt/alladin

# 5. Éventuellement re-copier les units si modifiées
sudo cp /opt/alladin/deploy/alladin-jafar-paper.service /etc/systemd/system/
sudo cp /opt/alladin/deploy/alladin-jafar-mission-control.service /etc/systemd/system/
sudo systemctl daemon-reload

# 6. Redémarrer
sudo systemctl start alladin-jafar-paper alladin-jafar-mission-control
```

---

## 21. Rollback

```bash
# Arrêt
sudo systemctl stop alladin-jafar-paper alladin-jafar-mission-control

# Restaurer base (si nécessaire)
DB="/var/lib/alladin/jafar/alladin.db"
cp "$DB" "${DB}.before_rollback"
cp /var/lib/alladin/backups/jafar_YYYY-MM-DD_HHMMSS.db "$DB"
chown alladin:alladin "$DB"

# Rollback code
sudo -u alladin git -C /opt/alladin checkout <SHA_STABLE>
sudo -u alladin /opt/alladin/.venv/bin/pip install -q -e /opt/alladin

# Redémarrer
sudo systemctl start alladin-jafar-paper alladin-jafar-mission-control
```

---

## 22. Incident — RuntimeStatus.FAILED (fail-closed)

Quand `RuntimeStatus.FAILED` est atteint, le process **s'arrête volontairement avec exit code 3**.
systemd **ne relance pas** (grâce à `RestartPreventExitStatus=3`).

```bash
# Diagnostiquer
journalctl -u alladin-jafar-paper -n 50 --no-pager
curl http://127.0.0.1:8002/api/runtime/health

# Les positions PAPER sont conservées — aucune fermeture automatique
sudo -u alladin /opt/alladin/.venv/bin/python -m alladin jafar positions --broker crypto-public

# Corriger la cause racine (provider, réseau, config), puis redémarrer manuellement
sudo systemctl start alladin-jafar-paper
```

---

## 23. Ne jamais passer LIVE

La transition vers LIVE est verrouillée dans le code. Le CLI refusera toute tentative.

```bash
# Ceci échoue intentionnellement (mode non raccordé)
python -m alladin jafar run --mode LIVE  # → erreur
```

---

## Acceptance checklist serveur

```
[ ] Service démarre au boot (reboot test)
[ ] Runtime heartbeat visible dans /api/runtime/health
[ ] Mission Control accessible http://127.0.0.1:8002/
[ ] status = HEALTHY
[ ] last_market_update_at avance à chaque cycle
[ ] provider_status = UP
[ ] Mode PAPER uniquement (vérifié via /api/workspace)
[ ] Aucun write production (broker crypto-public)
[ ] Provider outage → status = DEGRADED (test simulé)
[ ] Recovery → status = HEALTHY
[ ] SIGTERM → STOPPING → STOPPED dans les logs
[ ] Restart après STOPPED → positions restaurées sans duplication
[ ] Reboot machine → positions restaurées sans duplication
[ ] Logs ne contiennent aucun secret (grep BINANCE_API_KEY /var/log/journal/...)
[ ] DB survit au reboot (/var/lib/alladin/jafar/alladin.db présente)
[ ] Backup restaurable (test de restauration depuis backup)
[ ] FAILED (exit 3) → systemd ne relance pas
```
