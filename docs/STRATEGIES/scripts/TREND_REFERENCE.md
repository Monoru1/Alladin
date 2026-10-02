# Reference Script — Trend

Pseudo-code :
```python
past_return = close[t-1] / close[t-1-L] - 1
vol = realized_volatility(returns_up_to_t_minus_1)
score = past_return / max(vol, eps)

if score > threshold:
    signal = LONG
elif score < -threshold:
    signal = SHORT
else:
    signal = FLAT

return Signal(signal, score, strategy="TSMOM")
```

Interdit : utiliser `close[t]` avant sa clôture si le test suppose une décision au début de la barre.
