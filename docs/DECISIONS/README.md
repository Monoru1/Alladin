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
13. [DECISION-013 — Contrat de sécurité des modes OBSERVE/PAPER/DEMO (ADOPTED)](./DECISION-013-MODE-SAFETY.md)
14. [DECISION-014 — Alladin et Jafar sont deux workspaces isolés sur un core partagé (ADOPTED)](./DECISION-014-ALLADIN-JAFAR-WORKSPACES.md)
15. [DECISION-015 — Broker et compte sont des bindings, pas l'identité d'un workspace (ADOPTED)](./DECISION-015-BROKER-ACCOUNT-ABSTRACTION.md)
16. [DECISION-016 — Command Center global et identités visuelles distinctes (ADOPTED)](./DECISION-016-GLOBAL-COMMAND-CENTER.md)
17. [DECISION-017 — Vérité marché causale, archivée et rejouable (ADOPTED)](./DECISION-017-CAUSAL-MARKET-TRUTH-REPLAY.md)
18. [DECISION-018 — Économie expérimentale commune (ADOPTED)](./DECISION-018-COMMON-EXPERIMENTAL-ECONOMICS.md)
19. [DECISION-019 — Frontière Brain / ActionProposal (ADOPTED)](./DECISION-019-BRAIN-ACTION-PROPOSAL-BOUNDARY.md)
20. [DECISION-020 — Apprentissage et promotion contrôlés (ADOPTED)](./DECISION-020-CONTROLLED-LEARNING-PROMOTION.md)
21. [DECISION-021 — Univers broker dynamique et filtré (ADOPTED)](./DECISION-021-DYNAMIC-BROKER-UNIVERSE.md)
22. [DECISION-022 — Strategy Harvester : provenance, licence et clean-room (ADOPTED)](./DECISION-022-STRATEGY-HARVESTER-GOVERNANCE.md)

23. [DECISION-023 — Outcomes audités et reward expérimental versionné (ADOPTED / coefficients EXPERIMENTAL)](./DECISION-023-OUTCOME-REWARD-EVIDENCE.md)

24. [DECISION-024 — SNN-X-01 — Extension parallèle et non destructive (ADOPTED)](./DECISION-024-SNN-X-PARALLEL-EXTENSIONS.md)
25. [DECISION-025 — SNN-X-02 — Boucles FAST/LIVE et SLOW/LEARNING (ADOPTED)](./DECISION-025-SNN-X-FAST-SLOW-LOOPS.md)
26. [DECISION-026 — SNN-X-03 — Surveillance continue et mémoire du non-trade (ADOPTED)](./DECISION-026-SNN-X-CONTINUOUS-OBSERVATION.md)
27. [DECISION-027 — SNN-X-04 — Rendement sous contraintes et homéostasie (ADOPTED)](./DECISION-027-SNN-X-CONSTRAINED-OBJECTIVE.md)
28. [DECISION-028 — SNN-X-05 — Shadow Brain et promotion contrôlée (ADOPTED)](./DECISION-028-SNN-X-SHADOW-BRAIN.md)
29. [DECISION-029 — SNN-X-06 — Dream Engine et consolidation hors production (ADOPTED)](./DECISION-029-SNN-X-DREAM-ENGINE.md)
30. [DECISION-030 — Binance Spot natif pour Jafar et credentials Ed25519 locaux (ADOPTED)](./DECISION-030-JAFAR-BINANCE-SPOT-ED25519.md)

31. [DECISION-031 — Univers multi-marchés FTMO et sélection de symboles (ADOPTED ; performances EXPERIMENTAL)](./DECISION-031-FTMO-MULTI-MARKET-SYMBOLS.md)

32. [DECISION-032 — Economic Intelligence et décisions sensibles aux annonces (ADOPTED ; efficacité EXPERIMENTAL)](./DECISION-032-ECONOMIC-INTELLIGENCE.md)
33. [DECISION-033 — Moteur multi-prop-firm et conformité par compte (ADOPTED ; intégrations PLANNED)](./DECISION-033-MULTI-PROPFIRM-COMPLIANCE.md)
34. [DECISION-034 — Capital Engine : objectifs, preuve et croissance (ADOPTED ; performances EXPERIMENTAL)](./DECISION-034-CAPITAL-ENGINE-OBJECTIVES.md)
35. [DECISION-035 — Autonomie surveillée, qualité et observabilité (ADOPTED ; qualification PLANNED)](./DECISION-035-AUTONOMOUS-OPERATIONS-QUALITY.md)

## Source de vérité

- Architecture SNN : `docs/SNN/ALLADIN_SNN_BIBLE.md`
- Fonctionnement du cerveau : `docs/SNN/FLY_BRAIN_FUNCTION.md`
- Recherche stratégies : `docs/STRATEGIES/`
- Raisonnement décisionnel : **ce dossier**
