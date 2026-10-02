# DECISION-002 — Réutiliser avant de réécrire

**Date :** 2026-10-02  
**Statut :** ADOPTED

## Décision
Ne pas réécrire Alladin de zéro.

Réutiliser tout composant compatible avec l'architecture cible : MT5Broker, RiskEngine, ChallengeWatchdog, journal, replay, modes, tests, cockpit et infrastructure.

Supprimer/remplacer seulement ce qui entre réellement en conflit avec SNN-first.

## Raison
Préserver le travail validé, réduire les régressions et concentrer l'effort sur les changements à valeur scientifique.
