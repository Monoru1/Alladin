# HANDOFF CODEX — ALLADIN

## Checkpoint Codex Phase 2 — 2026-10-01

Commit de correction `ed311b4` pousse sur `origin/main` apres le HEAD Claude `c52113b`.
Validation : 280 tests passes, 3 ignores ; Ruff et mypy propres ; JavaScript `node --check` OK ; `git diff --check` propre. Aucun ordre MT5 ni Binance envoye.

- Backtest : signal a la cloture de i, fill a l'open de i+1 ; prix executables bid/ask ; gaps au prix d'ouverture ; politique intrabar explicite `CONSERVATIVE_STOP_FIRST` ou `EXCLUDE_AMBIGUOUS` ; pas de MFE/MAE apres une sortie intrabar.
- R : `loss_per_lot` est une perte totale au stop pour un lot ; risque initial fige a l'ouverture ; commission, slippage et swap comptabilises une fois ; spread deja porte par les prix executables.
- BTC : klines fermees seulement, decision H1 confirmee par M15/M5 clotures et recentes, identites/positions conservees entre evaluations, sizing borne par pas/minimum/notionnel/capital, short etiquete `SYNTHETIC_PAPER_SHORT`.
- DEMO : seules les versions `APPROVED` passent le registre ; PAPER demande `research_paper: true` ou une approbation ; transitions Research sequentielles ; OOS exclu du classement automatique.
- Mission Control : `/health` expose le dernier run officiel et son etat ; HTML externe filtre avant insertion ; polling par flux sans chevauchement. API toujours en lecture seule.
- MT5 DEMO : `sync --system-test` a reconcilie ticket EURUSD BUY `58707143622`, trade `2924d4e184ca`, deal `58325810043` ; sortie SL `1.13113` le 2026-10-01 06:40:43 UTC ; commission 0, swap 0, P&L net -1,77 EUR, R journalise -1,003 ; aucune position ouverte.
- BTC Three-Way PAPER sur donnees mock : exactement 3 definitions, toutes `NO_ENTRY` avec raison pour le snapshot teste (regime LOW_VOLATILITY / prix milieu de range). Aucune entree forcee.

Limites restantes : experiment BTC conserve son etat dans une instance de moteur, sans persistance apres redemarrage du processus ; aucun essai Binance Testnet live ; provenance du modele de cout reste dans les parametres d'experience sans schema impose ; le controle de hash du code approuve n'est pas automatise. Les sections historiques ci-dessous decrivent l'etat Claude avant ce checkpoint et peuvent etre perimees.

Lire d'abord `README.md`. Ne PAS reconstruire le projet : le MVP existe et est teste.
Regle absolue : **DEMO uniquement, argent reel interdit, fail closed**. Ne jamais lancer RUN-001 officiel ni d'ordre sans confirmation explicite de l'utilisateur.

## 1. Etat Git

| | |
|---|---|
| HEAD de depart de cette session | `496751b` docs: update HANDOFF_CODEX |
| HEAD actuel | `0927045` test: add observability and robustness tests |
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
| F. Mission Control cockpit | **DONE** | Dashboard complet avec BTC cards, tiered polling |
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
| X. BacktestRunner | **DONE** | `research/backtest.py` anti-lookahead strict |
| Y. R Analytics | **DONE** | `research/r_analytics.py` normalize en R-multiple |
| Z. Dataset Splits | **DONE** | `research/splits.py` TRAIN/VAL/OOS/DEMO + purge/embargo |
| AA. Strategy Scorecard | **DONE** | `research/scorecard.py` 20+ metriques par config |
| AB. Strategy Router perf | **DONE** | `strategies/performance.py` OOS/DEMO only, jamais TRAIN |
| AC. BTC Adapter | **DONE** | `brokers/crypto.py` CryptoDataProvider + Mock + Binance testnet |
| AD. Three-Way Experiment | **DONE** | `research/btc_experiment.py` 3 hypotheses, NO_ENTRY ok |
| AE. SNN BTC Research | **DONE** | `docs/SNN_BTC_RESEARCH.md` protocole 9 niveaux |
| AF. Mission Control v2 | **DONE** | BTC cards, tiered polling, N/A safe, read-only |
| AG. Observability tests | **DONE** | 5 nouveaux tests robustesse API |

