# DECISION-015 — Broker et compte sont des bindings, pas l'identité d'un workspace

**Date :** 2026-10-03  
**Statut :** ADOPTED

## Contexte

Jafar doit pouvoir utiliser un broker MT5 exposant de la crypto (par exemple un broker tel qu'Exness si ses capacités réelles sont compatibles), mais l'architecture ne doit pas devenir `Jafar = Exness`, ni `crypto = MT5`.

Alladin doit également rester multi-broker conformément à DECISION-004.

## Décision

L'accès marché/exécution passe par une abstraction de **BrokerAdapter + AccountBinding + capabilities**.

Un workspace choisit une liaison de compte/broker compatible avec ses besoins, mais cette liaison ne définit pas son identité.

Architecture cible :

```text
Workspace
   -> AccountBinding
   -> BrokerAdapter
   -> Broker / Exchange
```

Exemples autorisés conceptuellement :
- Alladin -> compte MetaQuotes-Demo -> adapter MT5 ;
- Jafar -> compte MT5 d'un broker crypto-compatible -> adapter MT5 ;
- futur Jafar -> exchange crypto natif -> adapter dédié.

## Capacités à modéliser

Les capacités doivent être explicites et vérifiables : asset classes, symbol mapping, sessions, tick/lot/contract size, min volume, margin, order types, close/modify/partial-close, commissions/funding, provenance market data, etc.

On ne suppose jamais qu'une capacité existe parce qu'un broker ou MT5 la supporte parfois.

## Crypto

Le domaine crypto peut exiger des comportements différents de FX : 24/7, maintenance exchange, spot/perpetual, maker/taker, funding, liquidation, tailles de contrat, tick sizes et marge spécifiques. Ces différences doivent être portées par les adapters/capabilities et les règles dédiées, pas par des hacks dans le core.

## LIVE

Les comptes réels peuvent être représentables dans l'architecture future, mais **LIVE reste bloqué aujourd'hui**.

Toute future activation réelle doit conserver :
- validation PAPER/DEMO ;
- RiskEngine et kill switch ;
- reconciliation ;
- auditabilité ;
- vérification des capabilities ;
- activation humaine explicite ;
- politique de promotion documentée.

Aucun raccourci broker ne peut contourner ces gates.

## Invariants

- pas de hardcode Exness dans Jafar ;
- pas de hardcode MT5 comme modèle universel ;
- adapter obligatoire entre domaine Alladin/Jafar et API propriétaire ;
- même garde-fous de risque/exécution quel que soit le broker ;
- aucune activation LIVE implicite.

## Documents/code concernés

- `docs/DECISIONS/DECISION-004-MULTI-BROKER.md`
- `docs/DECISIONS/DECISION-013-MODE-SAFETY.md`
- futur `AccountBinding` / extension `BrokerCapabilities`
