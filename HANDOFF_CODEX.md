# HANDOFF CODEX — ALLADIN

Lire d'abord `README.md` et `docs/ARCHITECTURE.md`. Ne PAS reconstruire le projet : le MVP existe et est testé.
Règle absolue : **DEMO uniquement, argent réel interdit, fail closed**. Ne jamais lancer de RUN-001 officiel ni d'ordre sans confirmation explicite de l'utilisateur.

## 1. État Git

| | |
|---|---|
| Commit de départ de cette mission | `b73ed45` (MVP) |
| Commit de travail | `c03e677` — `feat: extend Alladin lab observability and MT5 validation` |
| HEAD | `c03e677` + le commit `docs: add Codex handoff` (ce fichier) — voir `git log -3` |
| Branche | `main` (suit `origin/main`) |
| Working tree | propre après le commit du handoff ; rien de volontairement non commité |
| Non commité par conception | `.env`, `data/` (base SQLite, kill switch), `.venv/` — tous dans `.gitignore` |

## 2. Statut de la mission précédente

| Mission | Statut | Détail |
|---|---|---|
| A. Valider MT5 réel | **DONE** | `mt5 status`, `pytest --run-mt5`, `market scan` exécutés pour de vrai (voir §4) |
| B. Univers de marché (LAB) | **DONE** | `config/universes/lab.yaml` ; exotiques + métaux admis ; filtrage au scanner |
| C. Algo Trading | **DONE** | `_require_algo_trading()` dans `cli.py` : arrêt (exit 6) avant tout envoi, message exact demandé. **Algo Trading est ENCORE désactivé dans le terminal** (à l'utilisateur de l'activer) |
| D. Premier ordre `test-order` | **PARTIAL** | Code prêt (récap complet, `EXECUTE`, vérification `positions_get`). **Aucun ordre n'a été envoyé** (Algo Trading off + pas de confirmation utilisateur). Jamais testé contre le vrai MT5 jusqu'à `order_send` |
| E. Redémarrage / réconciliation | **PARTIAL** | Commande `sync` ajoutée + `PositionMonitor.reconcile()` testé en simulation ; pas testé sur une vraie position MT5 |
| F. Dashboard / cockpit web | **NOT STARTED** | Seule l'API lecture seule du MVP existe (`api/app.py`) ; `serve` inchangé. Les données nécessaires (cycle_id, SCAN détaillé…) sont maintenant journalisées |
| G. Research Lab (modèles) | **NOT STARTED** | Aucun fichier `research/` |
| H. MarketDataArchive | **PARTIAL** | `market/archive.py` écrit et branché au scanner via `Components.engine()` ; **aucun test dédié**, jamais exécuté sur MT5 réel ; `market scan` (CLI) n'archive pas |
| I. cycle_id / observabilité | **PARTIAL** | Implémenté (journal, trades, moteur, hash) ; **aucun test dédié** ; endpoints API par cycle absents |
| J. SYSTEM-TEST vs RUN-001 | **DONE** | `kind` RUN / SYSTEM-TEST ; `test-order` n'utilise que SYSTEM-TEST ; test qui vérifie qu'aucun RUN n'est créé |
| K. Validation | **PARTIAL** | pytest/ruff/mypy verts (§4) mais tests des nouveautés (archive, cycle_id, migration, scanner durci, `sync`, `watchdog.report`) à écrire |
| L. Commit | **DONE** | `c03e677` poussé |

## 3. Modifications (commit `c03e677`)

**Créés** : `config/universes/lab.yaml`, `config/universes/conservative.yaml`, `src/alladin/market/archive.py`, `HANDOFF_CODEX.md`.

**Modifiés** : `config/challenge_profiles/ftmo_2step_demo.yaml` (`universe_ref: lab`), `challenge/models.py`, `challenge/profiles.py`, `challenge/watchdog.py`, `cli.py`, `execution/service.py`, `journal/models.py`, `journal/repository.py`, `journal/service.py`, `market/models.py`, `market/scanner.py`, `orchestration/bootstrap.py`, `orchestration/engine.py`, `orchestration/state.py`, `tests/test_cli.py`, `tests/test_market.py`, `tests/test_orchestration.py`.

**Migration** (automatique, `JournalRepository._migrate`, SQLite `ALTER TABLE ADD COLUMN`) : `runs.kind` (défaut `'RUN'`), `journal_events.cycle_id`, `trades.cycle_id`. Hash du journal : `cycle_id` ajouté à la chaîne **seulement s'il est non nul** (compatible avec les anciens événements). Nouvelles tables (créées par `MarketDataArchive`) : `market_bars`, `cycle_inputs` (+ triggers d'immuabilité sur `market_bars`).

