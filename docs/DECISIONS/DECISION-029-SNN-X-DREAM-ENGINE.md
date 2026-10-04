# DECISION-029 — SNN-X-06 — Dream Engine et consolidation hors production

**Date :** 2026-10-04 (Europe/Paris)
**Statut :** ADOPTED — architecture cible ; mécanismes scientifiques EXPERIMENTAL, non implémentés par cette décision.
**Source :** décision explicite de Ryad dans la discussion SNN-X du 4 octobre 2026.

## Contexte
La mémoire doit alimenter des expériences pendant que LIVE poursuit la surveillance.

## Décision
Construire une boucle mémoire/historique → replay causal → apprentissage/consolidation → candidats → validation → promotion contrôlée. Étudier consolidation/affaiblissement de synapses et évolution structurelle bornée hors production.

Les contrefactuels (attendre 30 secondes, autre entrée/sortie) exigent trajectoires archivées et modèle explicite de fills/coûts. Ils restent des simulations, pas des vérités observées. Les contrefactuels limités du lot J ne sont pas automatiquement élargis.

Versionner datasets, code, checkpoints, paramètres, seeds et ressources pour reproduction et retour arrière. Séparer entraînement, sélection et OOS ; ne pas réutiliser silencieusement le test pour sélectionner le gagnant. Le volume d’expériences dépend des ressources mesurées : aucun débit de milliers/millions garanti.

Les trois activités LIVE / SHADOW / DREAM sont une cible parallèle ; Dream transmet des candidats au registre de validation, jamais des poids directement au Brain actif.

## Raisonnement
Le replay permet d’apprendre sans bloquer LIVE et sans transformer une simulation favorable en preuve de déploiement.

## Conséquences
Extension additive du programme existant. Le travail Alladin déjà engagé et la recette PC F/G continuent ; ces décisions ne prouvent aucune fonctionnalité exécutée ni performance. Implémenter progressivement et désactiver les modules sans apport mesurable.

## Invariants
Causalité, isolation, coûts, audit et promotion contrôlée ; aucune mutation directe du runtime.

## Questions ouvertes
Capacité de calcul, replay disponible, validité des contrefactuels et politique de consolidation à mesurer.

## Conditions de révision
Réviser par une nouvelle décision motivée si les ablations/OOS invalident l’apport, si le budget ou la qualité des données rendent le module impraticable, ou si ses contraintes doivent changer. Conserver les résultats négatifs et l’historique.

## Documents/code concernés
Bible `docs/SNN/ALLADIN_SNN_BIBLE.md`, `docs/HANDOFF.md`, `docs/IMPLEMENTATION_PLAN.md`, décisions 001, 003, 006, 010, 013–020 et 023 ; futurs modules Brain, mémoire, replay, registre de modèles et supervision. Aucun changement runtime dans ce commit.
