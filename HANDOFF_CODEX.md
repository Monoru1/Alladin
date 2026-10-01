# HANDOFF CODEX — ALLADIN

Lire d'abord `README.md`. Ne PAS reconstruire le projet : le MVP existe et est testé.
Règle absolue : **DEMO uniquement, argent réel interdit, fail closed**. Ne jamais lancer RUN-001 officiel ni d'ordre sans confirmation explicite de l'utilisateur.

## 1. État Git

| | |
|---|---|
| HEAD de départ de cette session | `fdcdcc9` feat: add Mission Control cockpit and research foundations |
| HEAD actuel | `5dab0e4` feat: RunMode daemon, Opportunity model, Research persistence |
| Branche | `main` (suit `origin/main`, poussé) |
| Working tree | propre |
| Non commité par conception | `.env`, `data/`, `.venv/`, `.claude/` |

## 2. Statut des missions

| Mission | Statut | Détail |
|---|---|---|
| A. MT5 réel validé | **DONE** | Compte DEMO MetaQuotes-Demo connecté, lecture seule |
| B. Univers LAB | **DONE** | `config/universes/lab.yaml` — 127 instruments |
| C. Algo Trading guard | **DONE** | `_require_algo_trading()` — exit 6 |
| D. test-order / SYSTEM-TEST | **PARTIAL** | Pipeline complet ; position EURUSD 58707143622 potentiellement encore ouverte |
| E. Réconciliation redémarrage | **DONE** | `sync` command + `PositionMonitor.reconcile()` |
| F. Mission Control cockpit | **DONE** | `api/app.py` + `static/index.html` redesigné |
| G. Research models | **DONE** | `research/models.py` + `research/repository.py` (SQLite) |
| H. MarketDataArchive | **DONE** | `market/archive.py` branché, tests couverts |
| I. cycle_id / observabilité | **DONE** | Tests complets dans `test_observability.py` |
| J. SYSTEM-TEST vs RUN-001 | **DONE** | Isolation parfaite, tests couverts |
| K. RunMode daemon | **DONE** | OBSERVE/PAPER/DEMO, SIGINT propre, `mode.change` journalisé |
| L. Opportunity model | **DONE** | `market/opportunity.py` + `OpportunityStatus` lifecycle |
| M. Research persistence | **DONE** | `ResearchRepository` SQLAlchemy/SQLite complet |
| N. Tests daemon/research | **DONE** | 20 tests dans `test_daemon_modes.py` |
| O. Scanner multi-timeframe | **NOT STARTED** | Scanner actuel : mono-timeframe H1 par défaut |
| P. Paper experiments | **NOT STARTED** | PAPER mode déclaré mais sans simulation interne réelle |
| Q. Research Lab UI enrichi | **PARTIAL** | Affichage sources/findings/versions/résultats mais pas de drill-down |
| R. Opportunity Radar live | **PARTIAL** | Affiché depuis `mkt.candidates` ; pas encore branché sur `Opportunity` model |
| S. Archive stats CLI | **NOT STARTED** | `alladin archive stats` non implémenté |

## 3. Commits de cette session

```
5dab0e4  feat: RunMode daemon (OBSERVE/PAPER/DEMO), Opportunity model, Research persistence
fdcdcc9  feat: add Mission Control cockpit and research foundations  (point de départ)
```

## 4. Architecture ajoutée

### `core/enums.py`
- `RunMode` : `OBSERVE | PAPER | DEMO`

### `journal/models.py`
- `EventType.OPPORTUNITY_CREATED`, `OPPORTUNITY_REJECTED`, `MODE_CHANGE`

### `market/opportunity.py` (nouveau)
- `OpportunityStatus` : `SEEN → FILTERED | WATCH → QUALIFIED → AGENT_REVIEW → RISK_REVIEW → EXECUTED | REJECTED | PAPER | EXPIRED`
- `Opportunity` pydantic model avec `to_journal()`

### `orchestration/engine.py`
- `run_mode: RunMode` remplace `execute: bool` (legacy conservé)
- `run_loop(..., handle_signals=True)` : SIGINT/SIGTERM → `_stop_requested = True`, arrêt propre après le cycle en cours
- Journalise `EventType.MODE_CHANGE` au démarrage

### `orchestration/bootstrap.py`
- `engine(agent, *, execute=False, run_mode=RunMode.OBSERVE)`

### `cli.py`
- `run --mode OBSERVE|PAPER|DEMO` (remplace `--execute`, compat maintenue)

### `research/repository.py` (nouveau)
- `ResearchRepository` : SQLAlchemy/SQLite
- Tables : `research_sources`, `research_findings`, `research_hypotheses`, `research_strategy_versions`, `research_experiments`, `research_experiment_results`
- Opérations : save/get/list pour chaque entité, `update_status()`, `stats()`
- Idempotent (ON CONFLICT DO NOTHING pour les entités immuables)

### `api/app.py`
- `/api/research` retourne maintenant les données réelles du `ResearchRepository`

### `api/static/index.html` (redesigné)
- **Control** : Account/Equity, Challenge (barre de progression), Live Positions, Risk Map, Opportunity Radar, Brain Trace lisible (événements humains + raw details), Market Activity, Journal Integrity
- **Strategy Lab** : tableau complet avec N/A explicite
- **Research Lab** : pipeline, sources, findings, versions, expériences+résultats
- Polling fast 2s (control) / slow 30s (research)

## 5. Commandes

