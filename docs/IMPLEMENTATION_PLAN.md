# ALLADIN — Plan d'implémentation

## Point de reprise mesurable de cette session

| Chantier | Code livré | Limite restante |
|---|---|---|
| A Conformité | contraintes injectées, protections/revue, tests de compte | règles/horaires réels et réservations multi-processus |
| B Économie | BLS/BEA, réception causale, partial coverage fail-closed | couverture composite, archivage durable, mapping et licence |
| C Runtime | checkpoint opt-in OBSERVE/PAPER et audit SL/TP PAPER | configuration persistante et recette broker DEMO |
| D Challenge Factory | 16 scénarios appariés reproductibles, coûts/états | trailing/portefeuille et performances réelles non modélisés |
| E Qualité | rapports hashés, API de preuves/incidents | uptime/endurance inconnus, cockpit graphique inchangé |

Les statuts historiques ci-dessous restent conservés ; les blocs datés ci-dessus décrivent l’état opérationnel actuel.


## Lot 6 — 2026-10-08 : campagnes et preuves opérationnelles PAPER

Base `0b030ed`. `challenge/factory.py` et script `report_challenge_campaign.py` : seize replays appariés (deux profils SYNTHÉTIQUES × deux allocations nominales × quatre chemins). PolicyGate d'entrée + watchdog existant, reset avant perte, arrêt au creux éliminatoire, phases/restart, annonces/pannes. Drawdown aux points observés, cas inachevés conservés, frais/coûts/récompenses explicitement hypothétiques. Aucune stratégie, probabilité réelle ou cash généré inféré ; compte/récompense absents restent null. Les contraintes avancées non raccordées sont rejetées, jamais ignorées. Voir `docs/CHALLENGE_CAMPAIGNS.md`, fixtures et rapport versionnés.

Qualité : refus, raisons d'indisponibilité, correspondance des attentes labellisées ; contexte complet hashé dans le journal et direction LONG/SHORT du provider vérifiée. Un contexte changé avec même verdict devient un incident de replay. Audit après fill natif SL/TP PAPER : protection préservée, conflit contractuel ou panne journalisés, pas d'assimilation à une proposition refusée. API /api/policy distingue refus pré-proposition et revues après fill simulé ; aucun changement de routes existantes ni interface cockpit.

Validation finale : **498 passed** ciblés ; suite finale **1435 passed, 3 skipped MT5, 0 failed, 1 warning Starlette**, 132.41 s. Ruff src/tests/deux scripts : **PASS**. Mypy src/deux scripts : **PASS, 112 fichiers**. Diff --check : **PASS**. Environnement, hash du code/fixtures, commandes et skips exacts : `docs/reports/policy_software_current.json`.
Deux rapports régénérés octet par octet à l'identique. Une suite intermédiaire avait **1431 passed, 2 failed, 3 skipped** : les deux fixtures SL PAPER laissaient MockAgent ouvrir une nouvelle position après la clôture ; fixture corrigée en NO_TRADE et étendue aux TP. Aucune protection supprimée pour obtenir un PASS.

Reprise commune Claude/Codex : lire ce bloc puis les lots 4/5, PUBLIC_CALENDAR.md et CHALLENGE_CAMPAIGNS.md. Prochain lot logiciel : admission persistante de profils par compte/phase + composite calendrier causal à couverture vérifiable, archive de réception/licence/mapping, réservations atomiques de risques/expositions, replay trailing/overnight/portefeuille raccordé au runtime. Le checkpoint reste opt-in OBSERVE/PAPER et le collecteur n'est pas activé automatiquement. Aucun contrat réel admis, aucun LIVE/DEMO activé, aucune modification Brain/RiskEngine/Jafar/SNN-X, aucun compte financier ni achat.

À réaliser sur Windows/MT5 DEMO : terminal et liaison serveur/compte, ownership/magic, règles horaires réelles, fills SL/TP et restrictions d'annonces, latences/slippage, pannes/redémarrages/reconciliation et endurance. Performance OOS et probabilités de validation exigent ensuite des données/expériences, pas une extrapolation des quatre chemins synthétiques. Pas de readiness 24/7 ni rendement démontré.

---


## Lot 5 — 2026-10-08 : sources publiques et checkpoint OBSERVE/PAPER

