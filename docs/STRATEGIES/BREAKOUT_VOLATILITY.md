# Strategy — Breakout / Volatility Expansion

## Hypothèse
Une sortie d'une zone de compression/range peut annoncer une phase de déplacement persistant.

Exemple causal :
```math
upper_t=max(High_{t-L:t-1})
```
```math
lower_t=min(Low_{t-L:t-1})
```

```text
price > upper + buffer -> candidate LONG
price < lower - buffer -> candidate SHORT
otherwise -> FLAT
```

Le buffer peut être normalisé par ATR/spread.

## Intérêt SNN
Très compatible avec l'encodage événementiel : le franchissement devient naturellement un burst sensoriel.

## Risques
False breakouts, spreads lors d'annonces, slippage, chasse aux niveaux, paramètres sur-optimisés.
