# DECISION-020 — Adaptation rapide en production, apprentissage durable hors chemin critique

**Date :** 2026-10-03  
**Statut :** ADOPTED

## Contexte
Alladin doit être autonome et adaptatif sans permettre à une perte, un bruit de marché ou un reward mal spécifié de réécrire directement le cerveau actif.

## Décision
Séparer deux temporalités :

1. **boucle rapide de production** : un Brain promu, versionné et gelé observe, propose, passe par RiskEngine, exécution et monitoring ;
2. **boucle lente d'apprentissage/promotion** : snapshots immuables, replay causal, entraînement/plasticité, validation, OOS et promotion contrôlée.

Les pertes/outcomes alimentent la recherche et l'apprentissage, mais ne modifient pas arbitrairement les poids actifs en production.

La promotion d'un nouveau Brain/checkpoint doit être atomique, versionnée, réversible et auditable.

## Invariants
- Brain actif identifiable par version/checkpoint ;
- aucune auto-réécriture incontrôlée du modèle actif ;
- rollback possible ;
- mêmes règles causales/OOS que DECISION-017/018 ;
- RiskEngine, kill switch, audit et séparation Brain/exécution restent externes ;
- indisponibilité du Brain/données = pas d'action nouvelle par défaut.

## Conséquences
Le futur R-STDP/SNN peut apprendre, mais son apprentissage durable doit passer par une discipline de validation/promotion. Une éventuelle adaptation online plus fine devra être explicitement expérimentée et bornée avant adoption.

## Documents/code concernés
future model/checkpoint registry, replay/research, SNN runtime, service supervision.