### Items restants (prochaine session)

| Item | Statut | Detail |
|---|---|---|
| SYSTEM-TEST reconciliation | **PENDING** | `python -m alladin sync --system-test` |
| MQL5 Research | **NOT STARTED** | Extraire hypotheses depuis mql5.com/fr/code/mt5 |
| Research Lab drill-down | **NOT STARTED** | SOURCE->FINDING->HYPOTHESIS->RESULT chain |
| Regime Engine confidence | **NOT STARTED** | Multi-indicateur, pas mono-classif |
| BTC live data integration | **NOT STARTED** | Connecter BinancePublicProvider a l'engine |
| SNN Phase A baselines | **NOT STARTED** | Ridge/RF/LSTM sur BTCUSDT (voir SNN_BTC_RESEARCH.md) |

## 3. Commits de cette session (iteration 3)

```
0927045  test: add observability and robustness tests for Mission Control API
e44d715  feat: Mission Control dashboard with BTC Three-Way cards and tiered polling
c7f3784  docs: add SNN BTC research protocol
19902b0  feat: BTC adapter, Three-Way Experiment, ResearchPerformanceProvider
85364ee  feat: BacktestRunner, R Analytics, dataset splits, Strategy Scorecard
```

## 4. Architecture ajoutee (iteration 3)

### `research/r_analytics.py` (nouveau)
- `RMetrics` dataclass : realized_r, planned_rr, mfe_r, mae_r, spread_cost_r, holding_time
- `compute_r()` : 1R = |entry - SL| * loss_per_lot * volume
- Gestion complete des couts (spread, commission, swap)

### `research/splits.py` (nouveau)
- `SplitName = Literal["TRAIN", "VALIDATION", "OUT_OF_SAMPLE", "DEMO"]`
- `split_bars()` : purge/embargo pre-reserve, JAMAIS de random shuffle
- `DatasetSplitConfig` : proportions + purge_bars + embargo_bars configurables

### `research/backtest.py` (nouveau)
- `BacktestRunner.run()` : anti-lookahead strict (`bars[:i+1]` only)
- `VirtualPosition` : MFE/MAE tracking, SL/TP exit detection
- `BacktestResult` : win_rate, expectancy_r, profit_factor, max_drawdown_r
- `run_splits()` : backtest par segment independant
- `to_experiment_result()` : conversion vers ExperimentResult

### `research/scorecard.py` (nouveau)
- `ScorecardEntry` : 20+ metriques per strategy/version/symbol/tf/regime/split
- `MINIMUM_TRADES = 30` : en dessous = INSUFFICIENT_SAMPLE
- `build_scorecard()` + `build_scorecards_by_regime()`

### `strategies/performance.py` (nouveau)
- `ResearchPerformanceProvider` implements `PerformanceProvider` protocol
- `_TRUSTED_SPLITS = ("DEMO", "OUT_OF_SAMPLE")` : TRAIN/VAL exclus
- Priorite : DEMO > OOS. Absence = None (neutre, pas negatif)

### `brokers/crypto.py` (nouveau)
- `CryptoDataProvider` ABC : klines(), ticker(), instrument(), now()
- `CryptoMockProvider` : mock deterministe, spread_bps configurable
- `BinancePublicProvider` : REST public, testnet=True par defaut, urllib only
- `CryptoTick.spread_bps` : spread en basis points (pas forex pips)
- `CryptoInstrument` : tick_size, lot_size, min_notional

