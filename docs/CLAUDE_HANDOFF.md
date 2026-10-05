# ALLADIN — Claude Handoff

## HEAD
branch: main | SHA: 22a608a | dernier push fonctionnel/doc: 2026-10-05

Commits du lot Linux/systemd packaging :
- e7fb23d feat: Linux packaging — install/verify scripts, backup, DEPLOY_LINUX.md
- b7406ba feat: Linux/systemd packaging — units, env template, fail-closed exit code
- b56ccfd feat: surface runtime health in Mission Control
- 35e37be feat: persist runtime health and heartbeat state
- 04db040 feat: expose Jafar PAPER endurance harness via CLI

## Ce qui vient d'être terminé

**Lot 4 — Linux/systemd packaging** (b7406ba + e7fb23d) :
- `deploy/alladin-jafar-paper.service` : runtime PAPER, `Restart=on-failure`,
  `RestartPreventExitStatus=3` (fail-closed ne relance pas), `KillSignal=SIGTERM`,
  hardening `NoNewPrivileges/PrivateTmp/ProtectSystem/ProtectHome`
- `deploy/alladin-jafar-mission-control.service` : cockpit séparé, restart indépendant
- `deploy/alladin-jafar.env.example` : template sans secret, `/etc/alladin/jafar.env`,
  `chmod 640` documenté
- `deploy/install.sh` : prépare service sans démarrer automatiquement le trading
- `deploy/verify.sh` : vérification read-only des artefacts + health check optionnel
- `scripts/backup_jafar_db.sh` : backup SQLite hot (`sqlite3 .backup`), intégrité check,
  procédure de restauration
- `docs/DEPLOY_LINUX.md` : procédure complète (prérequis → upgrade → rollback →
  incident FAILED → acceptance checklist)
- `cli.py` : exit 3 après `run_loop()` si `RuntimeStatus.FAILED` (fail-closed logique)
- `tests/test_deploy_artifacts.py` : 38 tests structurels

## État réel

| Fonctionnalité | État |
|---|---|
| PAPER end-to-end | OUI |
| Risk traversé | OUI |
| Anti-duplication | OUI |
| Heartbeat persisté journal | OUI |
| Stale detection (bloque entrée) | OUI |
| Provider failure → DEGRADED | OUI |
| Backoff borné testable | OUI |
| Provider recovery → HEALTHY | OUI |
| Fail closed (seuil FAILED) | OUI |
| Exit 3 fail-closed (no systemd restart) | OUI |
| Graceful shutdown STOPPING→STOPPED | OUI |
| run_loop() avec SIGINT/SIGTERM | OUI |
| Health API GET /api/runtime/health | OUI |
| Restart sans duplication | OUI |
| Endurance harness | OUI |
| Runtime health UI (Mission Control) | OUI |
| JAFAR allowed_modes OBSERVE+PAPER | OUI |
| systemd units (2 services séparés) | IMPLEMENTED |
| EnvironmentFile template | IMPLEMENTED |
| install.sh | IMPLEMENTED |
| verify.sh | IMPLEMENTED |
| backup SQLite | IMPLEMENTED |
| DEPLOY_LINUX.md | IMPLEMENTED |
| 100/1000 cycles propres | TESTED |
| Fault injection déterministe | TESTED |
| Artefacts déploiement structurels | TESTED (38 tests) |
| Long-run réelle (24/7) | NON VALIDÉE |
| Déploiement serveur réel | NON DÉPLOYÉ |
| TESTNET validation réelle | NON |
| LIVE | NON |

## Validation (e7fb23d)

- 907 passed, 3 skipped (MT5), 0 failed
- mypy clean sur tous les fichiers modifiés
- ruff clean sur tous les fichiers modifiés

## Fichiers clés

