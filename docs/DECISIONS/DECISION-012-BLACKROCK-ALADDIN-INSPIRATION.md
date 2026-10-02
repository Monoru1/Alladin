# DECISION-012 — Inspiration BlackRock Aladdin

**Date :** 2026-10-02  
**Statut :** ADOPTED

## Contexte
Le nom et une partie de la philosophie architecturale d'Alladin sont inspirés d'Aladdin de BlackRock.

## Faits vérifiés
BlackRock indique avoir développé Aladdin dès ses premières années pour gérer portefeuilles et risque. La plateforme actuelle unifie le processus d'investissement via un langage de données commun et couvre notamment portfolio management, risk, trading, compliance, operations et accounting.

Sources officielles :
- https://www.blackrock.com/corporate/about-us/who-we-are/history
- https://www.blackrock.com/aladdin
- https://www.blackrock.com/aladdin/platforms/products/aladdin-risk
- https://www.blackrock.com/aladdin/benefits/traders

Larry Fink est cofondateur, Chairman et CEO de BlackRock. Il ne faut pas attribuer Aladdin à Jeff Bezos.

## Ce que notre Alladin emprunte conceptuellement
- vue unifiée du système ;
- données communes ;
- risque transversal ;
- portefeuille plutôt que trades isolés ;
- intégration analyse -> risque -> exécution -> suivi ;
- observabilité et audit ;
- scénarios/contre-factuels comme outils de compréhension ;
- architecture extensible et intégrations externes.

## Ce que notre Alladin ne prétend PAS être
Nous ne possédons ni ne reproduisons le code, les modèles propriétaires, les données, l'infrastructure ou les capacités internes de BlackRock Aladdin.

L'inspiration est architecturale et conceptuelle.

## Différence centrale
Notre projet ajoute un axe expérimental autonome : cerveau SNN, plasticité, reward/pain/surprise, apprentissage, replay et gestion autonome des positions, toujours bornés par un RiskEngine déterministe.

## Invariant
S'inspirer d'un principe institutionnel ne constitue jamais une preuve de performance pour notre système. Chaque mécanisme d'Alladin doit être validé indépendamment.
