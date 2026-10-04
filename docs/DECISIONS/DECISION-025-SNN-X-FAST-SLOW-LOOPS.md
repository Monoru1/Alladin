# DECISION-025 — SNN-X-02 — Boucles FAST/LIVE et SLOW/LEARNING

**Date :** 2026-10-04 (Europe/Paris)
**Statut :** ADOPTED — architecture cible ; mécanismes scientifiques EXPERIMENTAL, non implémentés par cette décision.
**Source :** décision explicite de Ryad dans la discussion SNN-X du 4 octobre 2026.

## Contexte
La surveillance doit continuer pendant les expériences lourdes, conformément à DECISION-020.

## Décision
Séparer FAST/LIVE (perception, prédiction/inférence, propositions, suivi) et SLOW/LEARNING (replay, entraînement, plasticité, évaluation). Isoler calcul, mémoire, files et budgets de ressources pour que l’apprentissage ne bloque pas le chemin critique. Les mécanismes précis et budgets seront mesurés avant activation.

Le Brain actif reste versionné et gelé pour ses poids durables. Une surprise élevée peut conduire à une proposition plus prudente ou à l’abstention ; augmenter plasticité/exploration concerne la recherche et SHADOW, sans modifier librement PROD. Les limites déterministes restent externes.

## Raisonnement
Une expérience coûteuse ou en erreur ne doit pas dégrader la gestion des positions.

## Conséquences
Extension additive du programme existant. Le travail Alladin déjà engagé et la recette PC F/G continuent ; ces décisions ne prouvent aucune fonctionnalité exécutée ni performance. Implémenter progressivement et désactiver les modules sans apport mesurable.

## Invariants
Pas de dépendance runtime à Claude/Codex ; pas d’apprentissage durable incontrôlé en production.

## Questions ouvertes
Isolation processus, latence acceptable, backpressure et allocation CPU/GPU à spécifier.

## Conditions de révision
Réviser par une nouvelle décision motivée si les ablations/OOS invalident l’apport, si le budget ou la qualité des données rendent le module impraticable, ou si ses contraintes doivent changer. Conserver les résultats négatifs et l’historique.

## Documents/code concernés
Bible `docs/SNN/ALLADIN_SNN_BIBLE.md`, `docs/HANDOFF.md`, `docs/IMPLEMENTATION_PLAN.md`, décisions 001, 003, 006, 010, 013–020 et 023 ; futurs modules Brain, mémoire, replay, registre de modèles et supervision. Aucun changement runtime dans ce commit.
