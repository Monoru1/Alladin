# ALLADIN — Plan d'implémentation audité

**Audit :** 2026-10-02 · **Base :** `2453208da93f9e789171d196a7cd65e571c3f648` (`main`)
**Portée :** planification seulement ; aucun changement de runtime dans cet audit.
**Autorité :** le code et ses tests établissent l'existant ; les décisions `ADOPTED` de `docs/DECISIONS/` établissent la direction. Une cible documentaire n'est pas une capacité livrée.

## 1. Executive Summary

Alladin est un laboratoire de trading MT5 DEMO doté d'un noyau de sécurité réel : contrôle de compte, RiskEngine, ChallengeWatchdog, sizing, journal chaîné, réconciliation, scanner, trois stratégies et API de lecture. Le backtest et l'archive de barres ont déjà progressé au-delà de la description de `docs/ARCHITECTURE.md`. Le SNN, sa Brain API, l'apprentissage, la promotion contrôlée et les décisions persistantes consultables dans Mission Control restent à construire. La migration conserve les contrats broker/risque/journal et insère progressivement une interface de décision commune à la place du choix agent/routeur comme centre du système.

**Ordre de risque :** (1) rendre fiable le traitement d'une position possédée sans SL, y compris quand le broker refuse la fermeture ; (2) résoudre explicitement le contrat des modes OBSERVE/PAPER et la simulation PAPER ; (3) fiabiliser données, replay et expérience ; (4) brancher un cerveau simple en shadow, puis comparer les candidats SNN sans autoriser leur auto-promotion. Aucun résultat de recherche ne justifie aujourd'hui un trade LIVE ni l'assouplissement d'une protection.

## 2. Current Repository State

- Layout Python `src/alladin`, configuration YAML dans `config/`, tests `tests/`, CLI Typer dans `src/alladin/cli.py`, FastAPI dans `src/alladin/api/app.py`, frontend statique dans `src/alladin/api/static/index.html`.
- Runtime actuel : `BrokerAdapter` MT5/mock ; données crypto publiques et mock dans `brokers/crypto.py` mais **pas** d'adapter d'exécution crypto ; orchestration scanner → régime → stratégies/routeur → `AgentAdapter` → `TradeIntent` → `ExecutionService`/RiskEngine → broker → moniteur/journal.
- Stockage : SQLite via SQLAlchemy, journal append-only et hash par run (`journal/repository.py`), trades/runs, données de recherche (`research/repository.py`), barres OHLCV+spread immuables et références de fenêtres par cycle (`market/archive.py`). `ReplayContext.from_cycle` ne charge que les références et événements (`replay.py`).
- Mode par défaut `OBSERVE`, `PAPER` et `DEMO` exposés par CLI ; `TradingMode` de configuration reste `demo` pour interdire le compte réel. `run` fait **un cycle par défaut** ; la boucle continue et les signaux d'arrêt existent mais pas de service supervisé (`cli.py`, `orchestration/engine.py`).
- État initial Git : `main` aligné avec `origin/main` ; `.claude/` et `.test_tmp/` non suivis étaient déjà présents. Ils ne font pas partie du livrable. Aucune connexion MT5 ni aucun ordre n'a été lancé pendant l'audit.
- Lecture couverte : `docs/HANDOFF.md`, décisions 001–012 et registre, `docs/SNN/`, `docs/SNN_BTC_RESEARCH.md`, tous les fichiers `docs/STRATEGIES/` et `scripts/`, README/documents racine, code `src/alladin/`, configurations, tests et CLI. Les constats suivants concernent ce commit, pas un état historique.

## 3. What Already Works

| Capacité prouvée | Emplacement / limite |
|---|---|
| Blocage de compte non DEMO, jeton d'approbation, SL obligatoire à l'ouverture, précontrôle, vérification de position | `brokers/base.py`, `brokers/mt5.py`, `risk/engine.py`, `execution/service.py`; garder les tests `test_mt5_broker.py`, `test_execution.py`, `test_risk_engine.py`. La récupération d'une fermeture d'urgence refusée est insuffisante (section 21). |
| Profil challenge avec règles officielles séparées des règles expérimentales | `challenge/models.py`, `challenge/watchdog.py`, `config/challenge_profiles/ftmo_2step_demo.yaml`; plafonds actuels volontairement conservateurs. |
| Découverte, filtrage qualité, régimes, stratégies Trend/Breakout/Range | `market/`, `strategies/`, `config/strategies/strategies.yaml`; les signaux ne constituent pas une preuve d'edge. |
| Journal, intégrité et traçage des cycles ; réconciliation des positions possédées | `journal/`, `orchestration/monitor.py`, `replay.py`; `cycle_id`, `JournalEvent.id/seq`, `trade_id`, ownership magic+comment existent. |
| Backtest chronologique avec signal à la clôture puis fill à l'open suivant, spread, gap au SL, règle intrabar prudente | `research/backtest.py`, `tests/test_backtest.py`; simulateur encore distinct du RiskEngine et du vrai portefeuille. |
| Splits chronologiques avec purge/embargo, scorecards, ResearchRepository et lifecycle de version | `research/splits.py`, `scorecard.py`, `repository.py`; la décision `passed` du backtest n'est pas une validation OOS. |
| Cockpit lecture seule avec positions, risque, challenge, radar, journal, Strategy Lab et Research Lab | `api/app.py`, `api/static/index.html`; données historiques en base, mais interface de trace seulement sur 40 événements récents. |
| MockBroker, MockAgent, tests faux MT5 | `brokers/mock.py`, `agents/mock.py`, `tests/fake_mt5.py`; utiles pour expérimenter sans accès broker réel. |

## 4. Decision Compliance Matrix

Statuts : **conforme** = mécanisme présent ; **partiel** = base présente, exigence non couverte ; **cible absente** = choix adopté mais pas codé ; **conflit** = comportement actuel incompatible ou contrat contradictoire.

