# OFFLINE LOTS — TERMINAL ACCEPTANCE GATE

Status: PRE-VALIDATION. This document does not certify tests, broker compatibility or trading readiness.

## Scope

New offline modules under `src/alladin/challenge/`:

- `paper_risk_reservations.py` — isolated SQLite reservation ledger
- `paper_reconciliation.py` — deterministic closed-fill replay
- `economic_intelligence.py` — causal macro surprises
- `official_signals.py` — configured HTTPS origin checks
- `market_observatory.py` — read-only chart data contract
- `offline_diagnostics.py` — diagnostic-only composition
- `performance_research.py` — research-only net closed-trade metrics

These modules are NOT wired into live execution, the actual Mission Control UI, MT5, Binance, or SNN-X. The official source check is hostname allowlisting, not cryptographic publisher identity. The market observatory is a data contract, not a rendered chart. Do not claim either as complete.

## Windows terminal synchronization

1. `cd $HOME\Alladin`
2. `git status -sb` — inspect any local edits before pulling
3. `git fetch origin`
4. `git log --oneline -8 origin/main`
5. Only with clean/understood working tree: `git pull --ff-only origin main`
6. Activate existing venv: `.\.venv\Scripts\Activate.ps1`

## Software gate — execute BEFORE connecting MT5

```powershell
python -m pytest -o addopts='' -q tests/test_paper_risk_reservations.py tests/test_paper_reconciliation.py tests/test_economic_intelligence.py tests/test_official_signals.py tests/test_market_observatory.py tests/test_offline_diagnostics.py tests/test_performance_research.py
python -m pytest -o addopts='' -q
python -m ruff check src/alladin tests
python -m mypy src/alladin
```

Stop on any failure. Capture full traceback and environment versions. The last *previously reported* green baseline was 1501 passed / 3 skipped; these additions are untested.

## Required review before runtime integration

- Atomic reservations: process-level concurrency, SQLite lock/timeout, crash and retry, idempotency, lower limit, scope/currency/account isolation, never release on unknown broker outcome. Confirm exposure is counted exactly once, including existing positions.
- PAPER reconciliation: actual journal event shape, broker-specific contract sizing, partial closes, fees, reversals, hedged positions, short positions, event completeness, restarts and duplicates. Integer unit conventions in the prototype are NOT broker-ready.
- Economic intelligence: release publication versus receipt, consensus pre-release timestamp, revision/vintage, source provenance and units. Current surprise is a scalar difference, not a trade signal.
- Official publications: approved domains, actual URL provenance, redirect policies, source publication IDs, text hash, edits/deletions and dedup. A valid hostname does not prove authenticity or factual truth.
- Market Observatory: OHLCV data feed, candle finality, timezone, symbol mapping, chart JS rendering, performance and offline fallback. No chart UI is shipped in this lot.
- Diagnostics: explicit adapter mapping from existing event-sourced journal and runtime, read-only endpoints, no accidental execution permission or risk-gate bypass.
- Regression: verify Jafar, SNN-X, challenge watchdog, RiskEngine, journal replay and prior dashboards.

## MT5 DEMO gate (later)

Only after software tests pass and the user explicitly authorizes DEMO tests: inspect terminal/account configuration, account currency and symbol specifications; reconcile orders/fills/SL/TP, partial closes, broker rejects, restart/reconnect and trading session boundaries. Never infer LIVE readiness from DEMO.

## Definition of done

A module is only **implemented** when code exists; **validated** after automated checks and review; **integrated** after journal/runtime/UI adapters are wired and regression-tested; **broker-validated** only after the terminal evidence is collected. No profitability or production claims without actual evidence.