### `research/btc_experiment.py` (nouveau)
- `BTCThreeWayEngine` : exactement 3 experiments (TREND/BREAKOUT/MEAN_REVERSION)
- NO_ENTRY si le regime ne qualifie pas — pas de trades forces
- `BTCExperimentPosition` : MFE/MAE en R, PnL en USDT et R
- Position sizing : `risk_amount = notional * risk_pct / 100`, `size_btc = risk_amount / sl_dist`
- Fee model : `FEE_BPS = 10.0` (0.1% par trade)

### `docs/SNN_BTC_RESEARCH.md` (nouveau)
- Protocole scientifique : 9 niveaux (Ridge -> SNN + R-STDP + metabolic)
- Hypothese falsifiable : le connectome peut ne rien apporter
- Controls : degree-preserving rewired, ER random, small-world
- Anti-overfitting : splits chrono, purge/embargo, 10+ seeds, report ALL

### `api/app.py` (modifie)
- `/api/btc/experiments` : endpoint read-only BTC experiment status

### `api/static/index.html` (reecrit)
- Top bar : MODE, broker, daemon, heartbeat badges
- ROW 1 : Account metrics (Balance, Equity, Floating P&L, DD, Risk)
- ROW 2 : BTC THREE-WAY EXPERIMENT (3 cartes)
- ROW 3 : Live positions + Risk map
- ROW 4 : Opportunity Radar (Why / Why not)
- ROW 5 : Brain trace + Market activity
- Tiered polling : FAST(2s) / MEDIUM(8s) / SLOW(30s)
- In-flight dedup, N/A pour donnees manquantes

## 5. Etat des tests

```
pytest:   256 passed, 3 skipped
ruff:     All checks passed!
mypy:     Success: no issues found
```

Tests ajoutes cette session :
- `tests/test_backtest.py` : 23 tests (R analytics, splits, backtest runner, scorecard)
- `tests/test_btc_experiment.py` : 19 tests (crypto provider, 3-way engine, risk profile)
- `tests/test_api.py` : +5 tests observabilite/robustesse

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
git log --oneline -10
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

**A2 — BTC live data**
Connecter `BinancePublicProvider` (testnet) dans l'OrchestrationEngine pour alimenter les 3 experiments BTC en temps reel.

**A3 — Research Lab drill-down**
Chain SOURCE->FINDING->HYPOTHESIS->EXPERIMENT->RESULT dans l'UI.

### PRIORITE B
**B1 — SNN Phase A baselines**
Implementer Ridge/RF/LSTM baselines sur BTCUSDT (voir `docs/SNN_BTC_RESEARCH.md`).

**B2 — MQL5 research**
Etudier mql5.com/fr/code/mt5, extraire hypotheses, creer ResearchSource entries.

**B3 — Regime Engine v2**
Multi-indicateur avec confidence, pas mono-classif.

## 9. Points d'attention pour Codex

- `BacktestRunner` passe `bars[:i+1]` a la strategie — anti-lookahead strict, teste explicitement
- `ResearchPerformanceProvider` n'utilise JAMAIS TRAIN/VALIDATION — seulement DEMO et OOS
- `BTCThreeWayEngine` cree exactement 3 experiments mais ne force PAS 3 trades — NO_ENTRY est valide
- `BinancePublicProvider` default `testnet=True` — ne JAMAIS changer sans confirmation utilisateur
- `CryptoDataProvider` est separe de `BrokerAdapter` — ne pas contaminer le core MT5
- `split_bars()` pre-reserve le budget purge/embargo — jamais de random shuffle
- `ScorecardEntry` requiert minimum 30 trades sinon INSUFFICIENT_SAMPLE
- Tiered polling dans index.html : FAST(2s), MEDIUM(8s), SLOW(30s) — ne pas tout mettre en FAST
- Les apostrophes dans les heredocs bash plantent sur ce systeme — utiliser Python pour ecrire des fichiers complexes
- Fichiers CRLF sur Windows — toujours lire/ecrire en binaire avec replace