| Décision ADOPTED | État au commit audité | Preuve et conséquence de migration |
|---|---|---|
| 001 SNN-first | **cible absente** | Aucun SNN/Brain API ; `engine.py` exige `AgentAdapter`, `StrategyRouter` reste décisionnel. Garder ces voies comme contrôle classique, puis brancher Brain API. |
| 002 reuse before rewrite | **conforme en base** | MT5, risque, watchdog, journal, cockpit, stratégies et backtest réutilisables. Aucun remplacement global justifié. |
| 003 deterministic risk | **conforme, couverture à étendre** | `ExecutionService.submit` appelle `RiskEngine` et token ; sorties de position et portefeuille transversal nécessitent des contrats de risque supplémentaires, sans exposer `send_order` au cerveau. |
| 004 multi-broker/canonique | **partiel** | `Tick`, `Bar`, `InstrumentSpec` et `BrokerAdapter` existent ; pas de `CanonicalMarketEvent` ni capacités annoncées. `CryptoDataProvider` fournit de la donnée, pas l'exécution. |
| 005 Strategy Lab | **partiel** | 3 stratégies implémentées et dépôt de recherche ; les autres fiches sont hypothèses. Source/licence/audit leakage et coût ne sont pas des portes imposées partout. |
| 006 no LLM runtime | **partiel** | Le défaut `MockAgent` fonctionne sans LLM, mais `AgentAdapter` est obligatoire et Claude/Codex restent sélectionnables dans la boucle. Le service H24 doit choisir un moteur local sans LLM et échouer fermé. |
| 007 Mission Control | **partiel** | API journal/cycle et positions existent ; pas de fiche décision stable, chart, overlay, reward, replay cliquable. UI remplace les 40 derniers événements. |
| 008 service autonome | **partiel/conflit de mode** | Boucle et arrêt propre existent ; pas de superviseur, checkpoint, heartbeat process, authentification distante. `/health` infère la fraîcheur du dernier cycle (2 min fixes). `OBSERVE/PAPER` peuvent produire une fermeture protectrice malgré « aucun ordre » dans l'aide CLI. Voir décision proposée 013. |
| 009 shared core Jafar | **partiel** | Noyau données/recherche mutualisable ; crypto isolé du `BrokerAdapter` et modèle FX implicite dans univers/sizing/exposition. Aucun transfert de paramètres FX→BTC présumé. |
| 010 no V1/V2 | **conforme au plan** | Une architecture cible ; les étapes ci-dessous sont unités testables/réversibles, pas produits concurrents. |
| 011 cycle multi-position autonome | **partiel** | Plusieurs positions et limites de risque ; `Opportunity` n'évolue pas après QUALIFIED/FILTERED, pas de HOLD/MODIFY/PARTIAL_CLOSE/CLOSE par cerveau. Exposition `RiskContext` limitée aux positions du run ; corrélation provider absent au bootstrap. |
| 012 inspiration BlackRock Aladdin | **partiel** | Journal/risque/exposition unifiés localement ; vue portefeuille inter-runs et scénarios transversaux manquants. Inspiration conceptuelle uniquement, jamais preuve d'efficacité. |

**Décision non tranchée :** `docs/DECISIONS/DECISION-013-MODE-SAFETY.md` est une proposition `PROPOSED` sur les fermetures protectrices en OBSERVE/PAPER ; aucune décision ADOPTED n'est modifiée.

## 5. Documentation vs Implementation Gap Analysis

| Sujet | Statut | Preuve / correction documentaire à prévoir |
|---|---|---|
| DEMO only, SL, risk, watchdog, journal chaîné | **DOCUMENTED + IMPLEMENTED** | `docs/ARCHITECTURE.md`, `src/alladin/brokers/base.py`, `execution/service.py`, `journal/repository.py`. |
| Barres archivées et replay | **OBSOLETE + PARTIAL** | `docs/ARCHITECTURE.md` dit « barres non archivées » ; `market/archive.py` existe. `replay.py` retourne métadonnées/événements, sans barres reconstruites ni ré-simulation. |
| PAPER simulation complète | **CONFLICTING** | `core/enums.py`/aide CLI promettent P&L simulé ; `engine.py:171` appelle `submit(..., dry_run=True)` et `market/paper.py` est isolé. |
| SNN, encoder, reward, surprise, metabolism, connectome, promotion | **DOCUMENTED + MISSING** | `docs/SNN/ALLADIN_SNN_BIBLE.md`, `FLY_BRAIN_FUNCTION.md` décrivent la cible ; aucune implémentation correspondante dans `src/`. |
| Cycle de vie Opportunity et position | **PARTIAL** | `market/opportunity.py` et événements créés ; pas de liaison stable opportunity→proposal→risk→order→position→outcome ; pas d'actions de gestion autonome. |
| Runtime autonome sans LLM | **PARTIAL** | Mock local existe ; CLI LLM optionnelles toujours sur le chemin de décision. Pas de SNN local promu. |
| Cockpit scientifique et décisions persistantes | **PARTIAL** | Journal conserve les événements, API `GET /api/runs/{run_id}/cycles/{cycle_id}` ; la trace UI consomme `/api/journal?limit=40`, sans sélection stable ni chart. |
| Strategy Harvester | **DOCUMENTED + MISSING** | `docs/STRATEGIES/SOURCE_MAP.md`, `scripts/EXTERNAL_SCRIPT_AUDIT.md` ; aucun collecteur/porte de provenance/licence relié à l'exécution. |
| CLI README | **OBSOLETE** | README indique `run [--execute]`; CLI réelle utilise `--mode` et un cycle par défaut (`cli.py`). |
| Index des décisions | **OBSOLETE** | `docs/DECISIONS/README.md` liste 001–010 alors que 011–012 sont ADOPTED ; correction dans ce commit. |
| Capacités du code peu documentées | **IMPLEMENTED, doc PARTIAL** | Archive incrémentale, BTC data provider/expérience, mode PAPER déclaré, `ResearchPerformanceProvider`, endpoints `/api/research` et `/api/opportunities`, run `SYSTEM-TEST`, split `DEMO` figurent dans le code mais pas tous dans les guides racine. |

## 6. KEEP / ADAPT / REFACTOR / REPLACE / REMOVE / NEW

| Classe | Composants | Justification / limite |
|---|---|---|
| KEEP | `MT5Broker` et garde DEMO `BrokerAdapter.send_order`; `RiskEngine`, `PositionSizer`, `ChallengeWatchdog`, `ApprovalToken`, kill switch, ownership magic+comment | Contrats de sécurité éprouvés. Ajouter des contrôles sans affaiblir les limites existantes. |
| KEEP | `JournalRepository`, `RunManager`, `PositionMonitor`, CLI de vérification, MockBroker et tests faux MT5 | Traçage/réconciliation de base utiles ; corriger les défauts ciblés. |
| ADAPT | `Tick`/`Bar`/`InstrumentSpec`, scanner, archive, `ReplayContext`, splits, backtest, scorecards | Ajouter provenance, capacités, intégrité des fenêtres, coûts comparables et replay causal ; préserver API existante tant que possible. |
| ADAPT | 3 stratégies, registre/lifecycle, `ResearchRepository`, `ResearchPerformanceProvider` | Baselines/features/enseignants, jamais preuve automatique ; versionner et imposer preuves de promotion. |
| ADAPT | `api/app.py` et frontend actuel | Conserver cartes positions/challenge/risque/labs ; ajouter historique paginé, fiche stable et graphique. |
| ADAPT | `PaperExperimentEngine`, `CryptoDataProvider` | Simulateur en mémoire non connecté au mode PAPER ; crypto lecture publique non broker de production. |
| REFACTOR ciblé | `OrchestrationEngine` et `bootstrap.py` | Introduire décision locale `Brain API`/`ActionProposal` et shadow sans casser la voie classique ; retirer ensuite l'obligation structurelle `AgentAdapter`. |
| REPLACE progressif | Autorité du `StrategyRouter`/CLI Claude-Codex dans la décision de production | Garder voie classique comme baseline ; la décision promue passe par Brain API et contrôles de risque inchangés. |
| REMOVE | Aucun composant runtime maintenant | Attendre preuves de redondance et tests de migration ; pas de suppression motivée par l'âge du code. |
| NEW | `CanonicalMarketEvent`, capability manifest, normaliseur/encodeur, Brain API, cerveau simple/SNN, outcome/reward, registre de modèles/checkpoints, validateur de promotion, supervision service, détails de décision et replay contrefactuel | Manques avérés par audit. Modules à créer seulement quand le lot correspondant dispose d'un contrat et de tests. |

