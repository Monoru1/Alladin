# ALLADIN — Claude Handoff

## HEAD
branch: main | SHA: a661b7f | dernier push fonctionnel/doc: 2026-10-05

Commits du lot Health + Endurance :
- 35e37be feat: persist runtime health and heartbeat state
- 7dc962d feat: wire RuntimeHealthTracker into PAPER runtime, API, and CLI
- ca3f63e docs: add CLAUDE_HANDOFF.md for session continuity
- 93cfa36 feat: add Paper Endurance Harness with fault injection
- 04db040 feat: expose Jafar PAPER endurance harness via CLI

## Ce qui vient d'être terminé

**Lot 1 — Runtime Health** (35e37be + 7dc962d) :
- RuntimeHealthTracker : HEALTHY / DEGRADED / STALE / STOPPING / STOPPED / FAILED
- heartbeat, market_progress, cycle_completed, provider_failure, stopping, stopped
- backoff borné, fail closed, run_loop() avec SIGINT/SIGTERM
- GET /api/runtime/health (read-only)
- Intégré dans JafarPaperRuntime, CLI, API

**Lot 2 — Paper Endurance Harness** (93cfa36 + 04db040) :
- EnduranceHarness : N cycles PAPER avec pannes injectées, aucun réseau requis
- FaultPlan + FaultEvent : provider_error, stale_data, restart, graceful_stop, price_drop/recover
- ScenarioScanner : fake scanner déterministe piloté par FaultPlan
- EnduranceReport : 25 métriques (cycles, positions, PnL, failures, drawdown...)
- check_invariants : cash >= 0, no duplicate proposal_id, health cohérent
- CLI `jafar endurance` : JSON, exit 1 si invariant_failures non vide

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
| 100 cycles propres | TESTED |
| 1000 cycles propres | TESTED |
| Fault injection déterministe | TESTED |
| Restart stress | TESTED |
| Duplicate proposal storm | TESTED |
| SL/TP stress | TESTED |
| CLI `jafar endurance` | OUI |
| Long-run réelle (24/7) | NON VALIDÉE |
| TESTNET validation réelle | NON |
| LIVE | NON |

## Invariants sécurité

- Aucun endpoint Binance production d'écriture jamais appelé en PAPER
- Stale data → StaleMarketDataError → pas de nouvelle entrée
- FAILED → boucle arrêtée, positions conservées, pas de fermeture arbitraire
- STOPPING → pas de nouvelle entrée, pas de fermeture arbitraire
- Anti-duplication par proposal_id + position symbol déjà ouverte
- `jafar endurance` : pas de réseau, pas de secrets, aucun write externe

## Validation (checkpoint fonctionnel 04db040, handoff a661b7f)

- 857 passed, 3 skipped (MT5), 0 failed
- mypy clean sur tous les fichiers modifiés
- ruff clean sur tous les fichiers modifiés
- git diff --check propre

## Fichiers clés

```
src/alladin/orchestration/health.py          # RuntimeHealthTracker complet
src/alladin/jafar/paper.py                   # JafarPaperRuntime + run_loop()
src/alladin/api/app.py                       # GET /api/runtime/health
src/alladin/cli.py                           # jafar endurance + jafar run
src/alladin/core/config.py                   # runtime_stale_after_s, max_failures, backoff_*
tests/test_runtime_health.py                 # unit tests tracker (5)
tests/test_jafar_runtime_health.py           # intégration health (6)
tests/test_jafar_paper_endurance.py          # endurance harness (11)
```

## Commandes de reprise

```bash
# Vérifier état
git log -5 --oneline
python -m pytest tests/test_jafar_paper_endurance.py -v
python -m pytest -q

# Endurance 100 cycles clean
python -m alladin jafar endurance --cycles 100 --seed 42

# Endurance 1000 cycles avec pannes injectées
python -m alladin jafar endurance --cycles 1000 --seed 42 \
  --provider-error-at 100,101 --stale-at 200 --graceful-stop-at 900
```

## Prochain lot recommandé : Mission Control runtime health UI

> `docs/AUTONOMY_PROGRESS.md` et `docs/IMPLEMENTATION_PLAN.md` ont été resynchronisés après les lots health/endurance. Utiliser ces versions à jour, pas les anciens passages OBSERVE-only de l'historique.

L'API GET /api/runtime/health est stable. Le frontend Mission Control
existe déjà. Le prochain lot utile est d'afficher le runtime health
dans l'UI existante (read-only) :

- runtime status badge (HEALTHY / DEGRADED / STALE / FAILED)
- last heartbeat, last cycle, last market update
- consecutive failures
- provider status
- last error

Scope minimal : ajouter le bloc runtime health à la page existante.
Ne pas refaire le frontend complet.

**Ne pas commencer avant d'avoir lu ce fichier et vérifié que pytest passe.**
