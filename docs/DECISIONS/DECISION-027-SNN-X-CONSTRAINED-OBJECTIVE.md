# DECISION-027 — SNN-X-04 — Rendement sous contraintes et homéostasie

**Date :** 2026-10-04 (Europe/Paris)
**Statut :** ADOPTED — architecture cible ; mécanismes scientifiques EXPERIMENTAL, non implémentés par cette décision.
**Source :** décision explicite de Ryad dans la discussion SNN-X du 4 octobre 2026.

## Contexte
La recherche vise les meilleures opportunités sans confondre rendement et exposition maximale.

## Décision
Étudier un objectif tenant compte du PnL net, drawdown, risque, incertitude, stabilité et budget de calcul/énergie. La forme PnL − λ1·drawdown − λ2·risk − λ3·surprise + λ4·consistency est une hypothèse, sans coefficients adoptés. Normaliser les unités et tester le reward hacking ; pénaliser la surprise peut autrement favoriser une abstention artificielle ou masquer des opportunités.

Ne pas remplacer le reward expérimental versionné du lot J (DECISION-023). Toute variante conserve sa politique et ses preuves. Une agressivité accrue n’est étudiée qu’avec avantage mesuré, toujours dans les limites existantes.

Chaîne obligatoire : Brain → ActionProposal/opportunité → validation déterministe du risque → exécution autorisée. Le cerveau ne possède aucun accès direct à l’argent ni pouvoir de relever les limites.

## Raisonnement
Une performance isolée ne mesure ni la robustesse ni le risque de ruine.

## Conséquences
Extension additive du programme existant. Le travail Alladin déjà engagé et la recette PC F/G continuent ; ces décisions ne prouvent aucune fonctionnalité exécutée ni performance. Implémenter progressivement et désactiver les modules sans apport mesurable.

## Invariants
RiskEngine, SL, kill switch, modes et limites de compte inviolables ; aucune garantie de gain.

## Questions ouvertes
Métriques, normalisation, calibration, coûts et preuve d’avantage restent expérimentaux.

## Conditions de révision
Réviser par une nouvelle décision motivée si les ablations/OOS invalident l’apport, si le budget ou la qualité des données rendent le module impraticable, ou si ses contraintes doivent changer. Conserver les résultats négatifs et l’historique.

## Documents/code concernés
Bible `docs/SNN/ALLADIN_SNN_BIBLE.md`, `docs/HANDOFF.md`, `docs/IMPLEMENTATION_PLAN.md`, décisions 001, 003, 006, 010, 013–020 et 023 ; futurs modules Brain, mémoire, replay, registre de modèles et supervision. Aucun changement runtime dans ce commit.
