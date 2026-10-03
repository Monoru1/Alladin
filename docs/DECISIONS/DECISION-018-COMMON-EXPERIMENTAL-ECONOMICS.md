# DECISION-018 — Même économie expérimentale pour classiques, contrôles et futurs Brains

**Date :** 2026-10-03  
**Statut :** ADOPTED

## Contexte
Un futur SNN ne doit pas paraître meilleur parce qu'il bénéficie d'un backtest, de coûts, d'un calcul de R ou d'un split plus favorable que les baselines.

## Décision
Les stratégies classiques, contrôles, expériences BTC et futurs Brains/SNN doivent être comparés sous un contrat expérimental commun : même dataset causal, même cutoff, même `CostModel`, même `FillRecord`, même définition économique du résultat/R et mêmes règles TRAIN/VALIDATION/OOS.

Les splits sont chronologiques avec purge/embargo lorsque requis. Le chemin OOS doit rester structurellement séparé du training.

## Invariants
- aucune voie d'évaluation spéciale favorable au SNN ;
- provenance dataset + fingerprint liés à l'expérience ;
- coûts/slippage explicités, jamais oubliés silencieusement ;
- résultats reproductibles et auditables ;
- les différences de modèle de coûts doivent être documentées plutôt que masquées.

## Conséquences
La promotion d'un nouveau Brain doit reposer sur des preuves obtenues sous les mêmes lois expérimentales que les contrôles.

## Documents/code concernés
research bench, `CostModel`, `FillRecord`, `StrategyExperiment`, splits OOS, BTCThreeWayEngine.
