# DECISION-017 — La vérité marché est causale, archivée et rejouable

**Date :** 2026-10-03  
**Statut :** ADOPTED

## Contexte
Les décisions, backtests, futurs Brains et expériences ne sont comparables que si chacun voit exactement l'information disponible au moment de la décision. Les lots C/D ont déjà introduit `available_at`, provenance, manifests de cycle, fingerprints et replay sans fetch broker.

## Décision
Toute décision/recherche sérieuse doit être fondée sur une vue causale du marché. Les entrées utilisées par un cycle sont archivées avec leur disponibilité/provenance et un fingerprint déterministe. Un replay historique ne peut pas aller chercher silencieusement des données actuelles auprès du broker pour combler le passé.

Les doublons identiques peuvent être idempotents ; les conflits doivent rester visibles. Une archive historique qui ne permet pas de reconstruire exactement le contexte causal ne doit pas prétendre offrir un replay exact.

## Invariants
- pas de future data dans une décision historique ;
- pas de broker fetch caché pour compléter un replay causal ;
- dataset/cycle fingerprintable et traçable ;
- divergence ou donnée requise manquante = échec explicite ;
- les futurs Brains/SNN respectent les mêmes cutoffs.

## Conséquences
Le replay est une infrastructure de vérité et d'audit, pas une simple animation UI. Toute optimisation qui casserait cette causalité est refusée.

## Documents/code concernés
`docs/IMPLEMENTATION_PLAN.md`, archive marché, ReplayContext, journal, research bench.
