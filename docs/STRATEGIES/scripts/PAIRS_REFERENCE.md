# Reference Script — Pairs

```python
# beta, center and scale are fitted on TRAIN / rolling past only
spread = y[t] - beta * x[t]
z = (spread - center) / max(scale, eps)

if z >= entry_z:
    signal = SHORT_SPREAD
elif z <= -entry_z:
    signal = LONG_SPREAD
elif abs(z) <= exit_z:
    signal = FLAT
```

L'exécution à deux jambes doit être simulée avec coûts, synchronisation et risque de legging.
