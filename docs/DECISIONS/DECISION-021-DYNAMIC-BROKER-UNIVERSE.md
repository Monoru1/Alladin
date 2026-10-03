# DECISION-021 — Découverte broker large, univers tradable dynamique et filtré

**Date :** 2026-10-03  
**Statut :** ADOPTED

## Contexte
MT5 peut exposer des milliers de symboles alors que l'univers Alladin courant n'en classe qu'une fraction. L'objectif n'est pas de hardcoder FX/métaux ni de trader tout ce que le broker expose.

## Décision
Séparer explicitement :
```text
Broker discovery
    -> asset classification
    -> capabilities / market metadata
    -> eligibility
    -> dynamic workspace universe
    -> opportunity selection
```

« Accessible chez le broker » ne signifie jamais « éligible » ni « à trader ».

La classification et les capabilities doivent permettre d'étendre progressivement Alladin/Jafar à de nouvelles classes d'actifs sans liste centrale rigide.

## Invariants
- aucun instrument n'est tradé uniquement parce qu'il a été découvert ;
- asset class/session/contract/tick/volume/capabilities doivent être connus suffisamment pour l'action demandée ;
- données insuffisantes ou ambiguës = inéligible/fail-closed ;
- les univers sont workspace-scopés ;
- l'accès large au marché ne contourne jamais RiskEngine ni les politiques de portefeuille.

## Conséquences
Le scanner peut viser une couverture broker beaucoup plus large, puis filtrer fortement. Les workspaces peuvent partager la mécanique de découverte tout en gardant leurs politiques d'éligibilité propres.

## Documents/code concernés
market discovery/classification, `BrokerCapabilities`, workspace universe, scanner.
