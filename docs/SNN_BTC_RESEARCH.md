# SNN BTC Research Protocol

## Status: PLANNING (not yet implemented)

This document defines the scientific protocol for evaluating whether a biological
connectome topology provides useful temporal market representations compared to
comparable controls.

---

## Central Hypothesis

> A real biological connectome topology (Drosophila MaleCNS / NeuPrint) provides
> a useful temporal representation of BTC market data compared to comparable
> controls of equivalent size and density.

This is a **falsifiable hypothesis**. The project must be able to conclude:
**"the connectome provides no advantage"**.

---

## Experimental Architecture

All models share:
- **SAME DATA** (BTCUSDT klines, order book, trades)
- **SAME COST MODEL** (fee_bps, slippage model)
- **SAME READOUT** (linear readout layer from reservoir/hidden state)
- **SAME RISK** (identical position sizing, SL/TP rules)
- **SAME EXECUTION** (paper/testnet only)
- **SAME SPLITS** (TRAIN/VALIDATION/OOS/DEMO chronological)

---

## Model Ladder (9 levels)

| # | Model | Purpose |
|---|-------|---------|
| 1 | Ridge Regression | Linear baseline |
| 2 | Random Forest | Non-linear baseline without temporal structure |
| 3 | Small temporal model (LSTM/GRU) | Conventional temporal baseline |
| 4 | Random reservoir (ESN) | Reservoir computing baseline |
| 5 | Degree-preserving rewired connectome | Control for degree distribution |
| 6 | Frozen biological connectome | Topology without plasticity |
| 7 | Biological SNN (LIF/AdEx) | Spiking network with bio topology |
| 8 | SNN + R-STDP | Add reward-modulated plasticity |
| 9 | SNN + R-STDP + metabolic mechanism | Full bio-inspired model |

Each level adds exactly one component. If level N doesn't improve on N-1,
there is no justification for level N+1.

---

## Connectome Source

- **Dataset**: MaleCNS from NeuPrint (Drosophila)
- **Regions of interest**:
  - Mushroom Body (MB) — hypothesized: regime classification
  - Central Complex (CX) — hypothesized: trend/navigation
  - Visual projection neurons — hypothesized: spatial input mapping

**IMPORTANT**: These functional mappings are **modeling hypotheses**, not
established neuroscience facts:
- "dopamine = gain" is a hypothesis
- "pain = noise" is a hypothesis
- "free energy" is a hypothesis
- "MB = regime" is a hypothesis
- "CX = trend" is a hypothesis

Each must be independently ablated.

---

## Neuron Models

- **LIF** (Leaky Integrate-and-Fire): simplest spiking model
- **AdEx** (Adaptive Exponential): adds adaptation currents

Selection criteria: use LIF unless AdEx demonstrably improves OOS metrics.

---

## Input Encoding

Two approaches to evaluate:
1. **Rate coding**: continuous market features encoded as firing rates
2. **Event coding**: price changes encoded as spike events

Input features:
- Price returns (multi-timeframe)
- Volume changes
- Spread
- Order book imbalance (bid/ask depth ratio)
- ATR-normalized features

Spatial mapping hypothesis: order book levels mapped to visual projection
neuron topology (needs ablation).

---

## Plasticity

- **R-STDP** (Reward-modulated Spike-Timing-Dependent Plasticity)
  - Reward signal: realized R from closed trades
  - Dopaminergic modulation: gain scaling
  - Must demonstrate improvement over frozen weights on OOS

---

## Metabolic / Free-Energy Mechanism

- Metabolic energy budget per neuron
- "Pain" signal from adverse excursion (MAE)
- Free-energy-inspired prediction error minimization
- **Swarm consensus**: multiple reservoir instances vote

All optional. Each must independently demonstrate OOS improvement.

---

## Controls

### Graph Controls
| Control | What it tests |
|---------|---------------|
| Degree-preserving rewired | Is the specific wiring important, or just the degree distribution? |
| Random graph (Erdos-Renyi) | Is any structure useful vs. random? |
| Small-world (Watts-Strogatz) | Is clustering + short paths sufficient? |

### Statistical Controls
- **Seeds**: minimum 10 random seeds per configuration
- **Sizes**: small (1K neurons), medium (10K), large (50K+)
- Complexity justified only if OOS improvement is robust across seeds

---

## Metrics

### Primary (decision metrics)
- Expectancy R (OOS)
- Sortino ratio
- Calmar ratio
- Max drawdown R

### Secondary (diagnostic)
- Predictive information
- Turnover
- Cost sensitivity
- Latency sensitivity
- Seed variance (across 10+ seeds)
- Win rate
- Profit factor

### Ablation Metrics
For each component added at each level:
- Delta expectancy R vs. previous level
- Statistical significance (paired t-test or Wilcoxon across seeds)
- Effect size

---

## Anti-Overfitting Protocol

1. **Chronological splits only** (never random shuffle)
2. **Purge/embargo** between splits
3. **No hyperparameter tuning on OOS**
4. **Report ALL experiments** (no cherry-picking)
5. **Seed variance** must be reported
6. **Complexity penalty**: prefer simpler model unless delta > 2 sigma

---

## Data Pipeline

```
BTCUSDT market data
    |
    v
[Feature extraction] -- same for all models
    |
    v
[Input encoding] -- rate or event coding
    |
    v
[Model] -- one of the 9 levels
    |
    v
[Linear readout]
    |
    v
[Signal: BUY/SELL/HOLD + confidence]
    |
    v
[Risk engine] -- same for all
    |
    v
[Paper execution]
    |
    v
[R analytics + scorecard]
```

---

## Implementation Phases (Future)

1. **Phase A**: Baselines (Ridge, RF, LSTM) on BTCUSDT
2. **Phase B**: Random reservoir (ESN)
3. **Phase C**: Import connectome from NeuPrint, build graph controls
4. **Phase D**: Frozen connectome reservoir
5. **Phase E**: LIF spiking network
6. **Phase F**: R-STDP plasticity
7. **Phase G**: Metabolic/free-energy extensions
8. **Phase H**: Full comparison and paper

Each phase produces a complete scorecard before proceeding.

---

## NOT in scope for this document

- Actual SNN implementation code
- Live trading
- HFT (sub-second) strategies
- Non-BTC instruments (initially)

---

*This document is a scientific protocol. It will be updated as the
research progresses, but the core principle remains: every addition
must be justified by OOS evidence, and the null result ("connectome
adds nothing") must remain a valid conclusion.*