```
src/alladin/orchestration/health.py          # RuntimeHealthTracker complet
src/alladin/jafar/paper.py                   # JafarPaperRuntime + run_loop()
src/alladin/api/app.py                       # GET /api/runtime/health
src/alladin/api/static/index.html            # Panel runtime health + banner PAPER
src/alladin/cli.py                           # jafar run/serve/endurance + exit 3 FAILED
src/alladin/core/config.py                   # runtime_stale_after_s, max_failures, backoff_*
deploy/alladin-jafar-paper.service           # unit systemd runtime PAPER
deploy/alladin-jafar-mission-control.service # unit systemd Mission Control
deploy/alladin-jafar.env.example             # template /etc/alladin/jafar.env
deploy/install.sh                            # script d'installation (ne démarre pas)
deploy/verify.sh                             # vérification artefacts (read-only)
scripts/backup_jafar_db.sh                   # backup SQLite hot
docs/DEPLOY_LINUX.md                         # procédure complète déploiement
tests/test_deploy_artifacts.py               # 38 tests structurels déploiement
tests/test_mission_control_health.py         # 12 tests Mission Control health
tests/test_jafar_paper_endurance.py          # 11 tests endurance harness
tests/test_jafar_runtime_health.py           # 6 tests intégration health
```

## Architecture des services

```
alladin-jafar-paper.service          alladin-jafar-mission-control.service
  python -m alladin jafar run          python -m alladin jafar serve
  --broker crypto-public               --broker crypto-public
  --mode PAPER                         --host 127.0.0.1
  --cycles 0                           --port 8002
  --interval 300
  
  EnvironmentFile=/etc/alladin/jafar.env (partagé)
  DB: /var/lib/alladin/jafar/alladin.db (partagé, lecture seule pour MC)
```

## Fail-closed systemd

```
Exit 0  → arrêt propre (STOPPED/STOPPING) → systemd NE relance PAS
Exit 3  → fail-closed logique (FAILED)    → systemd NE relance PAS (RestartPreventExitStatus=3)
Non-zero → crash technique                → systemd relance (Restart=on-failure, RestartSec=30)
```

## Commandes de reprise

```bash
git log -5 --oneline
python -m pytest -q --tb=no

# Vérifier artefacts
bash deploy/verify.sh

# Endurance
python -m alladin jafar endurance --cycles 100 --seed 42
```

## Validation manuelle poste — 2026-10-05

- MT5 DEMO connecté, Algo Trading ON, compte DEMO READY.
- Ordre test EURUSD BUY 0.01 envoyé via le pipeline complet : RiskEngine APPROVED, order_check OK, positions_get confirme la position, SL/TP actifs, trade journalisé dans SYSTEM-TEST-001.
- Jafar `crypto-public` PAPER `--cycles 0 --interval 5` a produit plusieurs cycles successifs en boucle continue (NO_TRADE attendu dans ce smoke test).
- `jafar account` authentifié via Ed25519 read-only : `reading_enabled=true`, retraits/trading Spot désactivés pour la clé, `api_key_read_only_safe=true`.
- Mission Control Jafar reçoit health/market data, mais incohérences observées : `MODE N/A`, banner "OBSERVE ONLY" alors que le runtime tourne en PAPER.
- Ceci est un smoke test réel, PAS une validation 2–4h/24h.

## Prochain lot recommandé : Cohérence Mission Control Jafar PAPER + préparation du long-run

Le packaging est terminé et le smoke test réel est concluant. Avant le soak long, corriger la cohérence du cockpit Jafar PAPER (mode/banner/source du run actif), puis préparer une exécution mesurable 2–4h.

### Procédure recommandée
1. `python -m alladin jafar new --broker crypto-public`
2. `python -m alladin jafar mode PAPER --broker crypto-public`
3. `python -m alladin jafar run --broker crypto-public --mode PAPER --cycles 0 --interval 300`
4. Observer pendant 2–4h :
   - `curl http://127.0.0.1:8002/api/runtime/health`
   - Vérifier que `last_market_update_at` avance
   - Vérifier `consecutive_failures == 0`
   - Vérifier aucune position dupliquée
5. SIGTERM → vérifier STOPPING → STOPPED
6. Redémarrer → vérifier restore sans duplication

### À surveiller
- Stale data incidents (Binance down ?)
- Provider backoff behavior
- Drift portfolio (cash doit rester cohérent)
- Aucun write Binance production (broker crypto-public)

**Ne pas lancer 24h automatiquement avant 2–4h de validation propre.**
**Ne pas commencer avant d'avoir lu ce fichier et vérifié que pytest passe.**
