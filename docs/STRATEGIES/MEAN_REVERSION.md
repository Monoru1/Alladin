# Strategy — Mean Reversion

## Hypothèse
Après un écart extrême relativement à un état local, certains marchés reviennent vers une moyenne/valeur de court terme.

Signal candidat :
```math
z_t = \frac{P_t-\mu_t}{\sigma_t}
```

```text
z > +k -> candidate SHORT
z < -k -> candidate LONG
|z| small -> FLAT/exit
```

## Intérêt SNN
Excellent antagoniste du trend : le cerveau peut apprendre dans quels contextes persistence ou reversion domine.

## Danger principal
Une « anomalie » peut être le début d'un nouveau régime. Ne jamais moyenner une perte sans contrainte déterministe.

## Validation
Mesurer half-life empirique, stabilité du centre, coûts, queues, comportement lors des breakouts et changement de volatilité.