## 7. Target Architecture

```text
Market/Broker → Adapter + capabilities → Canonical Market Event (temps, source, qualité)
  → archive causale → Features versionnées → Sensory Encoder → Brain API
  → {classique baseline | baseline simple | SNN candidat/promu}
  → ActionProposal (LONG/SHORT/NO_TRADE/HOLD/MODIFY/CLOSE, version, confiance, state_id)
  → Opportunity/position state → deterministic RiskEngine + ChallengeWatchdog
  → ExecutionService → broker DEMO ou simulateur PAPER → PositionMonitor
  → Outcome daté → reward/pain/surprise → replay/learning (boucle lente)

Journal append-only + IDs, métriques, traces et replay : à chaque frontière.
```

Le **FAST PRODUCTION LOOP** ne lit qu'un cerveau promu, gelé et versionné ; il observe, propose, valide, exécute et surveille. L'indisponibilité du cerveau ou de données closes/fraîches donne NO_TRADE et alerte. Le **SLOW LEARNING/PROMOTION LOOP** utilise des snapshots immuables, replay, train/validation/OOS et promotion atomique sous contrôle explicite ; aucune série de pertes ne réécrit les poids actifs. Une décision de gestion de position passe aussi par un contrôle externe de risque et par `ExecutionService`.

Le format canonique exprime des champs réellement observés (bid/ask, OHLC clos, volume, source, horodatage/close time, qualité) et la disponibilité par adapter. Les instruments, unités de prix, contract sizes, tick value, devise de compte, funding et sessions ne sont pas fusionnés par hypothèse. Le RiskEngine reçoit un snapshot portefeuille et des capacités vérifiées ; données/marge/corrélation indisponibles doivent conduire à un comportement explicitement prudent, jamais à une estimation inventée.

## 8. Migration Strategy

1. Poser des tests de sécurité et corriger les défauts P0 sans modifier les limites du profil.
2. Figurer par tests et décision documentaire le sens des modes ; raccorder PAPER au simulateur uniquement après séparation claire de toute voie `order_send` et persistance des positions simulées.
3. Faire de l'archive et du replay une source causale vérifiable ; archiver exactement l'information disponible au moment de décision, avec provenance/version/coûts. Corriger insertion tardive, doublons contradictoires et fenêtres incomplètes.
4. Définir les frontières canonique/Brain API et adapter la voie classique pour produire la même `ActionProposal` que le SNN ; conserver l'ancien chemin comme contrôle et faire tourner d'abord le cerveau en shadow.
5. Ajouter outcome/reward/learning hors runtime, promotion contrôlée, puis UI et service exploitant les événements persistés. Déployer PAPER puis DEMO prolongé seulement avec critères mesurés.

Chaque lot conserve un chemin de retour vers la voie classique, les schémas précédents ou le checkpoint promu précédent. Les nouvelles tables sont additives ; ne jamais modifier l'historique du journal ni réécrire les résultats négatifs.

## 9. Dependency Graph / Ordering

```text
P0 fermeture protectrice + contrat de modes
    ├─→ PAPER persistant et isolé du broker
    └─→ archive causale + replay fidèle ─→ simulateur/coûts/splits comparables
                                             ├─→ outcome/reward datés
                                             └─→ Brain API + baseline classique/simple
                                                     └─→ SNN simple shadow ─→ ablations/connectome
                                                                          └─→ promotion contrôlée
Journal/IDs ─→ API historique/détail/replay ─→ Mission Control enrichi
Heartbeat/checkpoints/reconcile ─→ service supervisé ─→ DEMO prolongé
Provenance/licence ─→ Harvester ─→ Strategy Lab ─→ baselines/enseignants
```

Les travaux UI, service et Harvester peuvent avancer en parallèle lorsque leurs contrats de données sont stabilisés. Les sorties autonomes dépendent du contrat de risque pour chaque action, jamais de la seule disponibilité du cerveau.

## 10. Detailed Implementation Phases

Ce sont des **unités d'implémentation/test/migration** sur une architecture cible unique, sans découpage produit V1/V2. Chaque phase livre un comportement vérifiable et peut être interrompue si son critère échoue.

