# ALLADIN — Claude Handoff

## Mise à jour autonome sans MT5 — 2026-10-08

Lire `docs/HANDOFF.md`, `AGENTS.md`, décisions 032–035.
Ajout : `src/alladin/challenge/policy_gate.py` et `tests/test_policy_gate.py` (PolicyGate pure, aucune exécution). Combine contexte de firme et macro pour OPEN/CLOSE/PARTIAL_CLOSE/MODIFY_STOP/MODIFY_TARGET/HOLD et retours ALLOW/DEFER/BLOCK/REVIEW. Ne pas confondre avec intégration broker : **non raccordée**.

Avant continuation : `python -m pytest tests/test_propfirm_policy_foundations.py tests/test_policy_gate.py -q`, `python -m ruff check src/alladin/challenge tests/test_policy_gate.py`, `python -m mypy src/alladin/challenge/policy_gate.py`. Aucun PASS déclaré pour ces nouveaux tests. Respecter la restriction FTMO Standard funded sur certaines clôtures au voisinage des annonces ; les sorties protectrices requièrent un arbitrage conforme et une revue spécifique.

---


## Lot 2026-10-08 — décisions 032–035 : fondations implémentées (lecture obligatoire Claude/Codex)

Décisions : [032](DECISIONS/DECISION-032-ECONOMIC-INTELLIGENCE.md) · [033](DECISIONS/DECISION-033-MULTI-PROPFIRM-COMPLIANCE.md) · [034](DECISIONS/DECISION-034-CAPITAL-ENGINE-OBJECTIVES.md) · [035](DECISIONS/DECISION-035-AUTONOMOUS-OPERATIONS-QUALITY.md).

**Code nouveau (fondations seulement)** :
- `src/alladin/challenge/event_policy.py` : événement macro horodaté, snapshot avec fraîcheur, évaluation déterministe BLOCK/DEFER/ALLOW et causality as-of ; fenêtre de précaution expérimentale.
- `src/alladin/challenge/firm_policy.py` : profils versionnés de firme/produit/phase/type de compte, refus si règles périmées, EA interdit, symbole non autorisé ou limite de positions atteinte.
- `src/alladin/challenge/capital_metrics.py` : distinguer capital nominal simulé et cash net effectivement encaissé.
- `tests/test_propfirm_policy_foundations.py` : tests unitaires de politique et comptabilité.

**État véridique** : modules isolés ; PAS de fournisseur de calendrier connecté, PAS d'injection du ComplianceGate/EventPolicy dans ExecutionService, PAS de nouveaux ordres réels ni certification 24/7. Tests ajoutés mais non exécutés depuis cette session distante. Ne pas déclarer de recette MT5 ou de suite complète PASS à partir de ce commit.

**Urgence sécurité / FTMO** : sur FTMO Account Standard, certains événements interdisent **ouverture et fermeture**, y compris déclenchement de SL/TP, de T-2 min à T+2 min ; pas les mêmes contraintes en évaluation ou Swing. Une fermeture automatique durant cette fenêtre peut enfreindre les règles. Lire la source officielle avant d'implémenter des décisions CLOSE : https://ftmo.com/faq/can-i-trade-news/ . Les fenêtres et instruments dépendent de la version du profil. Ne jamais remplacer le RiskEngine déterministe ; pas d'autopromotion LIVE.

**Ordre de réalisation pour Claude/Codex** :
1. Exécuter `python -m pytest tests/test_propfirm_policy_foundations.py -q`, Ruff et mypy ; corriger tout problème identifié avant raccordement.
2. Introduire source fiable/licenciée de calendrier + ingestion auditable (heure de connaissance, retards, révisions, freshness et DST), et firm profiles sourcés. Vérifier les règles officielles **au moment de l'utilisation**.
3. Ajouter un point de contrôle conjoint firm/event avant toute nouvelle entrée et avant les sorties concernées, sans casser les sorties de protection prioritaires ou le watchdog. Un snapshot absent bloque les **nouvelles entrées** ; traiter les sorties existantes séparément selon les conditions applicables et alerter en cas de risque de violation.
4. Ajouter tests intégration, replay as-of, pannes, reboots, weekend, annonces, SL/TP, multi-comptes, Mock/PAPER/DEMO, puis mise à jour Mission Control.
5. Calculer une scorecard de qualité : pertes, drawdown, coûts, refus conformes, données périmées, disponibilité, PnL net encaissé ; vérifier en soak prolongé.
6. Laisser Jafar/SNN-X indépendants et la restriction actuelle DEMO/LIVE inchangée.

