# DECISION-028 — SNN-X-05 — Shadow Brain et promotion contrôlée

**Date :** 2026-10-04 (Europe/Paris)
**Statut :** ADOPTED — architecture cible ; mécanismes scientifiques EXPERIMENTAL, non implémentés par cette décision.
**Source :** décision explicite de Ryad dans la discussion SNN-X du 4 octobre 2026.

## Contexte
Les nouvelles idées doivent pouvoir être comparées au Brain actif sans exposer de capital.

## Décision
Faire observer le même flux causal à un Brain actif autorisé et à un ou plusieurs Shadow Brains isolés. SHADOW produit uniquement propositions et simulations ; il ne peut ni envoyer d’ordres ni modifier les positions ou poids actifs.

Tester nouvelles connexions, capteurs, rewards, spécialisations et stratégies exploratoires avec versions et seeds traçables. Comparer sur horizons définis à l’avance, coûts réalistes, OOS chronologique, drawdown, stabilité et incertitude statistique ; tenir compte des essais multiples.

Un meilleur résultat rend le Shadow candidat, jamais remplaçant automatique. Appliquer DECISION-020 et les gates existants : validation, promotion explicite contrôlée, changement atomique, audit et rollback. PROD désigne ici le Brain actif dans un mode autorisé, pas une autorisation d’argent réel.

## Raisonnement
La comparaison parallèle mesure les candidats sans contaminer le système actif.

## Conséquences
Extension additive du programme existant. Le travail Alladin déjà engagé et la recette PC F/G continuent ; ces décisions ne prouvent aucune fonctionnalité exécutée ni performance. Implémenter progressivement et désactiver les modules sans apport mesurable.

## Invariants
SHADOW sans exécution ; pas d’auto-promotion ni d’assouplissement du mode Jafar.

## Questions ouvertes
Durée, seuils, puissance statistique et nombre de candidats simultanés à fixer avant essais.

## Conditions de révision
Réviser par une nouvelle décision motivée si les ablations/OOS invalident l’apport, si le budget ou la qualité des données rendent le module impraticable, ou si ses contraintes doivent changer. Conserver les résultats négatifs et l’historique.

## Documents/code concernés
Bible `docs/SNN/ALLADIN_SNN_BIBLE.md`, `docs/HANDOFF.md`, `docs/IMPLEMENTATION_PLAN.md`, décisions 001, 003, 006, 010, 013–020 et 023 ; futurs modules Brain, mémoire, replay, registre de modèles et supervision. Aucun changement runtime dans ce commit.