| Unité | Travail et fichiers/modules probables | Tests nécessaires et critères d'acceptation | Retour arrière |
|---|---|---|---|
| A — sécurité des sorties | `orchestration/monitor.py`, `execution/service.py`, `orchestration/engine.py`, `tests/test_execution.py`, `test_orchestration.py` : détecter à chaque cycle toute position possédée sans SL, même adoptée/non enregistrée ; résultat réel de fermeture, retry/alerte, ne plus affirmer « fermée » sans confirmation. | Faux broker refusant CLOSE puis l'acceptant ; DEMO, restart/reconcile, foreign position ignorée, événements append-only, aucun SL affaibli. Voir paquet final. | En cas de régression, bloquer les nouvelles entrées DEMO, alerter et réconcilier les positions ouvertes avant retour au dernier correctif validé ; ne jamais revenir silencieusement au défaut P0. |
| B — modes et PAPER | `core/enums.py`, `cli.py`, `orchestration/engine.py`, `market/paper.py`, `execution/service.py`, `tests/test_daemon_modes.py`, `test_paper_engine.py` : arbitrer la proposition 013, définir politiques d'ordres par mode, rendre PAPER réellement simulé et persistant, rejouer des positions sur restart. | Tests avec espion `send_order` pour OPEN/CLOSE selon contrat adopté, P&L paper net, crash/restart, aucune contamination du broker. Ne pas assimiler `DRY_RUN_APPROVED` à une exécution. | Revenir à OBSERVE sans simulation ; ne jamais activer DEMO pour « réparer » PAPER. |
| C — données causales et replay | `core/models.py`, `brokers/base.py`, `market/archive.py`, `market/scanner.py`, `replay.py`, `research/splits.py`, `tests/test_research_replay.py`, `test_market.py` : manifeste de capacité adapter, barres closes/temps de disponibilité, provenance, fenêtre complète, doublon contradictoire, insertion tardive, budget de données ; replay en lecture seule avec inputs réellement vus. | Assertions au cutoff temporel, trous/duplicates, redémarrage cache, fingerprint dataset, aucune donnée future, replay identique à entrées archivées ou échec explicite. | Tables additives et lecteur ancien conservé durant migration ; rejeter jeu incomplet plutôt que compléter avec données futures. |
| D — banc expérimental commun | `research/backtest.py`, `r_analytics.py`, `scorecard.py`, `repository.py`, `models.py`, `btc_experiment.py`, `tests/test_backtest.py`, `test_btc_experiment.py` : moteur de coûts/risque/positions comparables, provenance, splits et résultats négatifs immuables ; séparer résultat technique et promotion. | Même ordre de marché simulé → mêmes fill/cost/R pour tous modèles ; slippage/spread/frais, gaps, intrabar, labels/purge, OOS hors réglage ; BTC avec spread source explicite. | Laisser ancien backtest comme baseline étiquetée non comparable ; ne promouvoir aucune expérience non revalidée. |
| E — interface Brain et cycle de vie | `orchestration/engine.py`, `bootstrap.py`, `market/opportunity.py`, `core/models.py`, `journal/models.py`, tests d'orchestration : `ActionProposal` versionnée, NO_TRADE explicite, décision stable, lien opportunity→intent→risk→trade/position→outcome ; voie classique adaptée ; actions de sortie sous risque déterministe. | Voie classique avant/après égale sur fixtures, états valides, refus de proposition malformée, sorties/SL/TP/partial close sur mock, aucune route directe Brain→broker. | Flag de sélection : garder cerveau classique promu ; repasser en shadow si divergence. |
| F — outcome, reward et cerveau expérimental | Nouveaux modules `brain/`, `learning/` seulement après contrats E ; `research/` pour replay, registre/checkpoints et contrôles ; tests unitaires/reproductibilité. LIF réduit, readout, R-STDP avec trace, surprise et métabolisme chacun derrière ablation. | Résultat daté, attribution à décision/version, récompense NO_TRADE contrefactuelle séparée des données observées, poids reproductibles par seed ; aucune mutation du checkpoint actif par la boucle lente. | Restaurer checkpoint promu précédent et désactiver le candidat ; conserver expériences négatives. |
| G — Mission Control | `api/app.py`, `api/static/index.html`, `journal/repository.py`, `tests/test_api.py` : historique paginé par run/cycle/decision ID ; détail JSON brut et replay en lecture seule ; chart OHLC archivé et overlays, positions SL/TP, rejets, santé, stress/reward lorsque disponibles. | Décision accessible après >40 nouveaux événements/restart ; API read-only, limites de pagination, HTML échappé, aucune fuite de secret, chart au bon timestamp/source. | Conserver pages/cards actuelles ; désactiver seulement panneaux nouveaux si schéma/feature indisponible. |
| H — service supervisé | `cli.py`, `orchestration/engine.py`, `bootstrap.py`, `api/app.py`, nouvelles unités de déploiement documentées et tests daemon : service Windows MT5, heartbeat process/market/brain, checkpoints atomiques, restart/reconcile, auth/TLS du cockpit distant. Séparation Linux cerveau/Windows exécution seulement si besoin mesuré. | Crash/restart idempotent, compte DEMO revérifié, données périmées ou cerveau absent → aucune **nouvelle** entrée, alerte ; heartbeat authentique et liveness distincte de fraîcheur du cycle. | Arrêt du service, kill switch, retour à exécution manuelle OBSERVE/DEMO sans fermer implicitement des positions. |
| I — Strategy Research/Harvester | `research/models.py`, `repository.py`, `strategies/registry.py`, docs/templates `docs/STRATEGIES/`, nouveaux outils de collecte isolés : provenance/licence → règles → leakage/repaint → implémentation propre → tests/replay/OOS/coûts → PAPER/DEMO → keep/modify/kill. | Source traçable/hashée, licences vérifiées, aucune importation d'un script tiers vers `execution/` ou runtime, transitions bloquées sans preuves, résultats négatifs visibles. | Désactiver candidat/outil ; conserver historique de provenance et versions. |

## 11. Fichiers et frontières de responsabilité

Le lot A possède uniquement sécurité de position ; B possède modes/simulateur ; C possède archive/replay ; D possède protocole de simulation ; E possède contrats de décision. Éviter les modifications simultanées de `orchestration/engine.py` par B et E, ou `research/models.py` par D et I. `execution/service.py` reste **l'unique** chemin broker ; `risk/` et `challenge/` gardent leurs règles déterministes ; `journal/` est une dépendance transversale append-only. Le frontend et l'API ne transmettent aucune intention de trading. Toute migration de schéma doit comporter lecteur compatible, migration explicite, et test de base existante.

## 12. Tests, quality gates et état observé

Sur ce dépôt : `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.test_tmp/risk_quality_full_20261002` a collecté **283 tests : 280 réussis, 3 ignorés** (`tests/integration/test_mt5_live.py`, opt-in `--run-mt5`). `.venv\Scripts\python.exe -m ruff check src tests` a réussi ; `.venv\Scripts\python.exe -m mypy src/alladin` a réussi sur 77 fichiers. Un essai ciblé recherche a d'abord rencontré `PermissionError` sur le répertoire temporaire global, puis la suite complète avec `--basetemp` local a réussi ; ce n'était pas une assertion de code. Un avertissement Starlette/httpx externe demeure. Aucun test MT5 connecté n'a été exécuté : il exige un terminal DEMO ; aucun trade réel n'a été fait.

À chaque lot : exécuter tests ciblés puis suite hors MT5, `ruff check src tests`, `mypy src` ; ne lancer `pytest --run-mt5` que dans un environnement DEMO validé, ses trois tests étant en lecture seule. Pour les travaux de recherche, ajouter tests de causalité, déterminisme, comparaison paire à paire et stress de coûts. Un test qui ne vérifie que l'enum ou recopie la fonction n'est pas une preuve fonctionnelle.

## 13. Critères d'acceptation transversaux

1. Aucune nouvelle entrée LIVE/CONTEST/UNKNOWN et aucune dérive du profil de risque ; SL et token restent obligatoires ; les sorties protectrices sont traitées explicitement selon décision 013.
2. Toute décision, y compris NO_TRADE et rejet, a ID, temps de disponibilité des données, version du cerveau/stratégie, proposition, résultat du risque, mode et lien vers outcome lorsqu'il existe.
3. Rejeu d'un cycle avec données archivées produit le même contexte ou une erreur d'intégrité ; jamais une substitution silencieuse par le marché actuel.
4. Un résultat OOS ne sert pas au réglage ; toute promotion réclame comparaison préenregistrée avec baseline et rollback possible.
5. Les tests de sécurité, causalité, intégrité et restart passent ; aucune modification de l'historique journal/recherche.

## 14. Rollback strategy

Runtime : conserver le dernier cerveau promu et une voie classique validée ; activation par configuration/version pin, jamais auto-réécriture. Données : migrations additives, backups SQLite avant migration, hash/fingerprint et lecture de l'ancien format jusqu'à preuve de conversion ; ne jamais « réparer » une archive invalide avec des barres futures. Modes : fail closed, OBSERVE lors d'une incompatibilité, kill switch opérationnel ; la réconciliation ne ferme pas une position simplement à cause d'un redémarrage. UI : panneau nouveau désactivable indépendamment. Chaque lot documente commandes de validation et procédure de retour à l'état antérieur.

