# ALLADIN — Plan d'implémentation

**Mis à jour :** 2026-10-04 · **Base :** `85c29e4` (`main`)
**Autorité :** le code et ses tests établissent l'existant ; les décisions `ADOPTED` de `docs/DECISIONS/` établissent la direction. Une cible documentaire n'est pas une capacité livrée.

---

## 1. Statuts utilisés dans ce document

| Statut | Signification |
|---|---|
| **IMPLEMENTED** | Code présent dans `src/`, tests passent, logique vérifiée |
| **TESTED** | Tests couverts et verts ; recette Windows/MT5 restante indiquée |
| **EXPERIMENTAL** | Architecture adoptée, code non encore implémenté ou résultats non établis |
| **PLANNED** | Décision ADOPTED ou intention documentée ; aucun code associé |

---

## 2. État actuel — HEAD `94cea9d`

**Tests software :** 629 passed, 3 skipped (intégrations MT5 opt-in `--run-mt5`)
**Ruff :** PASS · **mypy :** PASS (85 fichiers source)
**Acceptance workstation :** PASS (ruff + mypy + software)

### Ce qui fonctionne (IMPLEMENTED + TESTED)

| Capacité | Emplacement | Limite connue |
|---|---|---|
| Garde-fous sécurité : compte DEMO, SL obligatoire, token, précontrôle, kill switch | `brokers/base.py`, `brokers/mt5.py`, `execution/service.py`, `risk/engine.py` | Recette MT5 réelle non effectuée depuis Windows |
| Profil challenge (règles officielles/expérimentales séparées) | `challenge/models.py`, `challenge/watchdog.py`, `config/challenge_profiles/` | Plafonds expérimentaux conservateurs |
| Gestion autonome 5 actions (CLOSE, PARTIAL_CLOSE, MODIFY_STOP, MODIFY_TARGET, HOLD) | `risk/engine.py`, `execution/service.py`, `orchestration/engine.py` | Recette MT5 DEMO live non effectuée |
| Confirmation, claim durable, idempotence après reprise | `execution/service.py`, `journal/` | — |
| Isolation workspace Alladin/Jafar : journal, positions, recherche, archive | `core/workspace.py`, migrations | — |
| Catégories crypto, capabilities honnêtes, sessions configurables | `brokers/crypto.py`, `market/sessions.py`, `core/enums.py` | Aucun adapter d'exécution crypto |
| Runtime Jafar OBSERVE : scan spot, archive/replay, brain NO_TRADE, cockpit scoped | `jafar/`, `api/` | Fail-closed PAPER/DEMO/entry/management |
| Binance Spot public + compte USER_DATA read-only Ed25519 + restrictions de clé | `brokers/binance.py`, `brokers/crypto.py` | Aucun endpoint d'ordre ; clé API absente du processus de validation locale |
| Univers Jafar dynamique USDT depuis `exchangeInfo` | `brokers/crypto.py`, `brokers/crypto_observe.py` | Éligibilité liquidité/data quality encore à enrichir |
| Lifecycle ordre exchange persistant/idempotent et réconciliation | `execution/order_lifecycle.py` | Aucun envoi Binance raccordé |
| Valorisation portefeuille Spot et limites concentration/drawdown | `risk/portfolio.py` | Cost basis/corrélations doivent être alimentés par données réelles |
| Modes Jafar OBSERVE/PAPER/TESTNET/LIVE_GATED/LIVE et gates fail-closed | `core/enums.py`, `orchestration/jafar.py` | Runtime/CLI encore OBSERVE uniquement |
| Trades publics, carnet et statistiques 24 h Binance canoniques | `brokers/crypto.py` | Pas encore archivés ni utilisés par l'éligibilité |
| Backtest chronologique (fill next-open, spread, gap SL, règle intrabar) | `research/backtest.py` | Distinct du vrai RiskEngine ; `passed` ≠ preuve OOS |
| Splits chronologiques, scorecards, ResearchRepository, lifecycle de version | `research/splits.py`, `scorecard.py`, `repository.py` | — |
| Outcome/Reward : snapshots immuables, politique hashée, reward versionné, statut INCOMPLETE, contrefactuels NO_TRADE/HOLD | `research/outcome.py`, `research/reward.py` | Aucun entraînement ; brain actif inchangé |
| Archive barres + ReplayContext as-of | `market/archive.py`, `replay.py` | Barres sans close-time explicite ni provenance tick |
| Cockpit Mission Control lecture seule | `api/app.py`, `api/static/index.html` | Journal UI limité aux 40 derniers événements |
| MockBroker, MockAgent, fake MT5 | `brokers/mock.py`, `agents/mock.py`, `tests/fake_mt5.py` | — |

