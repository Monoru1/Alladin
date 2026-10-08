# Alladin — Codex handoff — 2026-10-08

## Lot autonome 2 — 2026-10-08 : calendrier causal et conformité simulée

`economic_calendar.py` : ingestion JSON offline validée (schéma/version, provenance/licence explicites, heure de disponibilité ET collecte, valeurs finies, révisions monotones), snapshots complets et replay selon réception. Dernier refresh périmé conservé : aucun fallback permissif. Horodatages normalisés UTC pour éviter les comparaisons ambiguës pendant le DST. Aucune connexion fournisseur.
Fixtures `tests/fixtures/policy/firm_profiles.json` : **SYNTHÉTIQUES UNIQUEMENT**, six variantes phase/type/automatisation/news/limite. Aucun contrat réel vérifié ni support d'une firme déclaré. Un profil portant `restrict_news` ne peut être contredit par le contexte appelant.

Validation : `python -m pytest -o addopts='' -q tests/test_economic_calendar.py tests/test_policy*.py tests/test_propfirm_policy_foundations.py` : **361 passed** ; Ruff fichiers du lot : PASS ; mypy challenge : PASS (10 fichiers) ; diff --check : PASS. Couvre limites ±2 min et précaution, pannes de calendrier, profils périmés/futurs, isolation de contextes, sérialisation/restart, révisions retardées et DST. Tests unitaires/simulation seulement ; pas de fills ni recette broker dans ce lot.

Limites : calendrier complet déclaré par le fournisseur mais couverture non certifiée, association événement/symbole à fournir, pas de validation indépendante des sources/licences ; weekends, overnight, copy trading, trailing drawdown et exposition multi-comptes non modélisés par PolicyGate. Sorties protectrices/SL/TP broker toujours à revoir ; aucun raccordement au runtime, aucun LIVE ni qualification 24/7.

---


## Lot autonome 1 — 2026-10-08 : validation PolicyGate

Base reprise : `a5073c7` sur main. Tests initiaux : 14 passed. Après durcissement :
`python -m pytest -o addopts='' -q tests/test_policy_gate.py tests/test_propfirm_policy_foundations.py tests/test_policy_gate_validation.py` : **51 passed**.
Ruff modules challenge + ces trois fichiers : PASS ; mypy challenge : PASS (9 fichiers), mypy global : PASS (104 fichiers) ; diff --check : PASS.
Ruff global : 15 erreurs préexistantes dans les tests Jafar execution/testnet, non attribuées au lot.

Actions inconnues bloquées ; horloge/contexte invalides et automatisation interdite escaladent la gestion des positions en REVIEW (OPEN bloqué). Les montants non finis, symboles ambigus et révisions dupliquées dans un snapshot sont rejetés. HOLD reste sans transaction. Aucun branchement à ExecutionService ni changement des modes/risques. La suite globale est en cours ; aucun PASS global déclaré à ce stade.
Suite : calendrier causal et fixtures synthétiques ; revue des sorties protectrices, contrats réels, source licenciée, intégration OBSERVE/PAPER, MT5 DEMO et endurance restent nécessaires.

---


## Complément 2026-10-08 — lot sans MT5

`src/alladin/challenge/policy_gate.py` et `tests/test_policy_gate.py` viennent d'être ajoutés sur main. Moteur déterministe composé, entrée ET clôture, avec statut REVIEW pour opérations non sûres sur une position existante. Aucun ordre broker, pas de branchement au runtime, tests encore à exécuter. Commencer par lint/typecheck/pytest puis revue des sorties protectrices et historique as-of avant raccordement de la politique.

---


Lire en priorité : `AGENTS.md`, `docs/HANDOFF.md`, `docs/DECISIONS/README.md`, DECISION-031 à DECISION-035.

## Livré sur main
- `challenge/event_policy.py` : évaluateur macro déterministe fondé sur calendrier injecté (aucun réseau ou ordre).
- `challenge/firm_policy.py` : profil de conformité versionné et gate d'entrée pur.
- `challenge/capital_metrics.py` : cash réellement encaissé vs allocation simulée.
- `tests/test_propfirm_policy_foundations.py` : contrats unitaires à exécuter.
- Handoffs `docs/HANDOFF.md` et `docs/CLAUDE_HANDOFF.md` mis à jour.

## Ce qui reste à faire
Tests locaux non exécutés par l'agent GitHub distant ; intégrer source économique fiable, profil de règles par compte, branchement dans la chaîne d'exécution, gestion des sorties conforme, journaux, observabilité, recette MT5 DEMO et endurance.

## Règle FTMO à ne pas rater
FTMO Standard funded : restriction de certaines ouvertures ET fermetures, y compris SL/TP, dans la fenêtre ±2 minutes des publications sélectionnées. L'évaluation et Swing ont des règles différentes. Source officielle : https://ftmo.com/faq/can-i-trade-news/. Les droits d'automatisation et conditions des autres firmes doivent être vérifiés avant intégration.

## Commandes proposées
```bash
python -m pytest tests/test_propfirm_policy_foundations.py -q
python -m ruff check src/alladin/challenge/event_policy.py src/alladin/challenge/firm_policy.py src/alladin/challenge/capital_metrics.py tests/test_propfirm_policy_foundations.py
python -m mypy src/alladin/challenge/event_policy.py src/alladin/challenge/firm_policy.py src/alladin/challenge/capital_metrics.py
```
Respecter la frontière OBSERVE/PAPER/DEMO et préserver Jafar + SNN-X.
