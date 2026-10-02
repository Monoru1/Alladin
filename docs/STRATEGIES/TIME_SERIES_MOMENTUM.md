# Strategy — Time-Series Momentum / Trend Following

## Hypothèse
La direction des rendements passés contient parfois de l'information sur la persistance future d'un mouvement.

La littérature documente cette famille sur futures/forwards et plusieurs classes d'actifs. Cela ne prouve pas qu'une implémentation courte fréquence sur le broker Alladin sera rentable.

## Signal minimal
```math
s_t = sign(P_t / P_{t-L} - 1)
```

Variante normalisée :
```math
z_t = \frac{r_{t,L}}{\sigma_{t,L}}
```

Action candidate :
```text
z > threshold  -> LONG
z < -threshold -> SHORT
otherwise       -> FLAT
```

## Intérêt SNN
- baseline directionnelle ;
- canal sensoriel « persistence » ;
- contre-factuel face au cerveau ;
- label de contexte, jamais vérité.

## Risques
Whipsaw en range, coûts élevés si horizon trop court, crowding/corrélations, paramètres sensibles.

## Validation
Tester plusieurs horizons pré-enregistrés, coûts complets, walk-forward, OOS, multi-instruments et stabilité par régime.