## 15. Observability requirements

Événements structurés et corrélés par `run_id`, `cycle_id`, `opportunity_id`, `decision_id`, `trade_id`/ticket et `brain_version`. À chaque frontière : source/capacités des données, horodatage observable, délai/fraîcheur, feature/encoder version, proposition+confiance/NO_TRADE, rejets codés RiskEngine, précontrôle/exécution vérifiée, changements de position, outcome/reward/surprise et checkpoint. Mesurer latences, stale-data, trous d'archive, refus de fermeture, positions sans SL, écarts paper/broker, drift/calibration, drawdown, headroom challenge, état de liveness/restart. Éviter secrets et identifiants broker dans API/logs. `/health` doit distinguer vie du processus, dernière observation et dernier cycle réussi ; l'heure du navigateur n'est pas un heartbeat serveur.

## 16. Data / replay requirements

`MarketDataArchive` constitue le point de départ, pas encore une preuve de fidélité : sa PK `(symbol,timeframe,ts)` et ses triggers empêchent une modification SQL, mais `_last` cache le dernier timestamp ; une barre arrivée tard est écartée, `OR IGNORE` peut masquer des doublons contradictoires et `added=len(rows)` surestime parfois l'insertion. Les références `cycle_inputs` donnent `n_bars/first_ts/last_ts`, sans garantir que toutes les barres sont retrouvables. Les barres archivées manquent close time explicite, disponibilité de la donnée, provenance, bid/ask tick et version de calcul. `ReplayContext` ne charge pas les barres ; la CLI « replay cycle » affiche des références.

Fixer des cutoffs observables par timeframe, frontières train/validation/OOS/DEMO, fingerprint de dataset/code/coûts, flux de ticks lorsque le coût/exécution le requiert, et politique des révisions vendor. Le replay doit pouvoir reconstruire la vue **as-of**, comparer des actions contrefactuelles sans contaminer l'observé, et signaler toute donnée indisponible. La même archive, le même simulateur, le même risque, les mêmes frais/spread/slippage et les mêmes splits alimentent toutes les architectures candidates.

## 17. SNN experimental protocol

Le SNN est une hypothèse falsifiable. Préenregistrer objectif, métrique primaire (par exemple expectancy R OOS net de coûts et drawdown/challenge), seuil minimal d'effet, budget de complexité, nombre de runs/seeds, contrôle des essais multiples et critères d'échec **avant** d'observer OOS. Comparer, avec mêmes données/features accessibles, horizon, coût, exécution, portefeuille, splits, seed set et budget de tuning :

1. Alladin classique (stratégies/routeur) ; baseline simple sans SNN (règle naïve, régression/ridge ou autre contrôle fixé).
2. SNN simple LIF et readout ; réseau gelé versus avec plasticité.
3. Connectome biologique pruné versus graphes aléatoires et **rewired à degrés préservés**, même taille/densité/readout ; ne pas changer plusieurs mécanismes à la fois.
4. Ablations appariées avec/sans R-STDP, avec/sans surprise, avec/sans état métabolique, puis interactions explicitement prévues.

Rapporter distribution par seed, instruments/régimes, OOS, coûts et slippage stressés, turnover, calibration, drawdown/tails, latence et consommation ; résultats négatifs conservés. OOS reste fermé au réglage. Les analogies Mushroom Body/Central Complex sont des hypothèses de mapping, pas des faits biologiques sur le marché. Si le connectome ou la plasticité n'apporte pas de gain robuste sur les contrôles, rejeter la complexité. Aucun modèle de recherche ne passe directement à l'exécution ; promotion avec version/checkpoint/signature et retour arrière.

## 18. Mission Control migration

Garder le frontend et les endpoints de lecture existants. Étape données d'abord : recherche paginée par run/type/date, détail stable par `(run_id, seq)` ou ID journal (la PK existe), fiche décision agrégeant les événements liés sans détruire le JSON brut ; `GET` replay read-only. Étape interface : sélectionner une décision puis conserver cette sélection pendant les rafraîchissements ; URL/deep link, filtres NO_TRADE/risk/position, état de chargement/erreur. Ajouter chandeliers depuis les barres archivées, overlays positions/SL/TP et décisions horodatées ; afficher explicitement « non disponible » pour reward/surprise/SNN tant que ces données n'existent pas. Les cartes positions, challenge, risque et labs restent.

Le défaut actuel est `refreshMedium()` qui remplace `brain-body` par les 40 derniers événements (`index.html`) ; le journal conserve l'historique. L'UI utilise un `renderHTML` avec allowlist ad hoc : préférer création DOM et `textContent` pour les données, ou assainissement robuste testé ; ajouter tests d'injection de champs journal/recherche. L'API actuelle n'a pas d'authentification intégrée : bind local par défaut, puis auth/TLS et contrôle de périmètre avant accès distant.

## 19. Autonomous service migration

Conserver la boucle `OrchestrationEngine.run_loop`, sa pause après erreurs et ses signaux d'arrêt. Ajouter superviseur Windows compatible MT5, politique restart/backoff, singleton/lock, heartbeat process écrit par service, contrôle de fraîcheur marché et du checkpoint cerveau, puis reconcile au démarrage. Séparer liveness, readiness et permission d'envoyer un ordre ; aucun ordre nouveau si marché périmé, broker non DEMO, cerveau indisponible, journal non accessible ou état non récupéré. Une sortie protectrice existante suit la décision 013 et reste auditée. Le nœud Linux Brain / Windows Execution est une possibilité conditionnelle : avant séparation, prouver auth des messages, idempotence, séquencement, timeouts et capacité à se fermer en sécurité. Le cockpit n'est exposé à distance qu'après authentification et TLS.

## 20. Strategy Research / Harvester integration

Conserver `StrategyRegistry`, les trois stratégies et `ResearchRepository`. Les fiches `docs/STRATEGIES/` (trend, breakout, mean reversion, pairs, carry, multifactor) et les références `scripts/` forment une bibliothèque d'hypothèses ; seuls Trend/Breakout/Range sont des stratégies de runtime. Un candidat traverse `discover → provenance/license → extraction de règles → audit leakage/repaint → implémentation propre → tests → replay → validation/OOS → stress de coûts → PAPER/DEMO → keep/modify/kill`. Enregistrer URL/auteur/date/licence et restrictions d'usage, hash de source et de code propre, données/coûts/seeds, motifs de rejet. Un script tiers reste isolé, n'est jamais importé dans le processus d'exécution et ne fournit jamais un `ApprovalToken` ; son idée peut devenir baseline, feature, enseignant ou contre-factuel après validation. L'état `APPROVED` n'est pas déduit d'une courbe positive ; le lifecycle actuel vérifie des statuts, pas l'ensemble des preuves.

## 21. Technical debt discovered

