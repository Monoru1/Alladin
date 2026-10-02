# DECISION-004 — Multi-instruments et broker-agnostic

**Date :** 2026-10-02  
**Statut :** ADOPTED

## Décision
Alladin n'est plus conçu autour de BTC ni d'une paire unique. Le cerveau reçoit un format marché canonique normalisé.

MT5 est le premier environnement d'exécution. Binance, Deriv, Exness et autres sont des intégrations futures à vérifier individuellement.

## Architecture
```text
Broker/Exchange Adapter -> Canonical Market Event -> Normalizer -> Encoder -> SNN
```

Chaque adapter doit annoncer ses capacités réelles. Aucun order book ou type d'exécution ne doit être inventé pour uniformiser artificiellement les plateformes.
