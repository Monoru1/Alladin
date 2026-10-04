# DECISION-024 — SNN-X-01 — Extension parallèle et non destructive

**Date :** 2026-10-04 (Europe/Paris)
**Statut :** ADOPTED — architecture cible ; mécanismes scientifiques EXPERIMENTAL, non implémentés par cette décision.
**Source :** décision explicite de Ryad dans la discussion SNN-X du 4 octobre 2026.

## Contexte
Ryad veut ajouter une contribution SNN-X sans interrompre ni remplacer le travail déjà adopté.

## Décision
Conserver la voie scientifique initiale (les neuf phases discutées : fondations/connectome, données, pruning, moteur/plasticité, encodage, métabolisme/énergie libre, essaim, backend/persistance, validation/exécution) et la bible SNN actuelle. SNN-X est un nom de programme de recherche additionnel, pas une nouvelle version produit ni un changement de priorité imposé.

Ajouter des modules désactivables individuellement : World Model, Surprise, homéostasie financière, populations spécialisées, Dream/Replay et évolution structurelle contrôlée. Le connectome MaleCNS reste un prior expérimental ; renforcement, pruning et création bornée de connexions se testent hors production.

Le modèle prédictif peut prévoir plusieurs horizons (ex. 1 s, 10 s, 1 min, 5 min selon données disponibles). L'erreur prédiction/observation nourrit la recherche. Prix/OHLCV multi-échelles, spread/profondeur/order flow, volatilité/funding/OI/liquidations et contexte ETH/indices/dollar/taux sont des capteurs candidats, pas des données déjà collectées.

Chaque module doit avoir une fiche : origine dans la littérature à vérifier, adaptation, contribution envisagée (originalité non démontrée), données/provenance, expérience, critère d'abandon. Comparer baselines classiques, connectome, R-STDP, énergie libre puis ajouts isolés et combinaison ; contrôler aussi l'effet de la topologie. Conserver chronologie, coûts et budget de calcul comparables.

## Raisonnement
Les métaphores biologiques orientent des hypothèses ; seules les ablations permettent de mesurer une contribution.

## Conséquences
Extension additive du programme existant. Le travail Alladin déjà engagé et la recette PC F/G continuent ; ces décisions ne prouvent aucune fonctionnalité exécutée ni performance. Implémenter progressivement et désactiver les modules sans apport mesurable.

## Invariants
Ne pas réécrire les fondations ni déclarer un avantage scientifique ou financier sans preuves.

## Questions ouvertes
Ordre des modules, horizons, données accessibles et critères quantitatifs d’ablation restent à définir.

## Conditions de révision
Réviser par une nouvelle décision motivée si les ablations/OOS invalident l’apport, si le budget ou la qualité des données rendent le module impraticable, ou si ses contraintes doivent changer. Conserver les résultats négatifs et l’historique.

## Documents/code concernés
Bible `docs/SNN/ALLADIN_SNN_BIBLE.md`, `docs/HANDOFF.md`, `docs/IMPLEMENTATION_PLAN.md`, décisions 001, 003, 006, 010, 013–020 et 023 ; futurs modules Brain, mémoire, replay, registre de modèles et supervision. Aucun changement runtime dans ce commit.