---

## 3. Décisions adoptées

| ID | Titre | État |
|---|---|---|
| 001–012 | Fondations, sécurité, multi-broker, labs, service autonome, Jafar | Voir code |
| 013 | Mode safety sorties protectrices OBSERVE/PAPER | **PROPOSED** non tranchée |
| 014 | Isolation workspaces Alladin/Jafar | **IMPLEMENTED** Lot G |
| 015 | Broker/account bindings, capabilities | **IMPLEMENTED** Lot F/H |
| 016 | Command Center global | **PLANNED** |
| 017 | Causal replay | **IMPLEMENTED** Lot C/D |
| 018 | Parité expérimentale | **IMPLEMENTED** Lot D |
| 019 | Frontière Brain/ActionProposal | **IMPLEMENTED** Lot E |
| 020 | Promotion contrôlée | Architecture cible ; promotion non implémentée |
| 021 | Univers broker dynamique | **IMPLEMENTED** Lot H |
| 022 | Gouvernance Strategy Harvester | Architecture cible ; Harvester non implémenté |
| 023 | Outcomes audités et reward expérimental versionné | **IMPLEMENTED** Lot J |
| 024 | SNN-X extensions parallèles et non destructives | **EXPERIMENTAL** aucun code |
| 025 | SNN-X boucles FAST/LIVE et SLOW/LEARNING | **EXPERIMENTAL** aucun code |
| 026 | SNN-X observation continue | **EXPERIMENTAL** aucun code |
| 027 | SNN-X objectif contraint/homéostasie | **EXPERIMENTAL** aucun code |
| 028 | SNN-X Shadow Brain et promotion contrôlée | **EXPERIMENTAL** aucun code |
| 029 | SNN-X Dream Engine et consolidation | **EXPERIMENTAL** aucun code |
| 030 | Binance Spot natif Jafar, credentials Ed25519 locaux | **IMPLEMENTED** public + compte read-only ; exécution non implémentée |

---

## 4. Lots implémentés

| Lot | Titre | Statut |
|---|---|---|
| A | P0 sécurité : fermeture protectrice et confirmation broker | **IMPLEMENTED** |
| B | Environnement PAPER réel et contrats de modes | **IMPLEMENTED** |
| C | Archive de barres et replay causal | **IMPLEMENTED** |
| D | Protocole expérimental : parité, provenance, OOS | **IMPLEMENTED** |
| E | Interface Brain/ActionProposal, cycle décision/position | **IMPLEMENTED** |
| F | Cycle de vie complet des positions (5 actions), claim, confirmation | **IMPLEMENTED** |
| G | Isolation workspace Alladin/Jafar, migrations | **IMPLEMENTED** |
| H | Catégories crypto, capabilities honnêtes, sessions | **IMPLEMENTED** |
| I | Runtime Jafar OBSERVE isolé, CLI et cockpit scoped | **IMPLEMENTED** |
| J | Outcome/Reward : snapshots, politique hashée, reward versionné | **IMPLEMENTED** |

**Total à fin Lot J :** 629 passed, 3 skipped.

### Ce qui reste ouvert après Lot J

- Recette MT5 DEMO live (Windows) : fermeture/modification/partial close réelles.
- PAPER ne simule pas encore les modifications/fermetures partielles.
- SNN : zéro ligne de code dans `src/`.

---

## 5. Lot K — Recherche SNN expérimentale

### K1 — Fondation SNN minimale et falsifiable (**EN COURS**)

**Localisation :** `src/alladin/research/snn/` (couche research/shadow uniquement)

**Composants minimaux :**

| Composant | Description |
|---|---|
| Neurones LIF déterministes | Leaky Integrate-and-Fire, seed explicite, reproductibilité garantie |
| Encodeur sensoriel déterministe | Conversion features scalaires → trains de spikes |
| R-STDP minimal | Plasticité pondérée par reward versionné (Lot J) |
| Protocole expérimental | Préenregistrement objectif, métrique, seuil, seeds, critère d'abandon |
| Baseline simple | Règle naïve ou moyenne mobile comme contrôle obligatoire |
| Fixtures synthétiques | Données déterministes si données causales insuffisantes |

**Tests obligatoires K1 :**

- Déterminisme avec seed : même seed → même sortie
- Dynamique LIF : potentiel, seuil, reset, fuite
- Comportement R-STDP : mise à jour des poids, bornes
- Absence de lookahead : données passées/présentes uniquement
- Isolation du chemin d'exécution : aucune importation depuis `execution/`, `brokers/`, `orchestration/`
- Aucun `order_send` ni accès broker