**Nouvelles commandes CLI** : `python -m alladin sync [--run ID] [--system-test]` ; `runs new --system-test` ; `challenge status` affiche désormais positions ALLADIN chez MT5 + état du journal (`_print_run_positions_and_journal`) ; `mt5 status` affiche marge utilisée, « Trading autorisé », message Algo Trading.

**Nouveaux endpoints** : aucun.

**Nouveaux modèles / API internes** :
- `UniverseRules.id/description`, `ChallengeProfile.universe_ref`, `load_universe()` ;
- `RunRecord.kind`, `TradeRecord.cycle_id`, `JournalEvent.cycle_id` ;
- `EventType.STRATEGY_EVAL / CYCLE_START / CYCLE_END` ;
- `JournalService.current_cycle` (appliqué automatiquement par `log()`), `JournalRepository.cycles(run_id)`, `events(..., cycle_id=)` ;
- `WatchdogReport.daily_pnl / daily_drawdown_pct / total_drawdown_pct / max_drawdown_pct`, `WatchdogState.max_drawdown_amount`, `ChallengeWatchdog.report()` (lecture seule) ;
- `ScanReport.summary()` détaillé (candidats : régime, biais, score, spread, spread/ATR, ATR, session), `ScanReport.cycle_id/archived_bars` ;
- `MarketScanner.scan(limit=, cycle_id=, max_trade_risk=)` : nouveaux rejets « tick de mauvaise qualité », « spécifications inexploitables », « sizing : volume minimum > plafond » ;
- `RunManager.create_run(..., kind=)`, `latest_run_id(kind="RUN")`, `build_services(..., run_kind=)`.

