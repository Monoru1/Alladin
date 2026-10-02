# ALLADIN — Registre des décisions

**Statut : mémoire opérationnelle du projet**

Ce dossier conserve les décisions d'architecture et de recherche prises pendant la conception d'Alladin.

## Règle

Une décision importante = un document.

Chaque fiche doit contenir :
- date ;
- statut ;
- contexte ;
- décision ;
- raisonnement ;
- conséquences ;
- invariants ;
- questions ouvertes ;
- conditions de révision ;
- documents/code concernés.

Les décisions ne sont pas des vérités éternelles. Si une expérience invalide une décision, on ne réécrit pas silencieusement l'histoire : on crée une nouvelle décision qui **supersède** l'ancienne et explique pourquoi.

## Statuts

- `ADOPTED` : décision actuelle.
- `PROPOSED` : proposition documentée, non encore adoptée.
- `EXPERIMENTAL` : hypothèse à valider.
- `SUPERSEDED` : remplacée par une décision plus récente.
- `REJECTED` : piste explicitement abandonnée.

## Index actuel

1. [DECISION-001 — Alladin devient SNN-first](./DECISION-001-SNN-FIRST.md)
2. [DECISION-002 — Réutiliser avant de réécrire](./DECISION-002-REUSE-BEFORE-REWRITE.md)
3. [DECISION-003 — RiskEngine déterministe et inviolable](./DECISION-003-DETERMINISTIC-RISK.md)
4. [DECISION-004 — Alladin est multi-instruments et broker-agnostic](./DECISION-004-MULTI-BROKER.md)
5. [DECISION-005 — Les stratégies deviennent une bibliothèque expérimentale](./DECISION-005-STRATEGY-LAB.md)
6. [DECISION-006 — Le runtime ne dépend pas d'un LLM](./DECISION-006-NO-LLM-RUNTIME.md)
7. [DECISION-007 — Cockpit Mission Control et décisions persistantes](./DECISION-007-MISSION-CONTROL.md)
8. [DECISION-008 — Alladin doit fonctionner comme service autonome](./DECISION-008-AUTONOMOUS-SERVICE.md)
9. [DECISION-009 — Jafar réutilisera le core Alladin](./DECISION-009-JAFAR-SHARED-CORE.md)
10. [DECISION-010 — Pas de logique produit V1/V2](./DECISION-010-NO-V1-V2.md)
11. [DECISION-011 — Cycle de vie autonome multi-position (ADOPTED)](./DECISION-011-AUTONOMOUS-MULTI-POSITION-LIFECYCLE.md)
12. [DECISION-012 — Inspiration BlackRock Aladdin (ADOPTED)](./DECISION-012-BLACKROCK-ALADDIN-INSPIRATION.md)
13. [DECISION-013 — Contrat des sorties protectrices par mode (PROPOSED)](./DECISION-013-MODE-SAFETY.md)

## Source de vérité

- Architecture SNN : `docs/SNN/ALLADIN_SNN_BIBLE.md`
- Fonctionnement du cerveau : `docs/SNN/FLY_BRAIN_FUNCTION.md`
- Recherche stratégies : `docs/STRATEGIES/`
- Raisonnement décisionnel : **ce dossier**