**Attention** : les profils des firmes ne sont pas validés par la seule création d'une classe Python. Aucun objectif de rendement mensuel n'est garanti ; les scénarios +20/+30 % post-validation servent à la simulation, pas à une obligation d'exécution.

---

## HEAD
branch: main | SHA: à mettre à jour après le commit final | dernier push: 2026-10-05

Commits du lot Mission Control PAPER + Soak Report :
- c85d920 feat: Jafar Mission Control PAPER mode alignment
- commit final à venir : feat: add Jafar PAPER soak report and validator

## Ce qui vient d'être terminé

**Lot 5 — Mission Control PAPER cohérence + Soak Report/Validator**

### RC1 — run_mode N/A (app.py)
- `app.py` `/health` : requête `"jafar.mode.change"` pour JAFAR (pas `"mode.change"`)
- Lit `payload["to"]` au lieu de `payload["run_mode"]`

### RC2 — Banner "OBSERVE ONLY" incorrect (index.html)
- Nouveau champ `live_locked = True` pour JAFAR dans `/health`
- `observe_only = live_locked and run_mode not in ("PAPER", "TESTNET")`
- Banner JS branché sur `live_locked` + `run_mode` → affiche "PAPER SIMULÉ" ou "OBSERVE"

### RC3 — DEGRADED persist
- Comportement by design (fail-safe). Non modifié.

### jafar report
- `jafar report --broker X --run RUN-XXX` : JSON read-only
- Champs : run_id, mode, cycles, health_transitions, current_health_status,
  provider_failures, max_consecutive_failures, stale_incidents, opportunities,
  no_trade_count, open_positions, closed_trades, realized_pnl, unrealized_pnl,
  total_fees, drawdown_pct, outcomes, journal_integrity, duplicate_anomalies

### jafar validate-paper
- `jafar validate-paper --broker X --run RUN-XXX [--min-duration-h N]`
- Exit 0=PASS / 1=WARN / 2=FAIL
- Checks : mode_is_paper, journal_integrity, no_duplicates, no_production_write,
  health_not_failed, cash_non_negative, heartbeat_progressed (≥2=PASS),
  market_progressed, min_duration (si fourni)

### Tests
- `tests/test_jafar_paper_mc_coherence.py` : 17 tests
- `tests/test_jafar_soak_report.py` : 13 tests — **tous verts**
- Suite complète : **937 passed, 3 skipped (MT5)**

## État réel

| Fonctionnalité | État |
|---|---|
| PAPER end-to-end | OUI |
| Mission Control run_mode / live_locked | OUI |
| Banner mode-aware PAPER vs OBSERVE | OUI |
| jafar report (JSON read-only) | OUI |
| jafar validate-paper (exit 0/1/2) | OUI |
| Tests soak report + MC coherence | OUI (28 tests) |
| Linux/systemd packaging | OUI |
| Long-run réelle (24/7) | NON VALIDÉE |
| Déploiement serveur réel | NON DÉPLOYÉ |
| TESTNET validation réelle | NON |
| LIVE | NON |
| docs/PAPER_SOAK_RUNBOOK.md | CRÉÉ |

## Fixes techniques notables

### WinError 32 (SQLite Windows lock)
- **Cause** : SQLAlchemy engine garde le fichier SQLite ouvert sous Windows
- **Fix** : API `JournalRepository.close()`, fermeture des commandes read-only et fermeture avant exception `run introuvable`
- **Pattern** : context manager `_db_ctx(settings)` qui ferme puis supprime sans masquer `OSError`
- **Ne pas** masquer avec `try/except OSError` silencieux — dispose explicitement

