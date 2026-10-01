# HANDOFF CODEX — ALLADIN

Lire d'abord `README.md`. Ne PAS reconstruire le projet : le MVP existe et est teste.
Regle absolue : **DEMO uniquement, argent reel interdit, fail closed**. Ne jamais lancer RUN-001 officiel ni d'ordre sans confirmation explicite de l'utilisateur.

## 1. Etat Git

| | |
|---|---|
| HEAD de depart de cette session | `0fb2e91` docs: update HANDOFF_CODEX |
| HEAD actuel | `0e58093` feat: enrich /health endpoint |
| Branche | `main` (suit `origin/main`, pousse) |
| Working tree | propre |
| Non commite par conception | `.env`, `data/`, `.venv/`, `.claude/` |

## 2. Statut des missions

| Mission | Statut | Detail |
|---|---|---|
| A. MT5 reel valide | **DONE** | Compte DEMO MetaQuotes-Demo connecte |
| B. Univers LAB | **DONE** | `config/universes/lab.yaml` |
| C. Algo Trading guard | **DONE** | `_require_algo_trading()` |
| D. test-order / SYSTEM-TEST | **PARTIAL** | Position EURUSD 58707143622 statut inconnu |
| E. Reconciliation redemarrage | **DONE** | `sync` command |
| F. Mission Control cockpit | **DONE** | `api/app.py` + `static/index.html` |
| G. Research models | **DONE** | `research/models.py` + `research/repository.py` |
| H. MarketDataArchive | **DONE** | `market/archive.py` avec stats CLI |
| I. cycle_id / observabilite | **DONE** | Tests complets |
| J. SYSTEM-TEST vs RUN-001 | **DONE** | Isolation parfaite |
| K. RunMode daemon | **DONE** | OBSERVE/PAPER/DEMO |
| L. Opportunity model | **DONE** | `market/opportunity.py` |
| M. Research persistence | **DONE** | `ResearchRepository` SQLAlchemy/SQLite |
| N. Tests daemon/research | **DONE** | 23 tests dans `test_daemon_modes.py` |
| O. Scanner multi-timeframe | **DONE** | `TimeframeScheduler` par (symbol, tf) |
| P. Paper experiments | **DONE** | `PaperExperimentEngine` avec MFE/MAE/SL/TP |
| Q. Research Lab UI enrichi | **PARTIAL** | Pas de drill-down provenance |
| R. Opportunity Radar live | **DONE** | `/api/opportunities` branche, journal CREATED/REJECTED |
| S. Archive stats CLI | **DONE** | `alladin archive stats` + `alladin archive inspect` |
| T. Market Quality Engine | **DONE** | `market/quality.py`, RejectCode machine-readable |
| U. Strategy Lifecycle | **DONE** | `check_lifecycle()` dans StrategyRegistry |
| V. /api/opportunities endpoint | **DONE** | Retourne qualified + filtered par run/cycle |
| W. /health enrichi | **DONE** | `last_cycle_at` ajoute |

### Items restants (prochaine session)

| Item | Statut | Detail |
|---|---|---|
| MQL5 Research | **NOT STARTED** | Extraire hypotheses depuis mql5.com/fr/code/mt5 |
| Strategy Research Matrix | **NOT STARTED** | StrategyHypothesis x Symbol x TF x Regime |
| Anti-overfitting splits | **NOT STARTED** | TRAIN/VAL/OOS/DEMO |
| Regime Engine confidence | **NOT STARTED** | Multi-indicateur, pas mono-classif |
| Position analytics R | **PARTIAL** | MAE/MFE en pips existe, pas en R-multiple |
| Research Lab drill-down | **NOT STARTED** | SOURCE->FINDING->HYPOTHESIS->RESULT chain |
| SYSTEM-TEST reconciliation | **PENDING** | `python -m alladin sync --system-test` |
| Backtest runner | **NOT STARTED** | `research/backtest.py` sur MarketDataArchive |

## 3. Commits de cette session

```
0e58093  feat: enrich /health endpoint with last_cycle_at
8e7d6df  feat: add /api/opportunities endpoint
5a85d32  feat: strategy lifecycle enforcement via check_lifecycle()
d806d28  feat: PaperExperimentEngine - simulate trades without real orders
c09be30  feat: add MarketQualityEngine with machine-readable RejectCodes
ce2113c  feat: add TimeframeScheduler for multi-timeframe caching
3c620e9  feat: add archive stats/inspect CLI commands
555648a  feat: branch Opportunity model into real pipeline
```