Base `1ca8fa2`. Adaptateurs à URLs fixes BLS ICS, BEA ICS/JSON, GET borné sans identifiants/redirects, provenance SHA-256, réception causale, SEQUENCE/DST/révisions, rejet des calendriers incertains. Couverture explicitement partielle : OPEN bloqué, gestion transactionnelle REVIEW. Documentation `docs/PUBLIC_CALENDAR.md`. Smoke réel : BLS ICS 313 événements (hash 92a350111ace106deaab5584e4084366bd367b594a0d0bad116008d82d63e501), BEA ICS 166 (c6320686f93a1200c1226ed92eed1c7d2531491006b6da7099fadaab57c433e9). BEA JSON a révélé la métadonnée file_last_updated : schéma corrigé/testé offline ; la tentative de téléchargement suivante a expiré, pas de PASS réseau JSON annoncé.

`PolicyController` injecté explicitement dans Components.engine : uniquement OBSERVE/PAPER, compte/journal/instant/symbole vérifiés, panne du provider fail-closed, ALLOW seul poursuit vers RiskEngine/exécution PAPER existants. Les six actions OPEN/CLOSE/PARTIAL_CLOSE/MODIFY_STOP/MODIFY_TARGET/HOLD sont testées ; aucune modification du Brain actif ni activation globale. Journal policy.decision/policy.incident, déduplication après restart, divergence de replay refusée. GET read-only /api/policy : refus, disponibilité par décision (pas uptime), incidents et intégrité ; aucune qualification automatique. Les protections SL/TP PAPER natives restent actives avant le checkpoint.