**Interdictions K1 :**

- Ne pas modifier `risk/engine.py`, `execution/service.py`, `orchestration/engine.py`
- Ne pas modifier le Brain actif en production
- Ne pas connecter le SNN au broker
- Aucun `order_send`, aucun ordre MT5
- Aucune auto-promotion, aucun transfert automatique FX→Jafar/crypto
- Résultats négatifs acceptables et conservés

### K2 — Shadow Brain intégré (**PLANNED**)

- Brancher le SNN K1 comme Shadow Brain (DECISION-028)
- Observer le même flux causal que le Brain actif sans envoyer d'ordres
- Stocker propositions et simulations, comparer sur horizons préenregistrés
- Évaluer avec les outcomes Lot J

### K3 — Boucles FAST/SLOW séparées (**PLANNED**)

- Séparer chemin d'inférence (FAST) et entraînement/replay (SLOW) — DECISION-025
- Dream Engine : replay causal → consolidation → candidats → validation — DECISION-029

---

## 6. Backlog technique prioritaire

### Jafar — modes persistants

Les modes `OBSERVE`, `PAPER`, `TESTNET`, `LIVE_GATED` et `LIVE` sont explicites
et persistés par run. Les transitions dangereuses ne peuvent pas sauter les
étapes intermédiaires ; tout mode peut revenir vers `OBSERVE`. Ce contrôle
d'état ne constitue jamais une autorisation exchange. Le runtime reste
fail-closed hors `OBSERVE` jusqu'au raccordement de chaque adapter dédié.

| Priorité | Sujet | Statut |
|---|---|---|
| P0 | Recette MT5 DEMO live : fermeture/modification/partial close réelles | **PENDING** Windows requis |
| P0 | Décision 013 : politique sorties protectrices OBSERVE/PAPER | **PROPOSED** non tranchée |
| P1 | PAPER : simulation des modifications/fermetures partielles | **PLANNED** |
| P1 | Archive : close-time explicite, provenance, bid/ask tick | **PLANNED** |
| P1 | Mission Control : historique paginé, fiche décision stable, chart | **PLANNED** |
| P2 | Service autonome : superviseur Windows, heartbeat, checkpoint | **PLANNED** |
| P2 | Strategy Harvester : collecteur, porte provenance/licence | **PLANNED** |
| P2 | Command Center global (DECISION-016) | **PLANNED** |

---

## 7. Protocole expérimental SNN

Préenregistrer **avant** tout OOS :

1. Objectif et métrique primaire (ex. expectancy R OOS net de coûts et drawdown)
2. Seuil minimal d'effet
3. Budget de complexité et nombre de runs/seeds
4. Contrôle des essais multiples
5. Critères d'abandon

Comparaisons obligatoires (mêmes données/features/horizon/coûts/splits/seeds) :

1. Alladin classique (stratégies/routeur)
2. Baseline simple sans SNN (règle naïve, ridge)
3. SNN LIF + readout, gelé puis avec plasticité
4. Ablations appariées : avec/sans R-STDP, avec/sans surprise

Rapporter distribution par seed, régimes, OOS, coûts stressés, drawdown.
Résultats négatifs conservés. OOS reste fermé au réglage.
Aucun modèle de recherche ne passe directement à l'exécution.

---

## 8. Non-objectifs explicites

- Aucun trading LIVE, aucun compte réel, aucun assouplissement des gardes.
- Aucune auto-promotion SNN → Brain actif.
- Aucun World Model complet, Dream Engine complet ou neuroévolution dans K1.
- Aucune surveillance BTC 24/7 sans infrastructure dédiée effectivement allumée.
- Aucun transfert automatique de paramètres FX → Jafar/crypto.

---

## 9. Critères d'acceptation transversaux

1. Aucune nouvelle entrée LIVE/CONTEST/UNKNOWN ; SL et token obligatoires.
2. Toute décision a ID, horodatage, version cerveau/stratégie, proposition, résultat risque, mode.
3. Rejeu d'un cycle avec données archivées → même contexte ou erreur d'intégrité.
4. Un résultat OOS ne sert pas au réglage ; toute promotion réclame comparaison préenregistrée avec baseline et rollback possible.
5. Tests sécurité, causalité, intégrité et restart passent ; historique journal/recherche immuable.

---

*Checkpoints historiques des lots A–J conservés dans l'historique git (commit `0660057` et antérieurs).*
