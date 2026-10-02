# Reference Script — Mean Reversion

```python
window = prices[t-L:t]  # past only
center = robust_median(window)
scale = mad(window)
z = (price_at_decision - center) / max(scale, eps)

if z <= -entry_z:
    signal = LONG
elif z >= entry_z:
    signal = SHORT
else:
    signal = FLAT
```

Ajouter time-stop, invalidation de régime et RiskEngine externe.
