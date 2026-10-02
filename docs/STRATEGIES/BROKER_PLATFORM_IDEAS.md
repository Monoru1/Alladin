# Broker & Platform Strategy Ideas

This file captures **ideas to test**, not broker endorsements.

## Exness-derived research candidates
Educational material emphasizes:
- trend trading;
- range trading;
- breakout;
- breakout + retest;
- momentum confirmation.

Alladin experiments:
1. breakout raw vs breakout+retest;
2. breakout with/without volume/tick-activity confirmation;
3. trend/range classifier before strategy activation.

## Deriv-derived research candidates
Material exposes:
- SMA/EMA/Bollinger/RSI/MACD blocks in Deriv Bot;
- automated rule construction;
- trend/pullback/rebound concepts;
- strong emphasis on risk, leverage, liquidity and performance review.

Alladin experiments:
1. indicator-only baseline ensemble;
2. RSI trend/pullback/rebound classifier;
3. compare derived/synthetic instruments separately from FX/CFD instruments;
4. capability-aware adapter because contract types differ.

## FxPro-derived research candidates
Mean reversion vs trend following is explicitly regime-dependent.

Alladin experiment:
```text
regime detector
  trending -> trend candidate
  ranging  -> mean-reversion candidate
  uncertain -> NO_TRADE / SNN arbitration
```

## Important
Broker education is valuable for:
- vocabulary;
- execution constraints;
- platform behavior;
- candidate rules.

It is weak evidence for expected profitability. All performance claims must be independently reproduced.
