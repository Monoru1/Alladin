# Community Research — Reddit / TradingView / Social

## Purpose
Community sources are hypothesis generators and failure-mode detectors.

## Reddit findings
Examples from r/algotrading show:
- self-reported mean-reversion systems can look exceptionally strong in backtests; treat numbers as unverified;
- practitioners repeatedly warn that regime mismatch can make an OOS-looking system fail live;
- spread and liquidity filtering are repeatedly reported as material in FX mean reversion;
- practitioners often pair trend/momentum with mean reversion to diversify failure modes.

### Alladin translation
Record for every experiment:
```text
training volatility distribution
validation volatility distribution
OOS volatility distribution
live/demo current distribution
distance(current_regime, training_regimes)
```

The SNN should receive regime novelty/surprise rather than blindly extrapolate.

## TradingView findings
Open-source scripts provide useful rule variants:
- previous-high/low trend test;
- trend + mean-reversion hybrid;
- VWAP trend/reversion;
- multi-MA trend templates;
- RSI mean-reversion with trend filter.

### Audit rule
A visible Strategy Tester equity curve is not evidence. Rebuild the logic in Alladin's replay environment using our costs and causal timing.

## X / social networks
Treat short-form claims as leads only:
1. capture exact rule;
2. locate code/data if possible;
3. reproduce;
4. discard claim if not reproducible.

Popularity/follower count is never a model-selection metric.