```bash
# Démarrage daemon
python -m alladin run --broker mt5 --mode OBSERVE        # par défaut
python -m alladin run --broker mt5 --mode PAPER
python -m alladin run --broker mt5 --mode DEMO           # confirmation requise

# Mission Control
python -m alladin serve --broker mt5 --port 8001

# Réconciliation
python -m alladin sync --system-test

# Tests
python -m pytest -o addopts="" tests                     # 189 passed, 3 skipped
python -m pytest -o addopts="" --run-mt5 tests           # avec terminal MT5
python -m ruff check src tests
python -m mypy src
```

## 6. État MT5 / SYSTEM-TEST-001

**Dernière info connue (session précédente 2026-09-30) :**
- Terminal MT5 connecté, compte DEMO MetaQuotes-Demo, balance 100 000 EUR
- Algo Trading : DÉSACTIVÉ au moment de la dernière session
- Position EURUSD BUY 0.01 lot, ticket 58707143622, trade_id 2924d4e184ca
  - Entry 1.13313 | SL 1.13113 | TP 1.13713
  - Statut : **INCONNU** — peut être ouverte, SL/TP atteint, ou expirée
  - À réconcilier via `python -m alladin sync --system-test`

**À ne jamais faire :**
- Fermer la position 58707143622 manuellement
- Lancer RUN-001 officiel
- Envoyer un ordre sans `EXECUTE` explicite

## 7. Résultats tests

```
pytest:   189 passed, 3 skipped (3 = mt5_integration sans --run-mt5)
ruff:     All checks passed!
mypy:     Success: no issues found
```

## 8. Travail restant — prochaines priorités

### PRIORITÉ A (à faire maintenant)

**A1 — Réconcilier SYSTEM-TEST après position fermée**
La position 58707143622 a peut-être atteint SL/TP. À faire :
```bash
python -m alladin sync --system-test
```
Si la position est fermée, `PositionMonitor.reconcile()` doit :
- récupérer l'historique broker (deals)
- calculer P&L, R, raison (SL/TP/manual)
- journaliser `position.closed`
- passer le trade 2924d4e184ca en CLOSED

**Tests à ajouter :** `test_closed_position_reconciliation_via_broker_history()`

**A2 — Scanner multi-timeframe**
Actuellement : `market/scanner.py` utilise H1 (ou une seule tf)
Action : étendre le scanner pour itérer sur plusieurs timeframes (M5, M15, H1, H4, D1)
avec fréquences différentes par timeframe. Configurable dans `UniverseRules`.

**A3 — Brancher Opportunity model dans le pipeline**
Actuellement : `Opportunity` model existe mais n'est pas utilisé dans `engine.py` / `scanner.py`
Action : créer des `Opportunity` à partir des `ScanReport.candidates` et les journaliser
avec `EventType.OPPORTUNITY_CREATED` / `OPPORTUNITY_REJECTED`

**A4 — `alladin archive stats` CLI**
```bash
python -m alladin archive stats   # affiche MarketDataArchive.stats()
```

### PRIORITÉ B

**B1 — PAPER mode : simulation interne**
Mode PAPER déclaré mais identique à OBSERVE. Implémenter la simulation :
- suivre les trades paper avec les prix réels
- calculer P&L simulé
- journaliser séparément (pas dans le run live)

**B2 — Research Lab : drill-down stratégie**
Permettre de naviguer : `StrategyVersion → StrategyHypothesis → ResearchFinding → ResearchSource`

**B3 — `ResearchRepository` partagé avec `JournalRepository.engine`**
Actuellement `/api/research` crée `ResearchRepository.from_engine(repo.engine)` → les tables
research sont dans la même DB SQLite que le journal. C'est correct. Vérifier que `alladin run`
le fait aussi.

### PRIORITÉ C

**C1 — Dashboard : Opportunity Radar live**
L'Opportunity Radar affiche `mkt.candidates` (les survivants du scan). Il faudrait
aussi afficher les `Opportunity` créées avec leur statut (QUALIFIED, REJECTED, etc.)
via un endpoint `/api/opportunities?run_id=&cycle_id=`.

**C2 — Brain Trace : filtrage par cycle**
Ajouter un sélecteur de cycle dans le dashboard pour filtrer les événements.

**C3 — Health endpoint enrichi**
`/health` actuel : basique. Ajouter : `run_mode`, `last_cycle_at`, `engine_running`.

### PRIORITÉ D

**D1 — Backtest runner**
`StrategyExperiment` existe, `ExperimentResult` existe, mais aucun runner de backtest.
Créer `research/backtest.py` avec un runner simple sur `MarketDataArchive`.

**D2 — Replay enrichi**
`replay cycle <id>` existe mais ne charge pas les bars archivés.
Brancher `MarketDataArchive.load(symbol, tf)` pour `cycle_inputs`.

## 9. Points d'attention pour Codex

- `RunMode.DEMO` → `execute=True` dans le moteur (compatibilité maintenue)
- `signal.signal` n'est pas testable directement : le test utilise `_stop_requested = True` directement
- `ResearchRepository` utilise la même `Engine` SQLAlchemy que `JournalRepository` (même fichier SQLite)
- Le dashboard poll à 2s pour le contrôle et 30s pour research (séparé intentionnellement)
- `handle_signals=False` dans les tests pour éviter la capture des signaux pytest
- Les apostrophes dans les heredocs bash plantent sur ce système — utiliser Python pour écrire des fichiers complexes

## 10. Commandes de reprise

```bash
cd ~/Alladin
git log --oneline -5
python -m pytest -o addopts="" tests   # 189 passed, 3 skipped attendus
python -m ruff check src tests && python -m mypy src
python -m alladin mt5 status           # vérifier terminal + Algo Trading
python -m alladin sync --system-test   # réconcilier la position EURUSD
python -m alladin run --broker mt5 --mode OBSERVE --cycles 1  # un cycle test
python -m alladin serve --broker mt5 --port 8001              # cockpit
```