- **P0 sécurité :** `monitor.sync()` écrit `stop_loss=None` dès détection ; si la fermeture échoue, le cycle suivant peut ne plus émettre `sl_removed`. `close_position()` retourne vrai dès qu'une position est trouvée, pas après fermeture confirmée. À l'ouverture sans SL, `submit()` affirme une fermeture d'urgence sans vérifier le résultat et peut laisser une position non enregistrée. Voir lot A.
- **P0 contrat :** modes OBSERVE/PAPER décrits sans `order_send`, alors que fermeture protectrice peut appeler broker ; PAPER n'est qu'un dry-run pour les entrées.
- **P1 portefeuille :** `ExecutionService._build_context` ne passe que les positions du run ; corrélation calculable mais provider non fourni au bootstrap ; si `calc_margin` renvoie `None`, contrôle de marge peut être ignoré. Définir politique fail-closed sans bloquer arbitrairement un compte sur données fiables.
- **P1 données :** cache `_last`, `OR IGNORE`, fenêtre replay incomplète, provenance et temps de disponibilité absents ; `BinancePublicProvider.klines` ne fournit pas de spread exploitable (valeur zéro), expérience BTC en mémoire avec coûts fixes.
- **P1 recherche :** backtest ne passe ni par `MarketQualityEngine` ni par le vrai `RiskEngine`, fabrique `tf_trend={}` et réduit `passed` à 30 trades + expectancy positive ; ce flag ne prouve pas OOS. Il est néanmoins causal sur le fill next-open et les gaps.
- **P1 observabilité :** décisions UI volatiles, `/health` sans heartbeat process, `Opportunity.strategy_candidates` rempli avec clés de timeframes (`engine.py`) et non IDs de stratégies ; opportunités sans transitions après création.
- **P2 docs/qualité :** README CLI et section replay d'`ARCHITECTURE.md` obsolètes ; index décisions incomplet ; `ResearchPerformanceProvider` existe mais bootstrap classe via journal ; champs de provenance/seed/coût/checkpoint absents du dépôt d'expériences.

## 22. Security / risk concerns and guards

Conserver `TRADING_MODE=demo`, contrôle `AccountType.DEMO` au niveau broker, token d'approbation frais, SL obligatoire, précontrôle, position vérifiée, kill switch, ownership magic+comment, watchdog, journal append-only et fermeture explicitement contrôlée. Le profil courant limite par exemple le risque par trade à 8 % du **working capital** (10 % de l'equity), 5 positions, risque ouvert total à 30 % du working capital, concentration devise à 15 %, marge à 50 %, corrélation à 0,85 ; ces valeurs sont des plafonds expérimentaux, pas des objectifs à atteindre. Un changement de garde-fou exige une proposition distincte avec justification, métriques, conditions, remplacement éventuel et rollback ; les invariants compte DEMO, chemin unique `ExecutionService`, risque externe et traçabilité ne deviennent jamais des poids du cerveau.

Risques additionnels : état broker/journal désynchronisé, fermeture refusée, tick périmé, capacité adapter absente, non-idempotence après crash, exposition de l'API, injection de données dans le frontend, provenance/licence de code tiers, fuite train→OOS, reward hacking et transfert FX→crypto. Mettre des tests d'échec réalistes avant toute extension d'autonomie. Aucune commande de l'audit n'a utilisé `--run-mt5` ou lancé un trade.

## 23. Unresolved questions

1. **Politique des sorties protectrices en OBSERVE/PAPER :** doivent-elles pouvoir envoyer un CLOSE sur une position DEMO possédée ou seulement alerter ? La proposition 013 recommande de séparer un mode strictement sans ordre d'un mode de gestion de positions DEMO, à adopter avant tout changement de sémantique.
2. Portefeuille : limites par run ou compte entier, attribution d'une position étrangère et comportement quand corrélation/marge sont indisponibles ? Ne jamais toucher une position étrangère, mais tenir compte de son exposition économique si les données sont fiables.
3. Fréquence des décisions et horizon de labels : préciser par instrument/timeframe avant purge, reward et contre-factuels.
4. Coûts par broker/instrument et provenance historique des ticks/spreads : quelles données seront effectivement disponibles, sans inventer d'order book ?
5. Stratégie de stockage long terme, rétention, sauvegarde et moteur de base si volume/accès multi-processus dépassent SQLite.
6. Seuils de promotion SNN, budgets de calcul et latence acceptables : à préenregistrer avec les premières expériences, pas à choisir après OOS.

## 24. Explicit non-goals

Pas de trading LIVE, de retrait de garde-fou, de copie/exécution directe d'un script Internet, de réécriture complète du frontend ou du backend, de chargement immédiat du connectome complet, de HFT, de promesse de profit, de transfert automatique FX→crypto, de restructuration V1/V2, ni de modification de l'historique des décisions. Ce plan ne déploie rien et ne décide pas à la place de la proposition 013.

## 25. Premier lot et handoff

Le premier lot traite le risque P0 de fermeture protectrice non confirmée. Le replay fidèle est le lot C suivant : son implémentation pourrait se limiter initialement à charger et vérifier les fenêtres archivées dans `ReplayContext.from_cycle`, avec tests d'archive incomplète. Avant chaque lot, Claude relit `docs/HANDOFF.md`, les décisions ADOPTED, la proposition 013 si elle touche les modes, puis le code et les tests indiqués ; les décisions restent source de contrainte, pas preuve que les fonctionnalités sont livrées.

# CLAUDE — NEXT WORK PACKAGE

**Objectif exact.** Empêcher qu'une position ALLADIN possédée et encore ouverte sans SL cesse d'être signalée après un seul essai de fermeture échoué ; ne déclarer une fermeture accomplie qu'après résultat broker confirmé et absence de la position. Petit correctif de sécurité réversible, en **DEMO/mock** avec tests ; pas de changement du contrat OBSERVE/PAPER tant que la décision 013 reste proposée.

**Contexte.** `PositionMonitor.sync()` détecte `pos.sl is None` seulement lorsque `trade.stop_loss` était non nul puis écrit `None` en base (`src/alladin/orchestration/monitor.py`). `OrchestrationEngine._run_cycle()` tente alors `close_position()` une seule fois. `ExecutionService._close()` ne retourne pas de statut confirmé ; `close_position()` peut retourner `True` malgré refus broker (`src/alladin/execution/service.py`). Le chemin d'ouverture sans SL a le même risque de message mensonger et peut précéder la création de `TradeRecord`. Toutes les sécurités DEMO et ownership restent obligatoires.

**Fichiers à inspecter.** `docs/HANDOFF.md`, `docs/DECISIONS/DECISION-003-DETERMINISTIC-RISK.md`, `DECISION-008-AUTONOMOUS-SERVICE.md`, `DECISION-011-AUTONOMOUS-MULTI-POSITION-LIFECYCLE.md`, proposition 013 ; `src/alladin/orchestration/{monitor,engine}.py`, `src/alladin/execution/service.py`, `src/alladin/brokers/{base,mock}.py`, `src/alladin/journal/{models,repository}.py`, `tests/{test_execution,test_orchestration,test_daemon_modes}.py` et fixtures `tests/conftest.py`.

