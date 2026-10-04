# DECISION-026 — SNN-X-03 — Surveillance continue et mémoire du non-trade

**Date :** 2026-10-04 (Europe/Paris)
**Statut :** ADOPTED — architecture cible ; mécanismes scientifiques EXPERIMENTAL, non implémentés par cette décision.
**Source :** décision explicite de Ryad dans la discussion SNN-X du 4 octobre 2026.

## Contexte
Observer BTC doit produire des expériences même en absence de position.

## Décision
Cibler une observation BTC 24/7 sur infrastructure effectivement allumée et connectée. Enregistrer événements, régimes, volatilité, anomalies, prédictions horodatées, erreurs réalisées, abstentions et propositions hypothétiques. Distinguer données observées, résultats de trades et contrefactuels simulés.

Prévoir supervision, reprise après coupure, détection de trous et données périmées, horodatage causal, provenance et rétention. Une panne ne fabrique pas les observations manquantes. Une absence de trade est exploitable comme observation mais n’est pas un outcome financier réel.

Cette cible ne déploie aucun hébergement payant et ne permet pas de fonctionner PC éteint sans autre hôte. Respecter les sessions des autres instruments. Jafar reste actuellement OBSERVE uniquement.

## Raisonnement
Une mémoire continue permet de comparer décisions et abstentions sans forcer des entrées.

## Conséquences
Extension additive du programme existant. Le travail Alladin déjà engagé et la recette PC F/G continuent ; ces décisions ne prouvent aucune fonctionnalité exécutée ni performance. Implémenter progressivement et désactiver les modules sans apport mesurable.

## Invariants
Données absentes ≠ zéro ; aucune promesse de service 24/7 déjà opérationnel.

## Questions ouvertes
Hôte disponible, coût, stockage, fréquence de collecte et couverture des flux à décider.

## Conditions de révision
Réviser par une nouvelle décision motivée si les ablations/OOS invalident l’apport, si le budget ou la qualité des données rendent le module impraticable, ou si ses contraintes doivent changer. Conserver les résultats négatifs et l’historique.

## Documents/code concernés
Bible `docs/SNN/ALLADIN_SNN_BIBLE.md`, `docs/HANDOFF.md`, `docs/IMPLEMENTATION_PLAN.md`, décisions 001, 003, 006, 010, 013–020 et 023 ; futurs modules Brain, mémoire, replay, registre de modèles et supervision. Aucun changement runtime dans ce commit.
