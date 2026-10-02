# Strategy — FX Carry

## Hypothèse
Le carry exploite les différences de rendement/taux entre devises. La littérature documente une prédictibilité et des rendements historiques, mais aussi des pertes abruptes lors de hausses de volatilité.

## Alladin
Cette famille est pertinente surtout pour FX et nécessite des données de swap/financement fiables du broker.

Signal conceptuel :
```math
carry_{A/B} \approx yield_A-yield_B
```

Le signal réel doit utiliser les coûts/rollover effectivement applicables à l'instrument.

## Risque majeur
Crash risk / negative skew / changement de régime de volatilité. Le carry ne doit pas être traité comme revenu gratuit.

## Intérêt SNN
Feature lente de contexte macro/financement, à combiner avec momentum, volatilité et stress plutôt qu'action autonome obligatoire.