**Fichiers probablement à modifier.** `src/alladin/orchestration/monitor.py`, `src/alladin/execution/service.py`, éventuellement l'appel dans `src/alladin/orchestration/engine.py` et tests existants `tests/test_execution.py`, `tests/test_orchestration.py`/`test_daemon_modes.py`. Aucun nouveau module, aucune migration de base sauf nécessité démontrée.

**Invariants.** Ne jamais ouvrir sur compte non DEMO ; ne jamais envoyer un ordre sans token, toucher une position étrangère ou supprimer l'exigence de SL. Ne pas transformer un mode en LIVE. Une fermeture protectrice refusée doit laisser une alerte persistante et bloquer les nouvelles entrées via les contrôles existants ; ne pas boucler rapidement des ordres sans cadence/backoff. Ne pas supprimer/modifier une ligne de journal antérieure. Respecter la politique de mode actuelle jusqu'à résolution explicite de la proposition 013.

**Tests avant.** Avec le venv, lancer `pytest -q tests/test_execution.py tests/test_orchestration.py tests/test_daemon_modes.py -p no:cacheprovider --basetemp=.test_tmp/claude_sl_before` et noter le résultat ; vérifier `git status --short`. Ne pas lancer MT5 réel.

**Modifications attendues.** Ajouter un test qui crée une position possédée sans SL, fait refuser la fermeture par le faux broker, appelle deux cycles de surveillance et vérifie alerte/retry ou état de retry explicite au second cycle. Ajouter un test pour une position adoptée/non enregistrée et un autre pour une fermeture refusée juste après ouverture sans SL ; vérifier qu'aucun message « fermée » ni succès booléen n'est émis sans confirmation. Implémenter la correction minimale : détection basée sur l'état **courant du broker** à chaque cycle, résultat de fermeture vérifié, journal d'échec persistant et réconciliation après succès. Tester que les positions étrangères restent ignorées et que la fermeture DEMO réussie est finalisée. Si le mock ne sait pas simuler le refus, l'étendre seulement dans les fixtures/tests nécessaires.

**Tests après.** Rejouer les tests ciblés, puis `pytest -q -p no:cacheprovider --basetemp=.test_tmp/claude_sl_full`, `ruff check src tests`, `mypy src`. Comparer `git diff` et démontrer qu'aucun plafond/profil/mode n'a été assoupli.

**Critères d'acceptation.** (a) une position encore sans SL reste détectée au cycle suivant même si le journal/trade a enregistré `stop_loss=None` ; (b) fermeture refusée/bloquée est journalisée et jamais annoncée réussie ; (c) réussite confirmée arrête les retries ; (d) aucun ordre vers position étrangère ; (e) tests de sécurité existants et nouveaux verts ; (f) aucun changement du sens d'OBSERVE/PAPER.

**Conditions d'arrêt.** Si résoudre le cas exige de changer la politique d'envoi de CLOSE en OBSERVE/PAPER, de retirer un garde-fou, ou d'introduire une migration destructrice, arrêter le lot après tests qui reproduisent le défaut et présenter le choix bloquant. Si la fermeture broker retourne un état ambigu, ne pas déclarer succès : journaliser l'incertitude et réconcilier avant nouvelle action.

**Hors scope.** SNN, Brain API, PAPER P&L, Mission Control, refonte générale du moniteur, trading LIVE, nouveaux brokers, stratégie de retry distribuée et migration de schéma non nécessaire.

## CLAUDE SESSION CHECKPOINT — Lot B

- **Date :** 2026-10-02 15:15 UTC+2
- **Work package :** Lot B — Contrat OBSERVE/PAPER/DEMO et environnement PAPER réel
- **État : COMPLETE**

### Objectif

Adopter DECISION-013 et implémenter le contrat de modes : OBSERVE (lecture stricte, aucun send_order), PAPER (simulation réelle avec PaperExperimentEngine, persistance, RiskEngine actif), DEMO (chemin sécurisé inchangé).

### Fichiers modifiés

| Fichier | Changement |
|---|---|
| `docs/DECISIONS/DECISION-013-MODE-SAFETY.md` | Statut PROPOSED → ADOPTED. Contrat formalisé : OBSERVE strict read-only, PAPER simulation isolée avec persistence, DEMO avec fermetures protectrices. |
| `src/alladin/execution/models.py` | `ExecStatus.PAPER_EXECUTED` ajouté — position paper créée, aucun ordre broker. |
| `src/alladin/journal/repository.py` | Table `paper_positions` ajoutée (paper_id PK, run_id, symbol, side, volume, entry_price, sl, tp, status, pnl_pips, mfe_pips, mae_pips, etc.). Méthodes CRUD : `insert_paper_position`, `update_paper_position`, `get_paper_position`, `list_paper_positions`. |
| `src/alladin/market/paper.py` | `PaperExperimentEngine` enrichi : persistance via repo, `restore()` pour restart, `close_position_by_id()` pour close explicite, accepte `RiskDecision` pour sizing. `PaperPosition.to_persistence()` / `from_persistence()` pour sérialisation. |
| `src/alladin/orchestration/engine.py` | `_run_cycle()` mode-aware : PAPER tick les positions paper, utilise submit(dry_run=True) + paper_engine.open_position. OBSERVE/PAPER : alerte critique sur SL supprimé sans send_order. DEMO : fermeture protectrice inchangée. Import `PaperExperimentEngine`, attribut `paper_engine`. |
| `src/alladin/orchestration/bootstrap.py` | `Components.engine()` crée `PaperExperimentEngine` et appelle `restore()` en mode PAPER. Import `PaperExperimentEngine`. |
| `tests/test_paper_engine.py` | 31 tests couvrant : isolation broker (SpyBroker qui RAISE sur send_order pour OBSERVE/PAPER/SL/TP/close/restart), DEMO conservé, OBSERVE alerte critique sans close, LIVE bloqué, PAPER lifecycle (open/SL/TP/close/P&L), persistance restart, double fill/close, DRY_RUN_APPROVED != EXECUTED, RiskEngine en PAPER, kill switch, journal, sizing, spread, round-trip persistence. |

### Résultats de validation

- Suite globale complète : **309 passed, 3 skipped** (MT5 opt-in)
- `ruff check src tests` : **All checks passed**
- `mypy src` : **Success: no issues found in 77 source files**
- `git diff --check` : aucune erreur

---

## CLAUDE SESSION CHECKPOINT — Lot A

- **Date :** 2026-10-02 10:38 UTC+2
- **Work package :** Lot A — P0 sécurité fermeture protectrice
- **État : COMPLETE**

### Cause racine

Trois défauts combinés empêchaient la re-détection et la fermeture fiable d'une position sans SL :

1. `monitor.sync()` comparait `pos.sl` (broker) à `trade.stop_loss` (DB). Après le premier cycle, la DB était mise à jour avec `stop_loss=None`, rendant la condition fausse au cycle suivant — la position sans SL devenait invisible.
2. `_close()` retournait `None` et ne vérifiait pas `result.accepted`. `close_position()` retournait `True` inconditionnellement.
3. `engine._run_cycle()` ignorait le retour de `close_position()` — aucune journalisation d'échec, aucun retry.

