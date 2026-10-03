# DECISION-014 — Alladin et Jafar sont deux workspaces isolés sur un core partagé

**Date :** 2026-10-03  
**Statut :** ADOPTED

## Contexte

DECISION-009 établit déjà que Jafar ne doit pas être reconstruit comme une seconde architecture indépendante. La direction précisée aujourd'hui est plus stricte : Alladin et Jafar doivent partager un même moteur de plateforme, tout en restant deux environnements opérationnels distincts.

L'objectif est d'éviter deux échecs opposés :
- dupliquer tout Alladin pour créer Jafar ;
- fusionner leurs états jusqu'à rendre les positions, runs, risques, univers ou cerveaux impossibles à distinguer.

## Décision

Alladin et Jafar deviennent deux **workspaces** indépendants construits au-dessus d'un **core partagé**.

Le core partagé peut contenir notamment :
- contrat `BrainContext -> Brain -> ActionProposal` ;
- primitives RiskEngine et ExecutionService ;
- journal, replay et causal archive ;
- contrats expérimentaux `FillRecord`, `CostModel`, R et OOS ;
- abstractions broker/capabilities ;
- primitives de cycle de vie et d'observabilité.

Chaque workspace conserve son propre état mutable :
- runs et cycles ;
- univers de marché ;
- stratégies et configuration ;
- version de Brain, poids/checkpoints et état d'apprentissage ;
- positions possédées ;
- risque, working capital et challenge state ;
- expériences et configuration de recherche ;
- configuration de broker/account binding.

Jafar **n'est pas un fork** de Alladin. Il réutilise le core, mais son runtime doit pouvoir démarrer, tomber, redémarrer, changer de broker ou expérimenter sans corrompre l'état d'Alladin.

## Invariant de décision

La chaîne reste identique dans les deux workspaces :

```text
Market/Context
    -> Brain
    -> ActionProposal
    -> deterministic Risk
    -> Execution
    -> Broker
```

Aucun Brain ne peut appeler directement le broker.

## Identité

Une identité de workspace explicite doit à terme traverser les entités causales et opérationnelles : run, cycle, opportunity, proposal, risk decision, trade/position, journal, experiment, dataset/replay.

Le système ne doit jamais confondre une position Alladin avec une position Jafar, même si les deux utilisent le même type d'adapter ou, plus tard, le même broker.

## Brain et recherche

Alladin et Jafar peuvent utiliser des implémentations de Brain différentes et doivent avoir des checkpoints/poids isolés. Le partage d'infrastructure de recherche ne signifie pas partage automatique des modèles appris.

## Conséquences

- Réutiliser avant de réécrire reste la règle.
- Toute abstraction commune doit venir d'un besoin réel, pas d'une généralisation prématurée.
- La gestion de position commune doit être stabilisée avant d'introduire un runtime Jafar complet si cette dépendance est confirmée par le code.
- Les interfaces visuelles peuvent partager composants et grammaire UX sans partager l'état opérationnel.

## Invariants

- état mutable isolé par workspace ;
- aucune route Brain -> broker directe ;
- aucune fusion implicite de positions/risques/runs ;
- Jafar ne peut pas dégrader les garanties OBSERVE/PAPER/DEMO d'Alladin ;
- LIVE reste bloqué tant que les gates dédiés ne sont pas implémentés et validés.

## Conditions de révision

Réviser uniquement si l'expérience montre qu'un découpage workspace explicite crée plus de risques ou de duplication qu'il n'en supprime, et documenter alors la décision qui la supersède.

## Documents/code concernés

- `docs/DECISIONS/DECISION-009-JAFAR-SHARED-CORE.md`
- `docs/HANDOFF.md`
- `docs/IMPLEMENTATION_PLAN.md`
- futur modèle workspace/account/broker
