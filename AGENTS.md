# ALLADIN — Instructions pour Codex et agents de développement

## État actuel après lot 8

Lire les derniers handoffs, POLICY_ARCHIVE.md et CHALLENGE_CAMPAIGNS.md. Campagnes trailing configurées, EOD/reset explicites et sélecteur de phase testés ; 32 replays supplémentaires synthétiques. Dernière suite réellement exécutée : **1501 passed, 3 skipped MT5, 0 failed**, Ruff/mypy PASS (117 fichiers). Aucun dossier financier admis ni mode d’exécution promu ; checkpoint opt-in OBSERVE/PAPER.


## État actuel après lot 7

Lire le dernier bloc des handoffs et docs/POLICY_ARCHIVE.md. Dossiers SIMULATION_ONLY persistants, archive causale et composite à gaps raccordés passivement au checkpoint opt-in OBSERVE/PAPER. Aucun compte réellement admis ni source publique partielle transformée en couverture complète. Dernière suite : 1484 passed, 3 skipped MT5 ; Ruff/mypy PASS (117 fichiers).


## État actuel après lot 6 du 2026-10-08

Lire le dernier bloc des handoffs et le tableau actuel du plan. Campagnes synthétiques reproductibles et audit après fill SL/TP PAPER livrés ; checkpoint toujours opt-in OBSERVE/PAPER. Dernière suite finale réellement exécutée : **1435 passed, 3 skipped MT5, 0 failed** ; Ruff PASS, mypy PASS (112 fichiers). Preuves : docs/reports/policy_software_current.json. Aucun contrat réel, trading, compte, disponibilité 24/7 ou performance admis par ces tests.


## État actuel après lot 5 du 2026-10-08

Lire les blocs lot 4/5 des handoffs. PolicyGate dispose maintenant de contraintes de compte et d’un checkpoint **opt-in OBSERVE/PAPER** dans l’orchestrateur ; aucune activation globale ni chemin DEMO autorisé par ce checkpoint. Sources publiques partielles : voir docs/PUBLIC_CALENDAR.md. Les mentions antérieures « hors runtime/non ingéré » sont historiques ou décrivent les sondes offline. Dernière suite réellement exécutée : 1416 passed, 3 skipped MT5 ; Ruff/mypy PASS. Préserver protections natives et RiskEngine.


## Reprise après validation offline du 2026-10-08

Lire le dernier lot dans les trois handoffs et `docs/POLICY_VALIDATION.md`. Les PolicyGate/event/firm/capital/calendar et sondes de qualité sont implémentés et testés **hors runtime** ; les paragraphes plus anciens « tests non exécutés » décrivent leur création, pas leur état actuel. Commande ciblée : `python -m pytest -o addopts='' -q tests/test_economic_calendar.py tests/test_policy*.py tests/test_propfirm_policy_foundations.py`. Rapport : `python scripts/report_policy_quality.py`. Fixtures SYNTHETIC-ONLY : jamais des contrats/admissions réels. Aucun branchement broker, aucune revue des sorties protectrices ni qualification 24/7 déduite d'un PASS logiciel. Maintenir RiskEngine et protections des modes.

---


## Lot PolicyGate sans MT5 (2026-10-08)

Lire `docs/HANDOFF.md`. Le module `src/alladin/challenge/policy_gate.py` et ses tests `tests/test_policy_gate.py` sont maintenant sur main : évaluation pure des ouvertures/sorties/modifications avec firm profile + calendrier, sans exécution. Ne pas prétendre qu'il est activé dans `ExecutionService`. Tests non exécutés dans la session de création. Préférer une batterie de tests déterministes et une revue humaine des sorties protectrices avant intégration OBSERVE/PAPER. Maintenir les protections DEMO/LIVE.

---


Ce fichier complète et ne remplace PAS `docs/HANDOFF.md`, source de vérité opérationnelle. Avant modification : lire `docs/HANDOFF.md`, `docs/DECISIONS/README.md`, puis les décisions concernées et le code existant.

## Priorité 2026-10-08
Lire DECISION-031, DECISION-032, DECISION-033, DECISION-034 et DECISION-035.

Fondations déjà livrées : `src/alladin/challenge/event_policy.py`, `firm_policy.py`, `capital_metrics.py`, tests `tests/test_propfirm_policy_foundations.py`.

**Ne pas annoncer une intégration qui n'existe pas :** calendrier réel non ingéré, conformité non branchée au runtime, multi-firmes non connectées, autonomie 24/7 non certifiée. La suite de tests de ce lot nécessite une exécution locale/CI ; ne jamais falsifier PASS.

## Prochain développement
1. Exécuter les tests, lint, typage des modules du lot, corriger toute défaillance.
2. Construire des adaptateurs de calendrier avec timestamps de disponibilité et provenance, expirations, DST, révisions et données replayables sans lookahead.
3. Construire les profils spécifiques aux comptes **depuis les contrats officiels** ; revalidation périodique obligatoire.
4. Brancher ComplianceGate + EventPolicy pour entrée ET gestion/fermeture de positions, en distinguant impérativement restrictions d'annonce et sorties de protection. En l'absence de profil ou calendrier fiable : bloquer les nouvelles entrées ; pour les positions existantes, protéger selon les obligations broker/firme et alerter.
5. Tester scénarios et modes OBSERVE/PAPER/MT5 DEMO, redémarrages, fills et annulations. Aucune promotion LIVE automatique.
6. Scorecards et Mission Control ensuite ; préserver Jafar, SNN-X et tout code non concerné.

## Invariants
- RiskEngine déterministe toujours souverain.
- L'algorithme ne modifie jamais les règles de firmes ni l'autorisation d'exécution.
- Aucun agent ne doit contourner limitations contractuelles (news trading, EAs, copie, comptes multiples).
- Aucun objectif mensuel +20/+30 % ne justifie de désactiver les garde-fous.
- Commit/push avec tests exacts et statut honnête. Conserver fichiers des autres agents.