### make_broker vs CryptoObserveBroker direct
- `CryptoObserveBroker(CryptoMockProvider())` → `provenance="crypto:mock"`
- `make_broker("crypto-mock", settings)` → `provenance="crypto:crypto-mock"`
- Les deux ne correspondent pas → binding check échoue au resume
- **Fix** : tests utilisent `make_broker("crypto-mock", settings)` identique au CLI

### validate-paper WARN vs PASS
- 1 seul heartbeat → `heartbeat_progressed = WARN` (threshold = 2)
- `--min-duration-h 2.0` sur run de quelques secondes → FAIL intentionnel
- Ne pas tricher : validation structurelle ≠ qualification durée

## Fichiers clés

```
src/alladin/orchestration/health.py          # RuntimeHealthTracker
src/alladin/jafar/paper.py                   # JafarPaperRuntime + run_loop()
src/alladin/api/app.py                       # /health live_locked + run_mode fix
src/alladin/api/static/index.html            # Banner mode-aware JS
src/alladin/cli.py                           # jafar report/validate-paper/endurance
src/alladin/core/config.py                   # runtime_stale_after_s, max_failures
deploy/alladin-jafar-paper.service           # unit systemd runtime PAPER
deploy/alladin-jafar-mission-control.service # unit systemd Mission Control
deploy/alladin-jafar.env.example             # template /etc/alladin/jafar.env
deploy/install.sh                            # script d'installation
deploy/verify.sh                             # vérification artefacts
scripts/backup_jafar_db.sh                   # backup SQLite hot
docs/DEPLOY_LINUX.md                         # procédure complète déploiement
tests/test_deploy_artifacts.py               # 38 tests structurels
tests/test_mission_control_health.py         # 12 tests Mission Control health
tests/test_jafar_paper_mc_coherence.py       # 15 tests PAPER mode coherence
tests/test_jafar_soak_report.py              # 13 tests soak report + validator
```

## Validation du lot

- `pytest tests/test_jafar_soak_report.py` : 13 passed, répété 3 fois sans verrou SQLite
- ciblés Mission Control/health/soak : 53 passed
- suite complète : 937 passed, 3 skipped (MT5)
- mypy `src/alladin` : PASS (100 fichiers)
- Ruff fichiers du lot : PASS
- Ruff global : dette préexistante, 15 erreurs dans `tests/test_jafar_execution.py` et `tests/test_jafar_testnet.py`
- `git diff --check` : PASS

## Prochain lot recommandé : long-run 2-4h

### Runbook à créer (docs/PAPER_SOAK_RUNBOOK.md)
Phase 1 — Smoke (15 min) :
1. `python -m alladin jafar new --broker crypto-public`
2. `python -m alladin jafar mode PAPER --broker crypto-public`
3. `python -m alladin jafar run --broker crypto-public --mode PAPER --cycles 10 --interval 30`
4. `python -m alladin jafar validate-paper --broker crypto-public --run RUN-XXX`
5. Vérifier exit 0 ou WARN (pas FAIL)

Phase 2 — Soak (2-4h) :
1. Relancer avec `--cycles 0 --interval 300`
2. Toutes les 30 min : `curl http://127.0.0.1:8002/api/runtime/health`
3. Vérifier `last_market_update_at` avance, `consecutive_failures == 0`
4. `python -m alladin jafar validate-paper --min-duration-h 2.0 --run RUN-XXX`

Phase 3 — Long-run (24h) :
- Uniquement après Phase 2 propre
- SIGTERM propre → STOPPING → STOPPED
- Redémarrage sans duplication

## Commandes de reprise

```bash
git log -5 --oneline
python -m pytest tests/test_jafar_soak_report.py tests/test_jafar_paper_mc_coherence.py -q

# Rapport d'un run
python -m alladin jafar report --broker crypto-public --run RUN-XXX

# Validation acceptance
python -m alladin jafar validate-paper --broker crypto-public --run RUN-XXX --min-duration-h 2.0
```

**Ne pas lancer 24h avant 2-4h de validation propre.**
**Ne pas commencer avant d'avoir lu ce fichier et vérifié que pytest passe.**