Tests ciblés : **88 passed, 1 warning**. Suite générale : **1416 passed, 3 skipped MT5, 1 warning Starlette**, 131.03 s, JUnit /tmp/alladin-lot5.xml. Ruff src/tests/script rapport : **PASS** ; mypy src + script rapport : **PASS, 110 fichiers** ; diff --check : PASS. Les erreurs initiales des nouveaux tests (mauvais noms d'API MockBroker/contexte) ont été corrigées avant cette suite finale.

Limites : collecteur/composite calendrier non configuré, licence/couverture/mapping contractuel à vérifier ; BEA JSON ne garantit pas un ID stable entre dates ; contraintes de compte sans réservations atomiques multi-processus ; conformité des fills natifs et MT5 DEMO/endurance non certifiée ; aucune admission officielle ni permission d'exécution. Suite : campagnes synthétiques reproductibles et rapports. Windows/MT5/comptes toujours inutilisés.

---


## Lot 4 — 2026-10-08 : contraintes de compte et protection

Base `8a48b5b`. Ajout `challenge/account_policy.py` et champ optionnel `FirmProfile.constraints` : sessions/actions permises, weekend et durée de coupure configurés via horaires injectés, drawdown static/trailing_balance/trailing_equity/trailing_eod avec état sérialisable, limites agrégées de positions/risque/groupes et opposition inter-comptes sur un scope explicite en devise commune. Données expirées/manquantes/divergentes : OPEN bloqué, gestion/HOLD soumis à revue. Pas de règles officielles codées par défaut ; legacy inchangé sans contraintes.

Protection : CLOSE/PARTIAL_CLOSE protecteur n'est pas retardé par la simple précaution stratégique si conforme ; une restriction contractuelle d'annonce reste REVIEW, jamais une permission de contourner. HOLD avec protection native signalée détecte le conflit SL/TP ; aucune modification du stop broker. Un cutoff imminent demande une clôture complète, pas un simple changement de stop. Aucun raccordement à ExecutionService dans ce lot.

Tests ciblés : **431 passed** (49 nouveaux). Suite : **1368 passed, 3 skipped MT5, 1 warning Starlette**, 116.92 s. Ruff src/tests/script rapport : PASS ; mypy src + script rapport : PASS (108 fichiers) ; diff --check : PASS. État trailing restauré et updates causaux testés ; la disponibilité/complétude des snapshots et les high water marks nécessitent toujours une collecte fiable.

Suite : ingestion publique partielle et contrôleur OBSERVE/PAPER opt-in, campagnes de simulation et reporting. Les contrats par compte, horaires réels, conversions/expositions exhaustives et protection native restent non certifiés ; aucune activation DEMO/LIVE, aucun accès financier, aucun changement Brain/Jafar/SNN-X ni migration.

---


## État courant — 2026-10-08 : validation offline

PolicyGate durci, calendrier offline causal, fixtures synthétiques, matrice de conformité et rapports audités : **IMPLEMENTED + TESTED ISOLATED**. Voir `POLICY_VALIDATION.md` et le dernier lot de `HANDOFF.md` pour les résultats exacts. Les notes de création ci-dessous sont historiques. Restent **NOT INTEGRATED / NOT QUALIFIED** : fournisseur réel/licencié, contrats officiels par compte, sortie protectrice/SL/TP broker, conformité dans ExecutionService, exposition multi-comptes, MT5 DEMO et soak. Aucun LIVE.

---


## Complément 2026-10-08 — lot PolicyGate sans MT5

- **IMPLEMENTED ISOLATED** : `src/alladin/challenge/policy_gate.py`, évaluation déterministe composée (OPEN, CLOSE, PARTIAL_CLOSE, MODIFY_STOP, MODIFY_TARGET, HOLD).
- **ADDED / NOT RUN HERE** : `tests/test_policy_gate.py` (restrictions macro, calendrier absent, profil absent, firme, sortie/revue).
- **NOT INTEGRATED** : tout raccordement à `ExecutionService`, acquisition de données de calendrier, profils de firmes réels, gestion de SL/TP côté broker, qualification 24/7.
- Prochaine étape sans MT5 : `python -m pytest tests/test_propfirm_policy_foundations.py tests/test_policy_gate.py -q`, lint/typecheck, tests causaux / limites et REVIEW de l'architecture des sorties.

---


**Mis à jour :** 2026-10-05 · **Base :** lot Mission Control/soak courant (`main`)
**Autorité :** le code et ses tests établissent l'existant ; les décisions `ADOPTED` de `docs/DECISIONS/` établissent la direction. Une cible documentaire n'est pas une capacité livrée.

---

## Lot politique multi-firmes / macro — 2026-10-08

| Livrable | Statut | Preuve / prochaine validation |
|---|---|---|
| EventPolicy : snapshots de calendrier, as-of et verdict BLOCK/DEFER/ALLOW | **IMPLEMENTED (module isolé)** | `src/alladin/challenge/event_policy.py` ; tests unitaires ajoutés, non exécutés ici |
| FirmProfile + contrôles d'entrée | **IMPLEMENTED (module isolé)** | `src/alladin/challenge/firm_policy.py` ; pas de profil live homologué |
| Ledger : cash réellement encaissé vs compte simulé | **IMPLEMENTED (module isolé)** | `src/alladin/challenge/capital_metrics.py` |
| Tests de ces fondations | **ADDED / NOT RUN IN THIS SESSION** | `tests/test_propfirm_policy_foundations.py` |
| Fournisseur macro, collecte/version/synchronisation et classification de symboles | **PLANNED** | données historiques causales + intégrité + licences |
| ComplianceGate intégré au runtime (entrée et sorties) | **PLANNED** | MT5 DEMO, multi-compte, news, SL/TP et restart |
| Configuration de firmes validées contractuellement | **PLANNED** | sources officielles et dates d'effet, revue humaine |
| Qualité & performance, scorecards + Mission Control | **PLANNED** | simulation OOS, coûts, reward/cash net, incidents |
| Fonctionnement autonome réellement qualifié 24/7 | **NOT VALIDATED** | soak et fault injection sur hôte disponible |

**Règle de vérité :** ces modules ne reçoivent aucun ordre broker ; ils ne sont pas encore branchés à `ExecutionService`. FTMO Standard funded peut interdire ouvertures **et fermetures y compris SL/TP** autour de certaines annonces (±2 minutes) ; les profils doivent être vérifiés et les sorties existantes traitées distinctement. Voir `AGENTS.md`, `docs/CODEX_HANDOFF.md`, `docs/CLAUDE_HANDOFF.md` et décisions 032-035.

---

## 1. Statuts utilisés dans ce document

| Statut | Signification |
|---|---|
| **IMPLEMENTED** | Code présent dans `src/`, tests passent, logique vérifiée |
| **TESTED** | Tests couverts et verts ; recette Windows/MT5 restante indiquée |
| **EXPERIMENTAL** | Architecture adoptée, code non encore implémenté ou résultats non établis |
| **PLANNED** | Décision ADOPTED ou intention documentée ; aucun code associé |

---

## 2. État actuel — HEAD `22a608a`

**Tests software :** voir `docs/CLAUDE_HANDOFF.md` pour la validation exacte du lot
**Ruff :** PASS · **mypy :** PASS sur les fichiers/checkpoints récents
**Acceptance workstation :** PASS (ruff + mypy + software)

### Ce qui fonctionne (IMPLEMENTED + TESTED)

| Capacité | Emplacement | Limite connue |
|---|---|---|
| Garde-fous sécurité : compte DEMO, SL obligatoire, token, précontrôle, kill switch | `brokers/base.py`, `brokers/mt5.py`, `execution/service.py`, `risk/engine.py` | Ouverture DEMO réelle validée ; lifecycle complet restant |
| Profil challenge (règles officielles/expérimentales séparées) | `challenge/models.py`, `challenge/watchdog.py`, `config/challenge_profiles/` | Plafonds expérimentaux conservateurs |
| Gestion autonome 5 actions (CLOSE, PARTIAL_CLOSE, MODIFY_STOP, MODIFY_TARGET, HOLD) | `risk/engine.py`, `execution/service.py`, `orchestration/engine.py` | Recette MT5 DEMO live non effectuée |
| Confirmation, claim durable, idempotence après reprise | `execution/service.py`, `journal/` | — |
| Isolation workspace Alladin/Jafar : journal, positions, recherche, archive | `core/workspace.py`, migrations | — |
| Catégories crypto, capabilities honnêtes, sessions configurables | `brokers/crypto.py`, `market/sessions.py`, `core/enums.py` | Aucun adapter d'exécution crypto |
| Runtime Jafar OBSERVE/PAPER : scan → Brain → Risk → lifecycle → simulation, health et reprise | `jafar/`, `orchestration/health.py`, `api/` | Boucle réelle crypto-public validée en smoke test ; soak 2–4h/24h restant |
| Binance Spot public + compte USER_DATA read-only Ed25519 + restrictions de clé | `brokers/binance.py`, `brokers/crypto.py` | Aucun endpoint d'ordre ; clé API absente du processus de validation locale |
| Univers Jafar dynamique USDT depuis `exchangeInfo` | `brokers/crypto.py`, `brokers/crypto_observe.py` | Éligibilité liquidité/data quality encore à enrichir |
| Lifecycle ordre exchange persistant/idempotent et réconciliation | `execution/order_lifecycle.py` | Aucun envoi Binance raccordé |
| Valorisation portefeuille Spot et limites concentration/drawdown | `risk/portfolio.py` | Cost basis/corrélations doivent être alimentés par données réelles |
| Modes Jafar OBSERVE/PAPER/TESTNET/LIVE_GATED/LIVE et gates fail-closed | `core/enums.py`, `orchestration/jafar.py` | OBSERVE et PAPER raccordés ; TESTNET/LIVE non autonomes |
| Trades publics, carnet et statistiques 24 h Binance canoniques | `brokers/crypto.py` | Pas encore archivés ni utilisés par l'éligibilité |
| Backtest chronologique (fill next-open, spread, gap SL, règle intrabar) | `research/backtest.py` | Distinct du vrai RiskEngine ; `passed` ≠ preuve OOS |
| Splits chronologiques, scorecards, ResearchRepository, lifecycle de version | `research/splits.py`, `scorecard.py`, `repository.py` | — |
| Outcome/Reward : snapshots immuables, politique hashée, reward versionné, statut INCOMPLETE, contrefactuels NO_TRADE/HOLD | `research/outcome.py`, `research/reward.py` | Aucun entraînement ; brain actif inchangé |
| Archive barres + ReplayContext as-of | `market/archive.py`, `replay.py` | Barres sans close-time explicite ni provenance tick |
| Cockpit Mission Control lecture seule + Runtime Health UI | `api/app.py`, `api/static/index.html` | Mode/banner PAPER et sélection du run actif corrigés ; soak réel restant |
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
| 024 | SNN-X extensions parallèles et non destructives | **IMPLEMENTED foundation / EXPERIMENTAL results** |
| 025 | SNN-X boucles FAST/LIVE et SLOW/LEARNING | **FOUNDATION IMPLEMENTED** |
| 026 | SNN-X observation continue | **IMPLEMENTED in shadow/observe path** |
| 027 | SNN-X objectif contraint/homéostasie | **EXPERIMENTAL** aucun code |
| 028 | SNN-X Shadow Brain et promotion contrôlée | **Shadow Brain IMPLEMENTED; promotion not implemented** |
| 029 | SNN-X Dream Engine et consolidation | **SLOW boundary implemented; Dream Engine incomplete** |
| 030 | Binance Spot natif Jafar, credentials Ed25519 locaux | **IMPLEMENTED** public/read-only + TESTNET adapter/execution chain ; LIVE remains gated |

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
| J-PAPER | Boucle Jafar PAPER scanner → Brain → Risk → lifecycle → position | **IMPLEMENTED + TESTED** |
| J-HEALTH | Health runtime, heartbeat, stale detection, backoff/recovery, graceful shutdown | **IMPLEMENTED + TESTED** |
| J-ENDURANCE | Harness 100/1000 cycles, fault injection, restart/duplicate/SL-TP stress | **IMPLEMENTED + TESTED** |
| J-SOAK-TOOLS | Rapport read-only, validator invariants et qualification SHORT_SMOKE/2H/24H | **IMPLEMENTED + TESTED** |

**Validation actuelle :** 907 passed, 3 skipped.

### Ce qui reste ouvert après Lot J

- Recette MT5 DEMO live (Windows) : ouverture réelle validée ; fermeture/modification/partial close + restart restent à valider.
- PAPER/endurance est validé logiciellement ; SHORT SMOKE réel validé, 2–4 h et 24 h non validés.
- Mission Control affiche le bon mode/banner et préfère le run actif pertinent.
- Packaging Linux/systemd est implémenté/testé structurellement ; déploiement serveur reste à faire.
- SNN K1/K2 et frontière FAST/SLOW existent ; résultats expérimentaux non établis.

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

### K2 — Shadow Brain intégré (**IMPLEMENTED, passif**)

- Brancher le SNN K1 comme Shadow Brain (DECISION-028)
- Observer le même flux causal que le Brain actif sans envoyer d'ordres
- Stocker propositions et simulations, comparer sur horizons préenregistrés
- Évaluer avec les outcomes Lot J

### K3 — Boucles FAST/SLOW séparées (**FOUNDATION IMPLEMENTED**)

- Séparer chemin d'inférence (FAST) et entraînement/replay (SLOW) — DECISION-025
- Dream Engine : replay causal → consolidation → candidats → validation — DECISION-029

Le runtime Jafar OBSERVE transmet désormais les candidats du scan au Shadow
Brain K2 dans le chemin FAST. Les propositions simulées, confiance, incertitude
et version sont journalisées ; aucune référence d'exécution n'est accessible et
les poids restent inchangés durant le cycle. `ShadowSlowLoop` constitue la
frontière explicite où outcomes, reward R-STDP et métriques candidat sont traités
hors chemin critique. Aucun candidat n'est promu automatiquement.

---

## 6. Backlog technique prioritaire

### Jafar — modes persistants

Les modes `OBSERVE`, `PAPER`, `TESTNET`, `LIVE_GATED` et `LIVE` sont explicites
et persistés par run. Les transitions dangereuses ne peuvent pas sauter les
étapes intermédiaires ; tout mode peut revenir vers `OBSERVE`. Ce contrôle
d'état ne constitue jamais une autorisation exchange. Le runtime reste
fail-closed hors `OBSERVE` jusqu'au raccordement de chaque adapter dédié.

Le runtime `crypto-public` est raccordé à la découverte Spot Binance dynamique.
Il classe le catalogue complet, journalise les trois catégories d'éligibilité,
puis borne le scan actif à une sélection issue du volume 24 h et du spread. Les
paires USDT et USDC partagent cette mécanique, sans liste de symboles figée.

La reprise Jafar raccorde désormais le registre lifecycle à une reconciliation
Binance read-only par `clientOrderId`. Les ordres ambigus, ouverts et partiellement
exécutés sont inspectés avant le runtime. Toute absence ou erreur demeure
`PENDING_CONFIRMATION`/ambiguë et bloque le démarrage au lieu de resoumettre.

| Priorité | Sujet | Statut |
|---|---|---|
| P0 | Recette MT5 DEMO live : ouverture | **VALIDATED MANUALLY** ; management/close/restart restants |
| P0 | Décision 013 : politique sorties protectrices OBSERVE/PAPER | **PROPOSED** non tranchée |
| P1 | PAPER : endurance accélérée + pannes/restart/SL-TP | **IMPLEMENTED + TESTED** ; long-run réelle restant à valider |
| P1 | PAPER : simulation des modifications/fermetures partielles | **PLANNED** |
| P1 | Archive : close-time explicite, provenance, bid/ask tick | **PLANNED** |
| P1 | Mission Control : runtime health/freshness/failures | **IMPLEMENTED + TESTED** |
| P0 | Mission Control Jafar PAPER : source run_mode/banner cohérente | **IMPLEMENTED + TESTED** |
| P1 | Service autonome : packaging Linux/systemd, secrets, logs, auto-restart | **IMPLEMENTED + TESTED structurally** ; terrain non déployé |
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