## 4. Architecture ajoutee

### `market/opportunity.py`
- `OpportunityStatus` + `Opportunity` Pydantic model
- `to_journal()` excluant les champs lourds

### `orchestration/engine.py`
- `_build_opportunities()` : ScanCandidate -> Opportunity, journalise CREATED/REJECTED

### `market/scanner.py`
- `TimeframeScheduler` : cache par (symbol, tf), intervalles configurables
- M5=1, M15=2, H1=4, H4=12, D1=48 cycles entre rechargements

### `market/quality.py` (nouveau)
- `RejectCode` StrEnum machine-readable (15 codes)
- `QualityReport` avec codes + raisons humaines separees
- `MarketQualityEngine.evaluate()` pipeline de pre-filtres

### `market/paper.py` (nouveau)
- `PaperPosition` avec MFE/MAE, detection SL/TP, close()
- `PaperExperimentEngine` : open, tick_all, stats

### `strategies/registry.py`
- `check_lifecycle(approved_ids, strict=False)` : enforce APPROVED

### `api/app.py`
- `/api/opportunities` : qualified + filtered par run/cycle
- `/health` : ajoute `last_cycle_at`

### `cli.py`
- `alladin archive stats`
- `alladin archive inspect <cycle_id>`

## 5. Etat des tests

```
pytest:   209 passed, 3 skipped
ruff:     All checks passed!
mypy:     Success: no issues found
```

## 6. Etat MT5 / SYSTEM-TEST-001

**Derniere info connue (session 2026-09-30) :**
- Terminal MT5 connecte, compte DEMO MetaQuotes-Demo, balance 100 000 EUR
- Position EURUSD BUY 0.01 lot, ticket 58707143622
  - Entry 1.13313 | SL 1.13113 | TP 1.13713
  - Statut : **INCONNU** — peut etre ouvert, SL/TP atteint, ou expire
  - A reconcilier via `python -m alladin sync --system-test`

**A ne jamais faire :**
- Fermer la position 58707143622 manuellement
- Lancer RUN-001 officiel
- Envoyer un ordre sans EXECUTE explicite

## 7. Commandes de reprise

```bash
cd ~/Alladin
git log --oneline -5
python -m pytest -o addopts="" tests
python -m ruff check src tests && python -m mypy src
python -m alladin mt5 status
python -m alladin sync --system-test
python -m alladin archive stats
python -m alladin run --broker mt5 --mode OBSERVE --cycles 1
python -m alladin serve --broker mt5 --port 8001
```

## 8. Prochaines priorites

### PRIORITE A
**A1 — SYSTEM-TEST reconciliation**
```bash
python -m alladin sync --system-test
```

**A2 — Backtest runner**
Creer `research/backtest.py` avec runner sur `MarketDataArchive`.
`StrategyExperiment` + `ExperimentResult` existent, il manque le moteur.

**A3 — R-multiple analytics**
Ajouter `realized_R`, `planned_RR`, `mfe_R`, `mae_R` dans les `TradeRecord`.

### PRIORITE B
**B1 — Research Lab drill-down**
Chain SOURCE->FINDING->HYPOTHESIS->EXPERIMENT->RESULT dans l'UI.

**B2 — MQL5 research**
Etudier mql5.com/fr/code/mt5, extraire hypotheses, creer ResearchSource entries.

**B3 — Anti-overfitting**
TRAIN/VALIDATION/OOS/DEMO splits dans ResearchExperiment.

## 9. Points d'attention pour Codex

- `TimeframeScheduler` cache par `(symbol, tf)` — ne pas faire de cache global par `tf` seul
- `PaperExperimentEngine` n'est pas integre dans l'OrchestrationEngine (il faut l'appeler manuellement)
- `check_lifecycle()` ne bloque pas automatiquement : appeler avec `strict=True` pour enforcer
- `/api/opportunities` lit les events journal, pas un store dedie
- Les apostrophes dans les heredocs bash plantent sur ce systeme — utiliser Python pour ecrire des fichiers complexes
- Fichiers CRLF sur Windows — toujours lire/ecrire en binaire avec replace
