# DECISION-001 — Alladin devient SNN-first

**Date :** 2026-10-02  
**Statut :** ADOPTED

## Contexte
Le projet SNN initialement étudié séparément pour BTC est devenu suffisamment central pour redéfinir Alladin.

## Décision
Le SNN devient le cœur apprenant d'Alladin. Il n'est pas un module facultatif ajouté à un routeur de stratégies classique.

## Raisonnement
Le but scientifique est d'étudier une boucle perception -> spikes -> décision -> conséquence -> reward/surprise -> plasticité et de comparer son comportement à des contrôles plus simples.

## Conséquences
StrategyRouter/Claude/Codex ne sont plus le cerveau cible. Les stratégies classiques deviennent contrôles/signaux/expériences.

## Condition de révision
Si les expériences OOS montrent que le SNN n'apporte aucun bénéfice diagnostique ou comportemental face aux contrôles, l'architecture doit pouvoir le démontrer et réduire la complexité.
