# DECISION-022 — Strategy Harvester : provenance, licence et clean-room avant expérimentation

**Date :** 2026-10-03  
**Statut :** ADOPTED

## Contexte
Alladin doit pouvoir apprendre de nombreuses sources de stratégies et d'idées (littérature, MQL5, brokers, GitHub, TradingView, communautés, etc.) sans transformer du code externe en voie d'exécution ni perdre la provenance/licence.

## Décision
Le Strategy Harvester est une chaîne de recherche, pas un mécanisme d'installation automatique de robots.

Pipeline cible :
```text
discover
 -> provenance / licence / source confidence
 -> formalize rules
 -> lookahead / repaint audit
 -> clean-room reimplementation when required
 -> unit tests
 -> causal replay
 -> TRAIN / VALIDATION / OOS
 -> cost / regime / robustness stress
 -> PAPER / DEMO
 -> keep / modify / reject
 -> strategy library / optional Brain features
```

Le système respecte les ToS, licences et restrictions de source. Il ne copie pas silencieusement du code propriétaire/copyrighté. Un script externe ne reçoit jamais un accès direct à `ExecutionService`.

## Invariants
- provenance conservée ;
- licence/usage vérifiés avant intégration ;
- aucune stratégie promue sur simple backtest favorable ;
- détection lookahead/repaint obligatoire quand pertinente ;
- expérimentation sous DECISION-017/018 ;
- PAPER/DEMO avant toute future éligibilité réelle ;
- code externe non fiable isolé du runtime critique.

## Documents/code concernés
`docs/DECISIONS/DECISION-005-STRATEGY-LAB.md`, `docs/STRATEGIES/`, future Strategy Harvester.
