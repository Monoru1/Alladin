# DECISION-034 — Capital Engine : objectifs, preuve et croissance
- Date : 2026-10-08
- Statut : ADOPTED (cadre) ; EXPERIMENTAL (objectifs de performance)

## Contexte
Alladin doit viser à constituer un patrimoine personnel et financer les projets Astra, en distinguant allocations simulées, profits d'évaluation et récompenses nettes réellement encaissées.

## Décision
1. L'objectif stratégique de long terme est une croissance substantielle et durable du capital propre ; aucun pourcentage mensuel n'est garanti ni fixé comme obligation du moteur.
2. Enregistrer distinctement : frais d'évaluation, capital nominal simulé, phase, profits simulés, récompenses demandées, reçues, impôts/frais estimés, cash réellement disponible et capital investi hors prop firm.
3. Tester les scénarios de performance post-validation (+3 %, +5 %, +10 %, +20 %, +30 %) comme hypothèses ; +20 à +30 % ne constituent pas un seuil opérationnel obligatoire. Comparer 10k, 100k, 200k et allocations permises selon le programme.
4. Simuler des séries entières de challenges, y compris échecs, pauses, slippage, frais, changement de régime, drawdowns et interruption de versements. Optimiser espérance de récompense nette, probabilité de survie et croissance long terme plutôt que rendement maximal isolé.
5. Promotion : backtest causal OOS multi-régime -> PAPER -> MT5 DEMO -> challenges simulés répétés -> revue humaine -> éventuel challenge officiel. Mesurer performance hors échantillon et intervalle d'incertitude ; aucun taux de réussite inventé.
6. Un budget d'évaluations explicite et plafonné doit être fixé avant achat. Ne jamais financer les frais par dette non soutenable ou argent nécessaire au quotidien. Tout transfert vers portefeuille propre repose sur montants réellement encaissés et comptabilisés.
7. Garder une réserve de fonctionnement et une réserve fiscale adaptées à la situation réelle. Réexaminer périodiquement la dépendance aux fournisseurs et la concentration des sources de revenu.

## Indicateurs de qualité
Validation complète, coût par validation, probabilité de perte du compte, profit factor net, espérance par trade, drawdown, stress des annonces, ratio récompenses reçues/frais engagés, distribution des périodes négatives, stabilité OOS, disponibilité du runtime.

## Raisonnement
Avoir plusieurs millions de capital nominal de prop firm n'est pas posséder plusieurs millions. La conversion vers patrimoine propre doit être mesurable.

## Invariants
Aucune promesse de rendement, aucune prise de risque commandée uniquement par un objectif de revenu, pas de LIVE sans autorisation explicite ni validation des garde-fous.

## Questions ouvertes
Allocation des récompenses, horizon cible, budget soutenable, fiscalité, contraintes des firmes et cadence de revue.

## Conditions de révision
Échec OOS, taux de perte excessif, modifications contractuelles ou nouvelles preuves de performance.

## Documents et code concernés
DECISION-018, 020, 023, 031, 033 ; research/, challenge/, risk/, Mission Control.