**Tests modifiés** (adaptés à l'univers LAB, aucun supprimé) : `test_market.py` (LAB + profil `conservative`), `test_orchestration.py`, `test_cli.py` (SYSTEM-TEST). **Aucun test nouveau pour archive/cycle_id/migration/sync/report** → à écrire.

## 4. Dernier état MT5 connu (session du 2026-09-30)

- Terminal MT5 build 5836 (MetaQuotes Ltd.) **CONNECTÉ** ; compte **DEMO** (login masqué `*******927`), serveur `MetaQuotes-Demo`, devise **EUR**, levier 1:100.
- Balance 100 000 € ; equity 100 000 € ; marge utilisée 0 € ; marge libre 100 000 € ; P&L flottant 0.
- **Algo Trading : DÉSACTIVÉ** (`terminal_info().trade_allowed == False`, « Trading autorisé (compte): NON`). → tout `test-order` s'arrête avec : « Activez Algo Trading dans MetaTrader 5 puis relancez cette commande. » (exit 6).
- Décalage horloge serveur/UTC : **+3 h (auto-détecté)**.
- 12 363 symboles découverts ; univers LAB : **127** instruments (92 FOREX_EXOTIC, 6 JPY, 7 MAJOR, 15 MINOR, 7 METAL). Avant correctif, l'univers prudent donnait 28 paires.
- `market scan` (LAB) : **95 analysés** ; régimes `RANGE 30, TREND 9, LOW_VOLATILITY 8, HIGH_VOLATILITY 2, REVERSAL_CONTEXT 1`. Les 15 symboles qui n'avaient « aucun tick » avant le correctif sont maintenant récupérés (28/28 analysés en univers prudent).
- Positions ouvertes : **0**. **Aucun ordre de test envoyé. Aucune position. Aucun RUN officiel créé.** (Les vérifications « pipeline réel » ont été faites dans une base jetable hors dépôt ; `data/alladin.db` locale peut exister mais ne contient aucun run.)
- Ordre de test éventuel : jamais exécuté.

## 5. Résultats EXACTS des dernières exécutions

```text
pytest:            156 passed, 3 skipped in 7.54s   (les 3 skipped = tests/integration/test_mt5_live.py)
pytest --run-mt5:  159 passed in 7.72s              (terminal MT5 connecté, compte DEMO, lecture seule)
ruff check src tests:  All checks passed!
mypy src:              Success: no issues found in 63 source files
```
(Invocation utilisée : `python -m pytest -o addopts="" tests [--run-mt5]` pour voir la ligne de synthèse.)

## 6. Travail restant (checklist)

Ordre recommandé ; toujours **sans** envoyer d'ordre sans `EXECUTE` de l'utilisateur.

**Tests des nouveautés (priorité 1)**
- [ ] `tests/test_observability.py` : `cycle_id` sur les événements d'un cycle (`OrchestrationEngine.run_cycle`, `JournalService.current_cycle`), sur `trades.cycle_id` (`ExecutionService.submit`), couvert par `verify_chain` ; `repo.cycles()` ; `repo.events(cycle_id=)`.
- [ ] Archive : `MarketDataArchive.store/load/cycle_inputs/stats` — pas de doublon au 2ᵉ appel, incrémental, immuabilité (triggers), branchement via `Components.engine()` (le `ScanReport.archived_bars > 0` au 1ᵉʳ cycle, 0 au 2ᵉ). Fichier : `src/alladin/market/archive.py`.
- [ ] Migration : créer une base avec l'ancien schéma (sans `kind`/`cycle_id`), ouvrir avec `JournalRepository`, vérifier `ALTER` + hash chain d'anciens événements. Fonction : `JournalRepository._migrate`.
- [ ] Runs : `create_run(kind="SYSTEM-TEST")` → `SYSTEM-TEST-001`, magic ≠ RUN-001, `latest_run_id(kind="RUN")` ignore les SYSTEM-TEST. Fichier : `orchestration/state.py`.
- [ ] Scanner durci : rejets « tick de mauvaise qualité », « spécifications inexploitables », « sizing » (param `max_trade_risk`). Fichier : `market/scanner.py`.
- [ ] CLI `sync` et `challenge status` (section positions/journal) avec `FakeMT5` ; `test-order` qui s'arrête (exit 6) quand `terminal_info.trade_allowed=False` — **FakeMT5 renvoie toujours `trade_allowed=True` : ajouter un paramètre** dans `tests/fake_mt5.py`.
- [ ] `ChallengeWatchdog.report()` (pas d'effet de bord) + `daily_pnl`, `daily_drawdown_pct`, `max_drawdown_pct` dans `tests/test_watchdog.py`.
- [ ] `load_profile` avec `universe_ref` (profil inexistant, `universe` + `universe_ref` exclusifs) dans `tests/test_market.py`.

**MT5 réel (nécessite l'action de l'utilisateur)**
- [ ] L'utilisateur active **Algo Trading** dans MT5 (bouton de la barre d'outils).
- [ ] `python -m alladin mt5 test-order` (run SYSTEM-TEST-001) → l'utilisateur tape `EXECUTE` → vérifier retcode/deal/position via `positions_get`.
- [ ] Test de redémarrage (mission E) : relancer `python -m alladin sync --system-test` dans un nouveau processus ; la position doit être reconnue (magic + commentaire `ALLADIN|SYSTEM-TEST-001|TEST-00`) et NON fermée. Ajouter un test `mt5_integration` dans `tests/integration/` (ne jamais envoyer d'ordre automatiquement).
- [ ] Vérifier sur données réelles que `run` (dry-run) produit un cycle avec `cycle_id` et que l'archive se remplit (`MarketDataArchive.stats()`).
- [ ] Vérifier le comportement du scan LAB : exotiques/métaux rejetés par spread/ATR ou sizing (inspecter `rejected` du `ScanReport`).

**Cockpit web (Mission F — NOT STARTED)** — fichiers : `src/alladin/api/app.py` (+ nouveau dossier statique, ex. `src/alladin/api/static/index.html`), `cli.py::serve`.
- [ ] Endpoints **GET uniquement** : `/api/overview?run_id=`, `/api/runs/{id}/cycles` (utiliser `JournalRepository.cycles`), `/api/runs/{id}/cycles/{cycle_id}` (utiliser `events(cycle_id=)`), positions ALLADIN ouvertes, exposition (`risk.exposure.compute_exposure`), dernier SCAN / AGENT / STRATEGY_EVAL / RISK_DECISION / ORDER_*.
- [ ] Données de compte live : lecteur MT5 en lecture seule optionnel (`serve --broker mt5`) ; sinon dernier `account.snapshot` du journal. **Aucun endpoint d'envoi d'ordre.**
- [ ] Page HTML unique (JS sans build) servie à `/` : sections ACCOUNT, CHALLENGE, RISK, MARKET, AGENT, STRATEGY, EXECUTION, POSITIONS, JOURNAL (timeline filtrable par cycle) — cf. cahier des charges du prompt de la Mission F. Utiliser `ChallengeWatchdog.report()` pour la section CHALLENGE (jours restants, meilleur jour, consistency).
- [ ] Tests `fastapi.testclient` : lecture seule (aucune route POST/PUT/DELETE), `/` renvoie du HTML.

**Research Lab (Mission G — NOT STARTED)** — nouveau package `src/alladin/research/`.
- [ ] Modèles pydantic : `ResearchSource`, `ResearchFinding`, `StrategyHypothesis`, `StrategyExperiment`, `StrategyVersion` (source URL, date, description, hypothèse, paramètres, parent, **hash du code**, résultats), `ExperimentResult` ; cycle de vie `SOURCE → HYPOTHÈSE → FORMALISATION → IMPLÉMENTATION → BACKTEST → OUT-OF-SAMPLE → DEMO → KEEP/MUTATE/KILL`.
- [ ] Dépôt SQLAlchemy (tables append-only, versions immuables) + tests. Pas de crawler.
- [ ] Lier `StrategyVersion` au `StrategyRegistry` (`strategies/registry.py`) sans casser `strategy_id`/`strategy_version` déjà journalisés.

**Archive / replay (suite de H)**
- [ ] Faire archiver aussi par `market scan` (CLI) si souhaité ; ajouter `alladin archive stats`.
- [ ] Préparer un lecteur de replay qui recharge `cycle_inputs` + `market_bars` pour un `cycle_id` (non implémenté).

**Avant tout RUN-001 officiel (Mission J)** — ne PAS démarrer avant : MT5 réel validé (test-order + sync), journal validé, dashboard fonctionnel, archive fonctionnelle, audit RiskEngine, vérification des règles FTMO (`docs/CHALLENGE_RULES.md` : valeurs « officielles » = modélisation de travail à confronter aux règles en vigueur), pipeline agent validé avec `--agent claude|codex`.

## 7. Dernière opération (au moment de l'arrêt)

Je venais de terminer, sans feature en cours ni code partiellement implémenté : (1) la correction de typage de `market/archive.py` (`rows: list[dict[str, Any]]`), (2) l'adaptation de `tests/test_cli.py` au run SYSTEM-TEST, puis `ruff`/`mypy`/`pytest` tous verts. La prochaine étape prévue était le **cockpit web (Mission F)** : étendre `api/app.py` (endpoints GET par cycle/overview) et créer la page statique — **non commencée**, aucun fichier partiel. `MarketDataArchive` et `cycle_id` sont implémentés mais sans tests dédiés (voir checklist).

## 8. Points d'attention pour Codex

- Les heredocs `cat <<EOF` contenant des apostrophes plantent dans l'outil Bash de la session précédente : écrire les fichiers avec un outil d'édition.
- Un hook utilisateur bloque les commandes contenant `rm -rf` (« Commande destructive detectee ») : utiliser un répertoire de travail neuf plutôt que supprimer.
- `ClaudeAdapter` est isolé des hooks/plugins utilisateur via `--setting-sources project,local --strict-mcp-config --disable-slash-commands` (sinon les hooks de l'utilisateur font échouer l'appel). Codex : ~50 s par appel.
- Le scanner ajoute les symboles au Market Watch du terminal (nécessaire pour les ticks).
- Les nombres d'instruments dépendent du broker/de l'heure (marché ouvert ou non).
- Format de sortie CLI : Windows, `sys.stdout.reconfigure(utf-8)` en tête de `cli.py`.

## 9. Commandes de reprise

```bash
cd ~/Alladin                       # (ou le clone local)
git pull origin main && git status && git log --oneline -5
python -m venv .venv && .venv\Scripts\activate && pip install -e ".[dev]"     # si nouveau clone
python -m alladin mt5 status                # terminal connecté ? Algo Trading activé ?
python -m pytest -o addopts="" tests        # attendu : 156 passed, 3 skipped
python -m pytest -o addopts="" --run-mt5 tests   # attendu : 159 passed (terminal DEMO connecté)
python -m ruff check src tests && python -m mypy src
python -m alladin market scan               # univers LAB, lecture seule
python -m alladin demo                      # banc d'essai simulé
# Après activation d'Algo Trading PAR L'UTILISATEUR, et seulement avec son accord :
python -m alladin mt5 test-order            # SYSTEM-TEST ; attend le mot EXECUTE
python -m alladin sync --system-test        # redémarrage : position reconnue, non fermée
python -m alladin challenge status --run SYSTEM-TEST-001
```
