# Reference Script — Breakout

```python
upper = max(high[t-L:t])
lower = min(low[t-L:t])
buffer = max(atr[t-1] * atr_buffer, spread[t] * spread_buffer)

if ask[t] > upper + buffer:
    signal = LONG
elif bid[t] < lower - buffer:
    signal = SHORT
else:
    signal = FLAT
```

Tester explicitement slippage et widening du spread.
