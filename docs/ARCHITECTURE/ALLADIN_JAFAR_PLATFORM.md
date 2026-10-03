# ALLADIN / JAFAR — Architecture de plateforme partagée

**Date :** 2026-10-03
**Statut :** ARCHITECTURAL STUDY — pas encore implémenté
**Baseline :** commit post-Lot E (368 tests, ruff PASS, mypy PASS)

> Ce document décrit une cible architecturale et un plan de migration.
> Il n'implique aucune modification de code immédiate.
> Le code reste source de vérité.

---

## 1. Vision

ALLADIN et JAFAR sont deux **workspaces de trading** indépendants qui partagent un core commun.

Ils ne sont pas deux produits séparés reconstruits de zéro.
Ils ne sont pas non plus un seul runtime couplé qui tenterait de tout faire.

```
╔══════════════════════════════════════════════╗
║            PLATFORM CORE                    ║
║  Journal · Risk · Execution · Brain API     ║
║  Replay · Research · Observability          ║
╠═════════════════╦════════════════════════════╣
║   ALLADIN       ║   JAFAR                   ║
║   (bleu)        ║   (rouge)                 ║
║   FX / metals   ║   crypto                  ║
║   MT5-first     ║   MT5 crypto → exchange   ║
║   classique→SNN ║   SNN crypto              ║
╚═════════════════╩════════════════════════════╝
```

Les deux workspaces partagent le code.
Ils **ne partagent jamais** l'état mutable d'exécution.

---

## 2. État actuel après Lot E

### Ce qui existe

| Composant | Statut |
|---|---|
| `ActionProposal` / `Brain` protocol | Implémenté |
| `ClassicBrainAdapter` | Implémenté |
| `RiskEngine` déterministe | Implémenté |
| `ExecutionService` DEMO-safe | Implémenté |
| `FillRecord` / `CostModel` (Lot D) | Implémenté |
| `JournalRepository` append-only | Implémenté |
| `RunRecord` avec `profile_id`, `broker`, `magic` | Implémenté |
| `BrokerCapabilities` manifest | Implémenté |
| `OrchestrationEngine` avec `BrainContext` | Implémenté |
| Modes OBSERVE / PAPER / DEMO | Implémenté |
| Research / Causal archive / Replay | Implémenté |
| Mission Control API (lecture seule) | Implémenté |

### Limitations connues après Lot E