### Fichiers modifiés

| Fichier | Changement |
|---|---|
| `src/alladin/execution/service.py` | `_close()` retourne `bool` basé sur `result.accepted`, log l'échec. `close_position()` propage le résultat. `close_all()` ne compte que les fermetures confirmées. `submit()` path no-SL : message distinct selon succès/échec de la fermeture d'urgence. |
| `src/alladin/orchestration/monitor.py` | `sync()` re-signale `sl_removed` chaque cycle si le broker montre `pos.sl is None`, indépendamment de l'état DB. |
| `src/alladin/orchestration/engine.py` | `_run_cycle()` capture le retour de `close_position()` et journalise l'échec. |
| `tests/test_execution.py` | 6 nouveaux tests de régression (voir ci-dessous). |

### Tests ajoutés

1. `test_close_position_returns_false_when_broker_refuses`
2. `test_sl_removed_position_is_redetected_after_failed_close` (reproduit le bug P0)
3. `test_successful_protective_close_stops_redetection`
4. `test_close_failure_never_announces_success`
5. `test_emergency_close_failure_on_submit_does_not_claim_success`
6. `test_no_double_close_on_foreign_position_without_sl`

### Résultats de validation

- Tests ciblés (3 fichiers, 55 tests) : **55 passed**
- Suite globale complète : **all passed, 0 failed**
- `ruff check src tests` : **All checks passed**
- `mypy src` : **Success: no issues found in 77 source files**
- `git diff --check` : **aucun problème de whitespace**

### Critères d'acceptation satisfaits

- (a) position sans SL re-détectée au cycle suivant ✓
- (b) fermeture refusée journalisée, jamais annoncée réussie ✓
- (c) fermeture confirmée arrête les retries ✓
- (d) aucun ordre vers position étrangère ✓
- (e) tests de sécurité existants et nouveaux verts ✓
- (f) aucun changement du sens OBSERVE/PAPER ✓

### Décisions techniques

- La re-détection utilise un `if pos.sl is None and ticket not in rep.sl_removed` séparé du bloc de comparaison SL/TP, pour couvrir aussi le cas où seul TP change avec SL toujours absent.
- Pas de backoff explicite introduit : le cycle naturel du daemon sert de cadence. Chaque cycle tente au plus une fermeture par position sans SL.
- `close_all()` ne compte désormais que les fermetures broker-confirmées.

### Prochaine étape (Lot A)

Lot B selon le plan : résolution du contrat OBSERVE/PAPER (DECISION-013). Requiert l'adoption formelle de la proposition avant implémentation.

---

## CLAUDE IMPLEMENTATION WAVE 2 CHECKPOINT — 2026-10-02 15:20 GMT+2

### LOT B — Modes et PAPER
**STATUS: COMPLETE** (commit 926a9c8)

**OBJECTIVE:** Résoudre le contrat OBSERVE/PAPER/DEMO (DECISION-013), rendre PAPER réellement simulé et persistant.

**IMPLEMENTED:**
- DECISION-013 promu de PROPOSED à ADOPTED
- `ExecStatus.PAPER_EXECUTED` ajouté à `execution/models.py`
- `PaperExperimentEngine` réécrit avec persistance SQLite (`paper_positions` table dans `journal/repository.py`)
- `PaperExperimentEngine` accepte `RiskDecision` pour volume/SL/TP du risk engine
- `PaperExperimentEngine.restore()` pour survie au restart
- `OrchestrationEngine._run_cycle()` mode-aware : PAPER tick, DEMO protective close, OBSERVE/PAPER alert-only
- `bootstrap.py` câble `PaperExperimentEngine` avec auto-restore en mode PAPER

**FILES:** `src/alladin/execution/models.py`, `src/alladin/market/paper.py`, `src/alladin/orchestration/engine.py`, `src/alladin/orchestration/bootstrap.py`, `src/alladin/journal/repository.py`, `docs/DECISIONS/DECISION-013-MODE-SAFETY.md`, `docs/DECISIONS/README.md`

**TESTS ADDED:** `tests/test_paper_engine.py` (31 tests : broker isolation, DEMO preserved, OBSERVE alert, LIVE blocked, PAPER lifecycle, persistence, dry_run, risk engine, journal, sizing)

**TESTS RUN:** 31/31 passed (+ suite complète green)

**ARCHITECTURAL DECISIONS:**
- PAPER utilise `submit(dry_run=True)` pour validation risque, puis `paper_engine.open_position()` — jamais `broker.send_order`
- SpyBroker pattern : RAISES sur `send_order` pour prouver l'isolation OBSERVE/PAPER
- Protective close en OBSERVE/PAPER = critical alert log (pas de close broker)

**KNOWN LIMITATIONS:** Commit local 926a9c8, push bloqué par réseau lors de la session précédente.

---

### LOT C — Données causales et replay
**STATUS: PARTIAL** (non commit)

**OBJECTIVE:** Fiabiliser archive, replay causal, provenance, doublons contradictoires, fenêtres complètes, fingerprint dataset.

**IMPLEMENTED (C1+C2 seulement):**
- `Bar` model : ajout `available_at: datetime | None` et `provenance: str | None` dans `core/models.py`
- `BrokerCapabilities` dataclass dans `brokers/base.py` : `name`, `has_tick`, `has_bars`, `has_spread`, `has_close_time`, `has_tick_volume`, `has_real_volume`, `supported_timeframes`, `max_bars`, `provenance_tag`
- `BrokerAdapter.capabilities()` méthode par défaut
- `MockBroker.capabilities()` et `MT5Broker.capabilities()` surchargés

**FILES:** `src/alladin/core/models.py`, `src/alladin/brokers/base.py`, `src/alladin/brokers/mock.py`, `src/alladin/brokers/mt5.py`

**TESTS RUN:** 57 tests ciblés (test_market, test_research_replay, test_paper_engine) : 57/57 passed. ruff clean, mypy clean, git diff --check clean.

**REMAINING WORK (C3-C5):**
- C3 : `MarketDataArchive` — corriger `_last` cache (late insert), `OR IGNORE` masquant doublons contradictoires, `added=len(rows)` surestimation, ajouter colonnes `available_at`/`provenance` à `market_bars`, fingerprint dataset
- C4 : `ReplayContext.from_cycle()` doit charger les barres archivées réelles (pas seulement références `cycle_inputs`)
- C5 : Tests causalité : cutoff temporel, trous/duplicates, cache restart, fingerprint, no future data, replay identique aux entrées archivées

**NEXT EXACT ACTION:** Reprendre Lot C à l'étape C3 — modifier `market/archive.py` : ajouter colonnes `available_at`+`provenance` à la table `market_bars`, remplacer `OR IGNORE` par détection de doublons contradictoires, corriger `_last` cache pour insertion tardive, ajouter méthode `fingerprint()`. Puis C4 (ReplayContext avec barres), C5 (tests), C6 (validation/commit).
