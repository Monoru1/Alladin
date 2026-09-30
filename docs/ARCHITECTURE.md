# Architecture

```
MT5 ──► MarketUniverse ──► MarketScanner ──► RegimeClassifier ──► StrategyRouter ──► Strategies
                                                                                         │ signaux
                                                                     AgentAdapter (Claude/Codex/Mock)
                                                                                         │ AgentIntentDraft (sans volume)
                                                        TradeIntent (schéma strict, non fiable)
                                                                                         ▼
 ExecutionService: DEMO check → ChallengeWatchdog → RiskEngine(+PositionSizer) → order_check MT5
                   → order_send → vérification retcode + position réelle → Journal → PositionMonitor
```

Code : `src/alladin/` (layout `src`).

| Package | Rôle |
|---|---|
| `core` | enums, modèles partagés (`TradeIntent`, `InstrumentSpec`…), config, `ApprovalToken`, `KillSwitch` |
| `challenge` | `ChallengeProfile` (YAML), `ChallengeWatchdog`, règles pures |
| `risk` | `RiskEngine`, `PositionSizer`, exposition par devise, corrélations |
| `market` | `MarketUniverse` (découverte dynamique), indicateurs, `RegimeClassifier`, `MarketScanner`, `MarketContextProvider` |
| `strategies` | `Strategy`, `StrategyRegistry` (versions, activation par YAML), `StrategyRouter`, TREND-01 / BREAKOUT-01 / RANGE-01 |
| `agents` | `AgentAdapter`, `MockAgent`, `ClaudeAdapter`, `CodexAdapter` (subprocess) |
| `brokers` | `BrokerAdapter`, `MockBroker`, `MT5Broker` |
| `execution` | `ExecutionService`, identification des ordres |
| `journal` | dépôt SQLAlchemy append-only, `JournalService`, statistiques |
| `orchestration` | `RunManager`, `PositionMonitor`, `OrchestrationEngine`, assemblage (`bootstrap`) |
| `api` | FastAPI **lecture seule** |

## Garde-fous structurels

1. **DEMO only.** `Settings.trading_mode` n'accepte que `demo`. `BrokerAdapter.send_order` (template method, non surchargé par `MT5Broker`, testé) relit le compte **au moment de l'envoi** et exige `AccountType.DEMO`. MT5 : `ACCOUNT_TRADE_MODE_DEMO` uniquement ; réel → `LIVE ACCOUNT DETECTED — EXECUTION BLOCKED` ; concours, inconnu, illisible, login nul, ou serveur dont le nom contredit le mode → `ACCOUNT TYPE UNKNOWN — EXECUTION BLOCKED`.
2. **Jeton d'approbation.** Un broker refuse tout ordre sans `ApprovalToken` valide (émis par le RiskEngine pour l'ouverture, par l'ExecutionService pour la fermeture), frais (60 s), et identique à la requête (symbole, volume). Un ordre d'ouverture sans SL est refusé au niveau broker aussi.
3. **Les agents n'ont aucun accès broker.** `agents/` n'importe ni brokers, ni exécution, ni risque, ni jeton (test AST). Sous-processus : environnement assaini par liste blanche (ni `MT5_*`, ni clés API), cwd temporaire vide.
4. **L'agent ne choisit pas le lot.** `AgentIntentDraft`/`TradeIntent` sont `extra="forbid"` : un champ `volume` est rejeté. `run_id`, agent et expiration sont imposés par l'orchestrateur.
5. **SL obligatoire** : RiskEngine, broker, et contrôle post-exécution (position sans SL ⇒ fermeture d'urgence).
6. **Un envoi n'est pas une exécution** : retcode vérifié, position relue chez MT5, sinon `FAILED`.
7. **Redémarrage** : jamais de fermeture implicite ; `PositionMonitor.reconcile()` rapproche MT5 / base / journal, adopte les positions ALLADIN orphelines, finalise celles clôturées hors-ligne.
8. **Identification** : `magic = 26_000_000 + n° de run` **et** commentaire `ALLADIN|RUN-001|TREND-01`. Une position n'est à ALLADIN que si les deux concordent ; les autres ne sont jamais touchées.

## Journal / audit

SQLite (`data/alladin.db`, migrable PostgreSQL). Tables `journal_events` (append-only, triggers anti UPDATE/DELETE, chaîne SHA-256 par run, vérifiable : `runs verify`), `runs` (un run `PASSED/FAILED/KILLED` est immuable en base), `trades` (un trade `CLOSED` est immuable ; MAE/MFE, R, slippage, spread, commissions, swap, equity après trade). Chaque signal/trade conserve `strategy_id` + `strategy_version`. NO TRADE est journalisé (instruments étudiés, candidats, stratégies évaluées, rejets, agent, décision). Pour PostgreSQL, porter les triggers dans la migration.

## Horloge serveur MT5

Les temps MT5 sont en heure serveur. `MT5Broker` détecte le décalage (≥ 3 majeures concordantes, marché ouvert) ; sinon repli à 0 signalé (`mt5 status`). Forçable via `MT5_SERVER_UTC_OFFSET_HOURS`.

## Replay (préparé, non implémenté)

Le journal contient contexte marché résumé, réponses d'agents, intents et décisions de risque : base d'un futur replay / simulation contrefactuelle. Les barres brutes ne sont pas encore archivées (prochain bloc).

## Limitations connues

- Pas d'ordres en attente (LIMIT/STOP) : architecture prête (`EntryType`, mapping MT5), désactivés dans le RiskEngine.
- Pas de modification SL/TP après ouverture ; une suppression de SL détectée ⇒ fermeture de la position.
- Exposition mesurée en risque-au-SL par devise (simplifiée) ; corrélations : structure + Pearson, non branchées au scanner.
- Pas de source macro/news concrète (interface `MarketContextProvider` seulement).
- Stratégies : 3 implémentées (heuristiques simples, non validées statistiquement).
