# Strategy Source Map — Wide Research

## Source hierarchy

### Tier A — research / reproducible evidence
Academic papers, working papers, documented datasets. Used for hypotheses and long-horizon evidence.

### Tier B — platform engineering
MQL5 CodeBase and MQL5 Articles. Valuable for concrete EA implementations, Strategy Tester patterns, indicators and MT5-specific pitfalls. Code is not assumed profitable.

### Tier C — broker education / platform research
Exness, Deriv, FxPro and similar. Useful for strategy taxonomy, broker-specific microstructure, instruments, swaps, execution and risk. Treat performance/marketing claims cautiously.

### Tier D — open community code
TradingView open-source Pine, GitHub repositories, public MQL5 code. Useful for implementation ideas and ablations. Must audit licensing, repainting, look-ahead and costs.

### Tier E — community experience
Reddit / public social discussions. Useful for failure modes, practitioner heuristics and new hypotheses. Anecdotes are not evidence of edge.

## Findings from expanded pass — 2026-10-02

### MQL5 / MetaTrader
- Official CodeBase exposes MT5 Expert Advisor source code ranging from simple MA systems to more complex EAs and explicitly recommends Strategy Tester validation.
- Recent MQL5 articles implement ensemble mean reversion, consolidation/Asian-session breakout and dynamic multi-pair momentum/mean-reversion systems.
- These are high-value implementation references for Alladin because the current execution environment is MT5.

### Broker material
- Exness educational material covers trend, range, breakout and breakout-retest; this is useful for generating rule families, not proof of profitability.
- Deriv publishes risk-management material, technical-analysis automation with Deriv Bot, and platform-specific automated/derived products.
- Deriv's material reinforces an important portability constraint: products and contract semantics can differ materially from ordinary spot/CFD FX, so a BrokerAdapter must expose capabilities rather than pretending all markets are identical.
- FxPro material explicitly contrasts mean reversion and trend following and highlights regime dependence.

### TradingView
Open-source Pine strategies exist for:
- trend-vs-mean-reversion classification;
- hybrid trend + mean reversion;
- VWAP adaptive trend/reversion;
- multi-MA trend templates;
- dynamic RSI mean reversion.

These are candidate implementations to reverse-engineer conceptually. Do not copy code without checking TradingView House Rules/license constraints.

### Reddit / practitioner discussions
Recurring useful themes:
- OOS is necessary but not sufficient when the live volatility regime differs from the backtest;
- spread/liquidity can destroy apparently attractive mean-reversion candidates;
- combining trend and mean-reversion components is a common practitioner hypothesis;
- reported Sharpe/win-rate numbers are self-reported and must never enter Alladin as evidence without reproduction.

## Research rule

Every discovered strategy enters a funnel:

```text
DISCOVER
 -> classify source
 -> extract exact rules
 -> check license
 -> inspect look-ahead/repainting
 -> implement clean-room reference if needed
 -> unit tests
 -> replay
 -> TRAIN
 -> VALIDATION
 -> OOS
 -> PAPER
 -> DEMO
 -> retain / reject
```

No popularity score, broker article, Reddit post or backtest screenshot can skip the funnel.

## Sources indexed in this pass

MQL5:
- MQL5 CodeBase — Expert Advisors for MT5
- Simple Mean Reversion Trading Strategy
- Ensemble Mean Reverting Strategy
- Asian Breakout EA
- Consolidation Range Breakout EA
- Dynamic Multi-Pair EA: Mean Reversion and Momentum

Broker/platform:
- Exness Insights — beginner forex strategies; breakout; advanced breakout/retest
- Deriv Blog — forex risk management; Deriv Bot technical analysis; bot construction; Tactical Indices
- FxPro Education — mean reversion guide

Community/open source:
- TradingView open-source strategy pages for trend/reversion/hybrid/VWAP/RSI templates
- Reddit r/algotrading discussions on mean reversion, regime mismatch and live survivability

## Future source expansion

Search in later passes:
- additional GitHub repos with explicit permissive licenses;
- MetaTrader Market demos/descriptions (ideas only where source unavailable);
- QuantConnect community/research;
- Backtrader/LEAN examples;
- broker execution specifications and symbol metadata;
- X posts only when independently reproducible or useful as hypothesis leads;
- published competition/quant research.

The library is intentionally extensible.
