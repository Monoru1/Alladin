# External Strategy Script Audit Template

For every external script/repository:

## Identity
- Name:
- Source:
- Author:
- Publication/update date:
- Language:
- License:
- Commit/version:
- Original market/timeframe:

## Logic extraction
- Entry:
- Exit:
- Stop:
- Target:
- Position sizing:
- Session filter:
- Regime filter:
- Indicators:
- Parameters:

## Leakage audit
- Future bars?
- Centered indicators?
- Repainting?
- Same-bar impossible fills?
- Higher-timeframe leakage?
- Survivorship bias?
- Selection bias?

## Execution audit
- Bid/ask modeled?
- Spread?
- Commission?
- Slippage?
- Swap/funding?
- Partial fills?
- Latency?
- Two-leg execution risk?

## Robustness
- Parameter sensitivity:
- Multiple instruments:
- Multiple regimes:
- Walk-forward:
- OOS:
- Monte Carlo/bootstrap:
- Number of trades:
- Tail losses:

## Alladin decision
- REJECT
- REIMPLEMENT CLEANLY
- BASELINE ONLY
- SNN FEATURE CANDIDATE
- EXPERIMENT CANDIDATE

Never connect an external script directly to ExecutionService.
