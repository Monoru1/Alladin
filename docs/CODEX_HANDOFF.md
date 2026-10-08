# Alladin — Codex handoff — 2026-10-08

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
