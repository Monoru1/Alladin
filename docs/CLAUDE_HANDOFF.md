# ALLADIN — Claude Handoff

## HEAD
branch: main | SHA: 581a8d7 | dernier push fonctionnel/doc: 2026-10-05

Commits du lot Mission Control Health UI :
- b56ccfd feat: surface runtime health in Mission Control
- a76e52f feat: add targeted Mission Control health tests (pre-push fixup)
- 35e37be feat: persist runtime health and heartbeat state
- 7dc962d feat: wire RuntimeHealthTracker into PAPER runtime, API, and CLI
- 04db040 feat: expose Jafar PAPER endurance harness via CLI

## Ce qui vient d'être terminé

**Lot 3 — Mission Control Runtime Health UI** (b56ccfd) :
- Panel "Runtime Health" dans index.html : badge HEALTHY/DEGRADED/STALE/FAILED, dot coloré, heartbeat/cycle/market timestamps, consecutive failures, last_error, degraded_reason/stop_reason
- `allowed_modes` JAFAR corrigé : `["OBSERVE"]` → `["OBSERVE", "PAPER"]`
- Banner text corrigé : "JAFAR · OBSERVE / PAPER · pas d'ordre Binance production · LIVE verrouillé"
- Banner JS différencié : PAPER → "PAPER SIMULÉ — données publiques · aucun ordre réel · LIVE verrouillé"
- Cycle trace renderer : utilise `p.mode` quand disponible
- `test_mission_control_health.py` : 12 tests (workspace, health HEALTHY/DEGRADED/STALE/FAILED/absent, read-only, /health enrichi, null last_error, banner)
- `test_jafar_observe.py` : assertions obsolètes mises à jour (encodage latin-1 mixte corrigé en UTF-8 propre)

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
| Graceful shutdown STOPPING→STOPPED | OUI |
| run_loop() avec SIGINT/SIGTERM | OUI |
| Health API GET /api/runtime/health | OUI |
| Restart sans duplication | OUI |
| Endurance harness | OUI |
| Runtime health UI (Mission Control) | OUI |
| JAFAR allowed_modes OBSERVE+PAPER | OUI |
| 100 cycles propres | TESTED |
| 1000 cycles propres | TESTED |
| Fault injection déterministe | TESTED |
| Long-run réelle (24/7) | NON VALIDÉE |
| TESTNET validation réelle | NON |
| LIVE | NON |

## Validation (581a8d7)

- 869 passed, 3 skipped (MT5), 0 failed
- mypy clean sur tous les fichiers modifiés
- ruff clean sur tous les fichiers modifiés

## Fichiers clés

```
src/alladin/orchestration/health.py          # RuntimeHealthTracker complet
src/alladin/jafar/paper.py                   # JafarPaperRuntime + run_loop()
src/alladin/api/app.py                       # GET /api/runtime/health, allowed_modes JAFAR
src/alladin/api/static/index.html            # Panel runtime health + banner PAPER
src/alladin/cli.py                           # jafar endurance + jafar run
src/alladin/core/config.py                   # runtime_stale_after_s, max_failures, backoff_*
tests/test_runtime_health.py                 # unit tests tracker (5)
tests/test_jafar_runtime_health.py           # intégration health (6)
tests/test_jafar_paper_endurance.py          # endurance harness (11)
tests/test_mission_control_health.py         # Mission Control health UI (12)
```

## Commandes de reprise

```bash
git log -5 --oneline
python -m pytest -q --tb=no

# Endurance 100 cycles clean
python -m alladin jafar endurance --cycles 100 --seed 42

# Endurance 1000 cycles avec pannes injectées
python -m alladin jafar endurance --cycles 1000 --seed 42 \
  --provider-error-at 100,101 --stale-at 200 --graceful-stop-at 900
```

## Prochain lot recommandé : Linux/systemd packaging

Le runtime PAPER tourne. Le prochain lot utile est de packager pour un serveur Linux :

### Objectif
Alladin tourne en continu sur un VPS Linux sans supervision humaine.

### Scope minimal
1. **Script de démarrage** : `scripts/start_jafar.sh` — active venv, exporte vars d'env, lance `python -m alladin jafar run`
2. **Unit systemd** : `deploy/alladin-jafar.service` — `Restart=on-failure`, `RestartSec=30`, `StandardOutput=journal`, `WorkingDirectory`, `EnvironmentFile`
3. **EnvironmentFile template** : `deploy/alladin-jafar.env.example` — toutes les vars requises documentées (pas de secrets réels)
4. **Makefile targets** : `make install-service`, `make start`, `make stop`, `make logs`, `make status`
5. **docs/DEPLOY_LINUX.md** : procédure d'installation complète, de zéro à `systemctl status alladin-jafar`

### Invariants à respecter
- Aucun secret hardcodé — tout via EnvironmentFile
- `Restart=on-failure` uniquement — pas de restart sur FAILED (fail closed respecté)
- Logs via journald (pas de rotation manuelle)
- Pas de dépendance réseau au démarrage (ExecStartPre optionnel pour attendre network)

**Ne pas commencer avant d'avoir lu ce fichier et vérifié que pytest passe.**