- CLOSE / MODIFY_STOP / MODIFY_TARGET / PARTIAL_CLOSE acceptés par `ActionProposal` mais non routés en production dans l'engine
- `RunRecord` n'a pas de champ `workspace`
- `AssetCategory` ne contient pas CRYPTO
- `BrokerCapabilities` est minimal (pas de session 24/7, pas de funding, pas de type d'ordre crypto)
- `ExecutionService` bloque sur DEMO uniquement — PAPER simulation partielle
- Pas de `AccountBinding` explicite (workspace → compte)
- Journal non partitionné par workspace : toutes les queries peuvent voir tous les runs

### Ce qui n'existe pas encore

- SNN réel
- Outcome Engine
- Reward / Pain / Surprise
- Position monitoring autonome (HOLD/MODIFY/CLOSE routés)
- Service H24 supervisé
- Jafar skeleton
- Exchange adapter crypto natif
- Command Center multi-workspace

---

## 3. Frontière du core partagé

### Classification des composants

```
SHARED CORE — Utilisable tel quel ou avec paramètre workspace
────────────────────────────────────────────────────────────
ActionProposal          Contrat universel Brain → Risk
Brain (Protocol)        Interface sans état workspace
BrainContext            Snapshot de marché sérialisable
FillRecord              Économie d'un trade (fill/cost/R)
CostModel               Modèle de coût indépendant du broker
JournalRepository       Append-only, requêtes filtrables
JournalEvent            Événement avec run_id
CausalArchive           Provenance dataset/fingerprint
ReplayContext           Déterminisme replay
ResearchRepository      Expériences et résultats
StrategyExperiment      Contrat expérimental
RunMode                 OBSERVE / PAPER / DEMO (+ futur LIVE)
RiskEngine (core)       Règles déterministes indépendantes
ExecutionService (core) Pipeline submit/close
BrokerAdapter           Interface abstraite
BrokerCapabilities      Manifeste de capacités

ALLADIN-SPECIFIC — Lié au profil FX/challenge/MT5
────────────────────────────────────────────────────────────
ChallengeWatchdog       Règles FTMO/prop-firm
Challenge profiles      Fichiers YAML par programme
MarketUniverse (FX)     Découverte / filtrage symbols FX
AssetCategory (FX)      FOREX_MAJOR, FOREX_MINOR, etc.
Classic strategies      TREND-01, BREAKOUT-01, RANGE-01

JAFAR-SPECIFIC — À créer, ne pas coller sur ALLADIN
────────────────────────────────────────────────────────────
Crypto session rules    24/7, weekends, maintenance exchange
Funding rate tracker    Financement perpetual futures
Crypto symbol mapper    BTCUSDT → canonical
Crypto risk policy      Leverage, liquidation, margin model
Exchange adapter        Binance/Bybit/etc (futur)

BROKER-SPECIFIC — Implémentation d'interface
────────────────────────────────────────────────────────────
MT5BrokerAdapter        Implémenté
CryptoBrokerAdapter     Stub existant (brokers/crypto.py)
Native exchange         Non implémenté

UNCERTAIN / REQUIRES REFACTOR
────────────────────────────────────────────────────────────
RunRecord               Manque workspace, account_binding
RiskEngine limits       Règles challenge FTMO hardcodées ?
PAPER simulation        Partielle, non finalisée
OrchestrationEngine     Un seul run global, non multi-workspace
```

---

## 4. Modèle workspace

### Identité workspace

```python
class WorkspaceId(StrEnum):
    ALLADIN = "ALLADIN"
    JAFAR   = "JAFAR"
    # Futur : HERMES, THOTH, ...
```

La valeur est une string courte, stable, lisible dans les logs.

### Propagation dans les structures

```
RunRecord          +workspace: WorkspaceId
JournalEvent       +workspace: WorkspaceId  (dénormalisé pour queries)
TradeRecord        via run_id → RunRecord
ActionProposal     via run_id → RunRecord   (pas de duplication)
Opportunity        via run_id
Position           via magic / comment (existant, déjà workspace-safe si magic unique)
Experiment         +workspace: WorkspaceId
Dataset            +workspace: WorkspaceId
```

**Règle :** `proposal_id` et `run_id` incluent déjà l'identité. Le workspace se déduit du run. Pas de duplication dans chaque event.

### Isolation par magic number

Le système actuel utilise déjà `magic` pour identifier les positions ALLADIN.
Pour JAFAR : plage de magic séparée (ex : ALLADIN 1000-1999, JAFAR 2000-2999).
La position broker est alors toujours identifiable même si les deux workspaces utilisent le même compte.

```python
MAGIC_ALLADIN_BASE = 1000
MAGIC_JAFAR_BASE   = 2000
```

---

## 5. Isolation d'état

### Ce qui doit être isolé

| Resource | Mécanisme d'isolation |
|---|---|
| Run actif | Un `RunRecord` par workspace, `run_id` unique |
| Positions | Magic number + workspace tag dans le comment |
| Risque ouvert | Calculé par workspace (filter sur magic/positions) |
| Working capital | Profile par workspace |
| Challenge | Profile par workspace (ALLADIN peut avoir challenge, JAFAR non) |
| Strategy registry | Répertoire de config par workspace |
| Brain version | `source_id` inclut workspace → checkpoints non partagés |
| Universe | `MarketUniverse` instancié par workspace |
| Expériences research | `workspace` field dans `StrategyExperiment` |
| Journal queries | Filter `workspace` sur `RunRecord` |

### Ce qui peut être partagé

| Resource | Notes |
|---|---|
| DB SQLite | Tables partagées, workspace comme clé de partition |
| BrokerAdapter instance | Si même compte ; sinon instances séparées |
| BrokerCapabilities | Partagé par broker, pas par workspace |
| CausalArchive | Fingerprint universel ; dataset taggé par workspace |

### Garantie de non-contamination

Un crash JAFAR ne doit pas affecter ALLADIN.

- Pas d'état mutable global partagé entre workspaces
- `OrchestrationEngine` instancié séparément par workspace
- `RiskEngine` stateless : recalcul à chaque cycle depuis positions réelles
- `JournalRepository` append-only : un write JAFAR ne peut pas corrompre les events ALLADIN

```
CRASH JAFAR
  → OrchestrationEngine JAFAR levée exception
  → Journal JAFAR event "KILLED" écrit
  → RunRecord JAFAR state = FAILED
  → Journal ALLADIN intact
  → RunRecord ALLADIN intact
  → Positions ALLADIN intact (magic séparé)
```

---

## 6. Modèle broker / compte

### Hiérarchie cible

```
Workspace (ALLADIN | JAFAR)
    │
    ▼
AccountBinding
    broker_name : str          # "mt5:ICMarkets", "binance:main"
    account_id  : str          # numéro de compte ou clé API
    account_type: AccountType  # DEMO | CONTEST | LIVE
    currency    : str          # EUR, USD, USDT
    capabilities: BrokerCapabilities
    │
    ▼
BrokerAdapter  (interface)
    │
    ▼
Broker / Exchange
```

### `BrokerCapabilities` enrichi pour Jafar

```python
@dataclass
class BrokerCapabilities:
    name: str
    # Données de marché
    has_tick: bool = True
    has_bars: bool = True
    has_spread: bool = True
    has_close_time: bool = False
    has_tick_volume: bool = True
    has_real_volume: bool = False
    supported_timeframes: frozenset[Timeframe] = ...
    max_bars: int = 10000
    provenance_tag: str = ""
    # Sessions
    is_24_7: bool = False          # crypto : True
    has_weekend_trading: bool = False
    # Types d'ordres
    has_limit_orders: bool = True
    has_stop_orders: bool = True
    has_oco_orders: bool = False
    # Sizing
    min_volume: float = 0.01
    volume_step: float = 0.01
    max_leverage: int = 100
    # Coûts
    has_maker_taker: bool = False   # True pour exchanges crypto
    has_funding_rate: bool = False  # True pour perpetual futures
    has_commission: bool = False
    # Asset classes
    supported_asset_classes: frozenset[str] = frozenset({"FOREX"})
    # Exécution
    has_partial_fill: bool = False
    has_market_order: bool = True
```

### Exemples d'instances

```
ALLADIN → MT5 ICMarkets DEMO
  is_24_7=False, has_weekend_trading=False
  has_maker_taker=False, has_funding_rate=False
  supported_asset_classes={"FOREX", "METAL"}

JAFAR phase 1 → MT5 broker crypto-capable
  is_24_7=True, has_weekend_trading=True
  has_maker_taker=False (MT5 normalise)
  supported_asset_classes={"CRYPTO"}

JAFAR phase 2 → Exchange natif Binance
  is_24_7=True, has_maker_taker=True, has_funding_rate=True
  supported_asset_classes={"CRYPTO_SPOT", "CRYPTO_PERP"}
```

---

## 7. Spécificités crypto pour JAFAR

### Ce que les abstractions ALLADIN gèrent déjà

| Aspect | Gestion actuelle |
|---|---|
| Format canonique OHLCV | Oui, broker-agnostic |
| `BrokerCapabilities` | Oui, extensible |
| `FillRecord` cost/spread | Oui, paramétrique |
| `Side` BUY/SELL | Oui |
| `ActionProposal` / `Brain` | Oui, sans dépendance FX |

### Ce qui doit être généralisé ou créé

| Aspect crypto | Impact architecture |
|---|---|
| Sessions 24/7 | `BrokerCapabilities.is_24_7` ; supprimer assumption de session FX dans `MarketUniverse` |
| Weekend trading | Vérification de session dans engine doit être configurable |
| Symbol naming (BTCUSDT) | `SymbolMapper` configurable par workspace |
| Tick sizes variables | Déjà dans `SymbolSpec` — vérifier |
| Funding rate | `CostModel` doit pouvoir inclure funding ; `FillRecord` inchangé |
| Perpetual futures | Nouveau `ContractType` enum ; `AssetCategory` enrichi |
| Spot | Nouveau `AssetCategory.CRYPTO_SPOT` |
| Leverage / liquidation | `RiskEngine` doit avoir policy configurable ; liquidation ≠ SL |
| Maker/taker fees | `CostModel` déjà abstrait — ajouter `fee_model` |
| Candle alignment | Cryptos : UTC strict, pas de clôture New York |
| Min volume | `BrokerCapabilities.min_volume` (déjà présent) |
| Margin model | Portfolio margin vs isolated — à modéliser |

**Règle :** ne pas faker le support. Un `BrokerCapabilities` qui annonce `has_funding_rate=False` interdit silencieusement le calcul de funding dans le `CostModel`. L'adapter doit être honnête.

---

## 8. Frontière du vrai argent

### État actuel

```
LIVE est bloqué dans ExecutionService.
AccountType.LIVE → block_message() → refus immédiat.
Aucune levée de ce blocage n'existe dans le code.
```

### Chemin de promotion futur (architecture uniquement)

```
PAPER (simulation interne)
  ↓ [critères de performance]
DEMO (broker account type = DEMO)
  ↓ [critères de durée + performance + validation]
LIVE-ELIGIBLE (gate technique)
  ↓ [activation humaine explicite]
LIVE
```

### Portes techniques à implémenter avant LIVE

| Gate | Description |
|---|---|
| `validated_brain_version` | Version brain avec OOS passé documenté |
| `min_demo_history_days` | Minimum N jours de DEMO sans violation |
| `max_drawdown_demo` | Pas de dépassement de limite en DEMO |
| `risk_policy_approved` | `RiskPolicy` signée et versionnée |
| `account_binding_verified` | AccountBinding confirmé avec `account_type=LIVE` |
| `broker_capabilities_verified` | `BrokerCapabilities` audité pour le compte LIVE |
| `kill_switch_tested` | Test kill switch sur DEMO prouvé |
| `audit_chain_ok` | Journal integrity check `verify_chain()` PASS |
| `position_reconciliation_ok` | Réconciliation positions au restart testée |
| `human_activation` | Flag explicite dans config non-versionné (ne jamais committer) |

Ces portes sont des **exigences architecturales futures**. Aucune ne doit être implémentée avant d'être testée sur PAPER/DEMO.

---

## 9. Command Center — Architecture d'information

### Vision

```
╔══════════════════════════════════════════════╗
║           COMMAND CENTER                    ║
║  ┌────────────┐    ┌──────────────────────┐ ║
║  │  ALLADIN   │    │      JAFAR           │ ║
║  │  ● DEMO    │    │  ○ OFFLINE           │ ║
║  │  1 pos     │    │  0 pos               │ ║
║  │  +1.2%     │    │  --                  │ ║
║  └────────────┘    └──────────────────────┘ ║
║  [ALLADIN] ⇄ [JAFAR]                        ║
╚══════════════════════════════════════════════╝
```

Cliquer sur ALLADIN → Mission Control ALLADIN (existant)
Cliquer sur JAFAR → Mission Control JAFAR (futur)

### API necessaires

```
GET /api/workspaces
  [
    {
      "workspace": "ALLADIN",
      "mode": "DEMO",
      "broker_connected": true,
      "run_id": "...",
      "equity": 10234.50,
      "open_positions": 1,
      "last_cycle_at": "...",
      "stale": false,
      "alerts": []
    },
    {
      "workspace": "JAFAR",
      "mode": null,
      "broker_connected": false,
      ...
    }
  ]
```

Chaque workspace garde sa propre API `/api/...` avec prefix ou port.

### Switch rapide

URL scheme proposition :
```
/                 → Command Center
/alladin/         → Mission Control ALLADIN
/jafar/           → Mission Control JAFAR
```

Ou ports séparés si déploiement séparé.

---

## 10. Identité visuelle

### ALLADIN
```
Primaire : #4a9edd  (bleu acier)
Accent   : #56d4dd  (cyan)
Fond     : #0b0f14  (near-black)
Surface  : #131920  (charcoal bleu)
Ton      : institutionnel, analytique, froid
```

### JAFAR
```
Primaire : #c0392b  (rouge cramoisi profond)
Accent   : #e74c3c  (rouge vif sobre)
Fond     : #0f0a0a  (near-black chaud)
Surface  : #1a1010  (charcoal rouge)
Ton      : agressif mais professionnel, NON casino
```

### Partagé
- Même système de composants (tokens CSS, panel, table, trace, status chip)
- Même grammaire UX (sidebar, statusbar, workspace)
- Même hiérarchie d'information
- Seuls les tokens de couleur primaire changent
- La page active doit être impossible à confondre visuellement

---

## 11. Isolation des cerveaux

### Principe

```
Brain ALLADIN ≠ Brain JAFAR
```

Même si les deux utilisent un SNN de même topologie, les poids/checkpoints ne sont jamais partagés automatiquement.

### Identité d'un cerveau

```python
source_id      = "snn:alladin:fly-v1"      # ALLADIN
source_id      = "snn:jafar:crypto-v1"     # JAFAR
source_version = "20261003-abc123"         # hash du checkpoint
```

`proposal_identity()` inclut `source_id` et `source_version` → deux cerveaux ne peuvent pas produire le même `proposal_id`.

### Partage autorisé

- Code du SNN (topologie, R-STDP, encodeur) : partagé
- Données d'entraînement : indépendantes
- Checkpoints / poids : strictement isolés
- Infrastructure research (replay, archive, expériences) : partagée avec tag workspace

### Transfert d'apprentissage

Si un jour FX → crypto transfer learning est exploré, ce doit être une expérience explicite dans le Research Lab avec split OOS clair, **pas un partage accidentel de checkpoint**.

---

## 12. Stratégie de migration

### Principe

Migration incrémentale. Chaque étape est testable indépendamment.

Le core actuel reste 100% fonctionnel pour ALLADIN pendant toute la migration.

### Étapes principales

```
1. Ajouter WorkspaceId enum (non-breaking)
2. Ajouter workspace à RunRecord (migration DB nullable → default ALLADIN)
3. Filtrer les queries journal par workspace
4. Extraire AccountBinding de RunRecord
5. Enrichir BrokerCapabilities
6. Créer AssetCategory crypto
7. Instancier OrchestrationEngine par workspace
8. Brancher workspace dans proposal_identity (non-breaking)
```

Chaque étape ajoute des tests avant merge.

---

## 13. Graphe de dépendances — prochains lots

```
Lot E (COMPLETE)
  Brain API, ActionProposal, ClassicBrainAdapter, lifecycle identity

Lot F — Position lifecycle complet (FONDATION)
  CLOSE / MODIFY_STOP / MODIFY_TARGET / PARTIAL_CLOSE routés en engine
  Position monitoring autonome dans OrchestrationEngine
  Tests d'intégration : position ouverte → HOLD → MODIFY_SL → CLOSE
  [Bloquant pour : Lot G, SNN real, Reward]

Lot G — Workspace identity + state isolation (ARCHITECTURE)
  WorkspaceId enum
  workspace dans RunRecord, TradeRecord, Experiment
  Journal queries filtrées par workspace
  Magic number ranges séparés
  AccountBinding model
  [Bloquant pour : Lot I Jafar skeleton]

Lot H — BrokerCapabilities + CostModel enrichis (BROKER)
  BrokerCapabilities crypto (is_24_7, has_funding_rate, ...)
  AssetCategory crypto (CRYPTO_SPOT, CRYPTO_PERP)
  CostModel maker/taker + funding
  Session rules configurables
  [Bloquant pour : Lot I]

Lot I — Jafar skeleton (WORKSPACE)
  WorkspaceId = JAFAR instancié
  Config profile JAFAR
  OrchestrationEngine JAFAR isolé
  Mission Control JAFAR (fork Mission Control ALLADIN avec tokens rouges)
  Zéro stratégie réelle — OBSERVE only
  [Bloquant pour : cerveau crypto]

Lot J — Outcome Engine + Reward (LEARNING FOUNDATION)
  Outcome Engine : MAE/MFE, durée, coût réel, contre-factuel
  Reward signal : PnL + quality + drawdown penalty
  [Bloquant pour : SNN R-STDP]

Lot K — SNN minimal contrôlable (SNN)
  Neurones LIF, R-STDP, encodeur minimal
  Vérification que R-STDP modifie effectivement le comportement
  Comparaison baseline classique vs SNN dans Research Lab
  [Bloquant pour : SNN complet]
```

### Recommandation d'ordre

```
F (lifecycle) → G (workspace) → H (broker) → I (Jafar) ↘
                                                          └→ J (outcome) → K (SNN)
```

**F est le lot suivant obligatoire.** Sans position lifecycle complet :
- le Brain ne peut pas gérer ses positions
- PAPER simulation est incomplète
- le feedback loop Outcome → Reward est vide
- JAFAR hériterait d'une lacune fondamentale

---

## 14. Risques et anti-patterns

### Risques principaux

| Risque | Mitigation |
|---|---|
| Couplage accidentel ALLADIN/JAFAR via état global | State isolation explicite (section 5) |
| Magic number collision entre workspaces | Plages réservées et validées au démarrage |
| Checkpoint SNN partagé par accident | `source_id` inclut workspace ; path isolé |
| Leakage FX assumptions dans JAFAR | `BrokerCapabilities.is_24_7` interdit silencieusement |
| LIVE enablement accidentel | `AccountType.LIVE → block_message()` — ne jamais supprimer |
| Fake crypto support | `BrokerCapabilities` honnête ; si non supporté = exception |

### Anti-patterns à éviter

- **God workspace** : un seul runtime qui tente FX + crypto avec conditionnels `if workspace == JAFAR`
- **Shared mutable risk state** : JAFAR ne doit jamais lire le `challenge` ALLADIN
- **Checkpoint drift** : nommer des checkpoints sans `workspace` et `source_version`
- **Premature abstraction** : ne pas créer `AbstractWorkspace` avant que deux workspaces existent réellement
- **LIVE shortcut** : "juste pour tester" — ne jamais affaiblir la gate DEMO check
- **Silent float** : paramètres FX (contract size, spread) utilisés en crypto sans adaptation explicite

---

## 15. Décision architecturale associée

Voir : `docs/DECISIONS/DECISION-009-JAFAR-SHARED-CORE.md` (ADOPTED)

Ce document opérationnalise cette décision en détaillant les frontières exactes, le modèle workspace, l'isolation d'état et le plan de migration.

Aucune nouvelle décision n'est nécessaire à ce stade. La décision 009 est suffisante.

Si lors de Lot G l'inspection du code révèle un besoin de précision supplémentaire sur l'AccountBinding ou la politique de magic numbers, créer `DECISION-014-ACCOUNT-BINDING.md`.

---

## Résumé des frontières

```
Partagé  : Brain API · ActionProposal · FillRecord · CostModel
           JournalRepository · CausalArchive · ReplayContext
           ResearchRepository · RiskEngine (core) · BrokerAdapter
           RunMode · ExecutionService (core logic)

ALLADIN  : ChallengeWatchdog · Challenge profiles
           MarketUniverse FX · AssetCategory FX
           Stratégies classiques FX

JAFAR    : Session rules 24/7 · FundingRateTracker
           CryptoSymbolMapper · CryptoRiskPolicy
           Exchange adapter natif (futur)

Non-implémenté (cible) :
           AccountBinding · WorkspaceId propagation
           BrokerCapabilities crypto complet
           OrchestrationEngine multi-workspace
           Command Center
           SNN réel · Outcome Engine · Reward
```
