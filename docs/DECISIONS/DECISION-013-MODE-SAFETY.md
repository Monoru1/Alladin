# DECISION-013 — Contrat de sécurité des modes OBSERVE / PAPER / DEMO

**Date :** 2026-10-02
**Statut :** ADOPTED
**Décisions liées :** 003 (risque déterministe), 008 (service autonome), 011 (cycle de vie des positions)

## Contexte

`RunMode.OBSERVE` et `RunMode.PAPER` sont décrits comme ne produisant aucun `order_send` (`src/alladin/core/enums.py`, aide `src/alladin/cli.py`). Les nouvelles entrées passent effectivement par `ExecutionService.submit(..., dry_run=True)` (`orchestration/engine.py`). En revanche, `PositionMonitor.sync()` peut signaler le SL supprimé d'une position DEMO possédée et `OrchestrationEngine` appelle alors `ExecutionService.close_position()`, qui peut envoyer un CLOSE. `ExecutionService.submit(dry_run=True)` peut aussi appeler `close_all()` avant le retour dry-run si le profil demande une fermeture sur échec ; ce réglage est actuellement `false` dans `config/challenge_profiles/ftmo_2step_demo.yaml`.

Une fermeture protectrice peut être légitime pour une position DEMO déjà ouverte, mais une promesse « aucun ordre broker » ne peut pas rester ambiguë. Le défaut de confirmation/retry d'une fermeture refusée est traité indépendamment dans le lot A de `docs/IMPLEMENTATION_PLAN.md`.

## Option adoptée

Séparer formellement les capacités d'exécution par mode :

### OBSERVE — lecture stricte

- Aucun appel à `BrokerAdapter.send_order`, même pour CLOSE, même sur erreur.
- Observation réelle du marché, scan, analyse, journalisation.
- Si une position DEMO existante est détectée sans SL : alerte critique journalisée, blocage des nouvelles entrées via les contrôles existants. L'opérateur doit intervenir manuellement ou basculer en DEMO.
- Pas de portefeuille simulé sauf si le contrat évolue explicitement.
- Fail-closed : toute ambiguïté donne NO_TRADE + alerte.

### PAPER — simulation isolée

- Aucun appel à `BrokerAdapter.send_order`, même pour CLOSE.
- Pipeline complet : scan → agent → intent → RiskEngine (dry_run) → validation.
- Si la validation risque est approuvée : `PaperExperimentEngine` crée une position simulée.
- Positions PAPER persistées en base (table `paper_positions`), survivent au restart.
- Lifecycle complet : open → market evolution (tick_all) → SL/TP/explicit close → outcome → P&L → journal.
- Frais/spread modélisables via le spread réel du tick au moment du fill simulé.
- `DRY_RUN_APPROVED` n'est PAS un fill, pas une position, pas un résultat financier. Le statut d'une exécution PAPER réussie est `PAPER_EXECUTED`.
- RiskEngine s'applique intégralement (sizing, exposure, SL requirements, kill switch).
- Les positions PAPER ne partagent pas les positions ni ordres du broker.

### DEMO — exécution sécurisée

- Seule voie autorisée vers `BrokerAdapter.send_order`.
- Exige `AccountType.DEMO`, ownership (magic+comment), `ApprovalToken`, RiskEngine, ChallengeWatchdog.
- Fermetures protectrices autorisées sur positions possédées : résultat vérifié, retry borné, journal d'échec.
- Toutes protections existantes conservées.

### LIVE — interdit

- Aucun mode LIVE n'existe. `AccountType.LIVE` bloque l'exécution au niveau broker.

## Invariants

1. Un mode strict read-only (OBSERVE) n'appelle jamais `BrokerAdapter.send_order`, même sur erreur.
2. PAPER n'appelle jamais `BrokerAdapter.send_order`. L'exécution simulée passe par `PaperExperimentEngine`.
3. Un CLOSE DEMO protecteur exige compte DEMO, ownership magic+comment, token et confirmation broker ; toute ambiguïté reste visible et réconciliée.
4. PAPER ne partage pas les positions ou ordres du broker d'exécution.
5. Aucun mode n'envoie d'ordre LIVE/CONTEST/UNKNOWN.
6. Les actions de sécurité sur une position DEMO existante ne sont possibles qu'en mode DEMO. Passer en OBSERVE ne désactive pas la détection, mais transforme la fermeture protectrice en alerte critique nécessitant intervention humaine.

## Raisonnement

La séparation de capacité rend testable la frontière « aucun ordre » et évite qu'un opérateur démarre OBSERVE en pensant que MT5 ne sera jamais modifié. Elle peut laisser une position déjà ouverte sans SL si le service DEMO de protection est absent ; l'alerte, le blocage des nouvelles entrées et la procédure opérateur compensent ce risque. L'alternative (autoriser CLOSE en OBSERVE) était écartée car elle brise la promesse read-only testable.

## Validation

Tests d'intégration avec broker espion dont `send_order` lève immédiatement : vérifier que OBSERVE et PAPER fonctionnent sans erreur. Position possédée sans SL en OBSERVE : alerte journalisée, pas de CLOSE envoyé. PAPER : position simulée créée, persistée, restaurée après restart. DEMO : chemin actuel préservé.

## Documents/code concernés

`docs/IMPLEMENTATION_PLAN.md`, `src/alladin/core/enums.py`, `src/alladin/cli.py`, `src/alladin/orchestration/engine.py`, `src/alladin/execution/service.py`, `src/alladin/market/paper.py`, `src/alladin/journal/repository.py`, `tests/test_daemon_modes.py`, `tests/test_paper_engine.py`.
