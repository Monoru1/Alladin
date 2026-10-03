# DECISION-019 — Le Brain propose, le système gouverne et exécute

**Date :** 2026-10-03  
**Statut :** ADOPTED

## Contexte
Le Lot E a créé une frontière stable entre stratégies classiques et futurs cerveaux.

## Décision
Le contrat commun est `Brain.decide(BrainContext) -> ActionProposal`. `ActionProposal` est versionné, validé, traçable et possède une identité stable.

`NO_TRADE` est une décision de première classe : jamais `None`, absence de proposition ou exception.

Le Brain peut proposer des entrées et, à terme, des actions de gestion (`HOLD`, `CLOSE`, `MODIFY_STOP`, `MODIFY_TARGET`, `PARTIAL_CLOSE`). Toute action reste soumise aux lois déterministes, ownership, capabilities, mode safety et kill switch.

## Chaîne obligatoire
```text
Market/Context -> Brain -> ActionProposal -> deterministic Risk -> Execution -> Broker
```

Le chemin classique passe par un adapter vers le même `ActionProposal` afin de préserver la parité avec les futurs SNN.

## Fail-closed
Brain indisponible, exception, schéma inconnu ou proposition invalide : aucune invention de trade. L'échec est explicite/journalisé et le système reste sûr.

Les fermetures protectrices déterministes restent indépendantes du Brain : une panne du Brain ne peut pas neutraliser les mécanismes de sécurité existants.

## Invariants
- aucune route Brain -> broker ;
- aucun lot final choisi librement par le Brain ;
- proposition malformée non réparée silencieusement ;
- lifecycle traçable opportunity -> proposal -> risk -> trade/position -> outcome ;
- OBSERVE/PAPER/DEMO conservent DECISION-013 ;
- LIVE reste bloqué.

## Limitation actuelle
Après Lot E, `CLOSE`, `MODIFY_STOP`, `MODIFY_TARGET` et `PARTIAL_CLOSE` ne sont pas encore autorisés par la politique normale ; leur exécution contrôlée constitue un chantier suivant.

## Documents/code concernés
`src/alladin/brain.py`, lifecycle/journal/risk/execution, `docs/IMPLEMENTATION_PLAN.md`.
