# Strategy — Pairs / Statistical Arbitrage

## Hypothèse
Deux instruments historiquement liés peuvent diverger temporairement puis converger.

Gatev, Goetzmann & Rouwenhorst ont documenté une règle de pairs trading sur actions historiques, tout en signalant qu'une partie des profits peut venir d'effets de microstructure.

## Pipeline
1. univers liquide ;
2. normalisation ;
3. sélection de paires sur TRAIN ;
4. test de relation/stabilité ;
5. spread ;
6. z-score ;
7. entrée divergence ;
8. sortie convergence/time-stop/invalidité.

Exemple :
```math
spread_t = y_t - \beta x_t
```
```math
z_t=(spread_t-\mu)/\sigma
```

## Intérêt SNN
Entrée relative particulièrement intéressante : le réseau observe une relation entre instruments plutôt qu'un prix isolé.

## Risques
Rupture structurelle, faux pairs, coûts doubles, synchronisation, latence, short/financement, data snooping.
