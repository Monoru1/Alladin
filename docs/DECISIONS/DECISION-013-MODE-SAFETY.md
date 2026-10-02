# DECISION-013 — Contrat des sorties protectrices par mode

**Date :** 2026-10-02
**Statut :** PROPOSED
**Décisions liées :** 003 (risque déterministe), 008 (service autonome), 011 (cycle de vie des positions)

## Contexte

`RunMode.OBSERVE` et `RunMode.PAPER` sont décrits comme ne produisant aucun `order_send` (`src/alladin/core/enums.py`, aide `src/alladin/cli.py`). Les nouvelles entrées passent effectivement par `ExecutionService.submit(..., dry_run=True)` (`orchestration/engine.py`). En revanche, `PositionMonitor.sync()` peut signaler le SL supprimé d'une position DEMO possédée et `OrchestrationEngine` appelle alors `ExecutionService.close_position()`, qui peut envoyer un CLOSE. `ExecutionService.submit(dry_run=True)` peut aussi appeler `close_all()` avant le retour dry-run si le profil demande une fermeture sur échec ; ce réglage est actuellement `false` dans `config/challenge_profiles/ftmo_2step_demo.yaml`.

Une fermeture protectrice peut être légitime pour une position DEMO déjà ouverte, mais une promesse « aucun ordre broker » ne peut pas rester ambiguë. Le défaut de confirmation/retry d'une fermeture refusée est traité indépendamment dans le premier lot de `docs/IMPLEMENTATION_PLAN.md`.

## Choix à adopter

**Option recommandée :** séparer formellement le mode d'observation strictement sans ordre d'un mode de gestion de positions DEMO possédées. Dans un processus strict OBSERVE/PAPER, `send_order` est impossible, même pour CLOSE ; les positions non protégées produisent une alerte critique et bloquent toute nouvelle entrée. Un service DEMO explicitement autorisé conserve les fermetures protectrices, vérifie le compte et l'ownership, journalise le résultat, réconcilie et retente de façon bornée si nécessaire. PAPER utilise un portefeuille simulé séparé et ne ferme jamais une position MT5 réelle.

**Alternative :** autoriser les CLOSE protecteurs en OBSERVE/PAPER, mais le dire explicitement dans la CLI/UI/docs et exiger le même opt-in que DEMO pour ce droit. Cela réduit le risque de position sans SL tout en renonçant au contrat de lecture stricte.

## Raisonnement et conséquences

La séparation de capacité rend testable la frontière « aucun ordre » et évite qu'un opérateur démarre OBSERVE en pensant que MT5 ne sera jamais modifié. Elle peut laisser une position déjà ouverte sans SL si le service DEMO de protection est absent ; l'alerte, le blocage des nouvelles entrées et la procédure opérateur doivent être définis avant adoption. La décision ne permet ni LIVE, ni suppression de SL, ni accès direct du cerveau au broker. L'invariant de contrôle déterministe reste celui de la décision 003.

## Invariants proposés

- Un mode strict read-only n'appelle jamais `BrokerAdapter.send_order`, même sur erreur.
- Un CLOSE DEMO protecteur exige compte DEMO, ownership magic+comment, token et confirmation broker ; toute ambiguïté reste visible et réconciliée.
- PAPER ne partage pas les positions ou ordres du broker d'exécution.
- Aucun mode n'envoie d'ordre LIVE/CONTEST/UNKNOWN.

## Validation avant adoption

Tests d'intégration avec broker espion : position possédée sans SL, fermeture acceptée/refusée, profil `close_positions_on_fail` activé, position étrangère, restart ; vérifier exactement les appels `send_order` autorisés par mode. Documenter le flux opérateur pour une alerte critique en OBSERVE strict.

## Questions ouvertes / condition de révision

Quelle autorisation explicite protège le service DEMO de gestion de positions et quel délai maximal d'alerte est acceptable si ce service est indisponible ? Réviser la proposition si les tests montrent qu'un OBSERVE strict augmente excessivement le risque opérationnel sans mécanisme de protection crédible. Aucune option n'est adoptée par la création de cette fiche.

## Documents/code concernés

`docs/IMPLEMENTATION_PLAN.md`, `docs/ARCHITECTURE.md`, `README.md`, `src/alladin/core/enums.py`, `src/alladin/cli.py`, `src/alladin/orchestration/engine.py`, `src/alladin/execution/service.py`, `src/alladin/market/paper.py`, `tests/test_daemon_modes.py`, `tests/test_execution.py`.
