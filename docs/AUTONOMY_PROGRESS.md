# ALLADIN — État d'avancement vers l'autonomie

**Date de référence :** 2026-10-05  
**Branche :** `main`  
**HEAD vérifié :** `22a608a`  
**Dernière validation logicielle connue :** **907 tests passed, 3 skipped (MT5)**  
**Validation manuelle poste (2026-10-05) :** MT5 DEMO order pipeline confirmé + Jafar PAPER crypto-public en boucle continue + Binance read-only authentifié.

> Ce document est un tableau de bord de progression. Le code et les tests restent la source de vérité pour ce qui est réellement implémenté. Les pourcentages ci-dessous sont des **indicateurs de readiness**, pas une mesure mathématique du nombre de lignes de code réalisées.

---

## 1. Résumé exécutif

Alladin n'est plus au stade de prototype architectural. Le socle principal est largement implémenté : orchestration, journalisation, risque, lifecycle d'ordres, replay, outcomes, workspaces Alladin/Jafar, cockpit, Jafar OBSERVE/PAPER, adapter Binance Testnet, réconciliation au redémarrage et fondations SNN-X.

La prochaine cible réaliste n'est **pas** le LIVE. La cible est :

> **Alladin/Jafar autonome 24/7 sur serveur en OBSERVE/PAPER, capable de survivre aux redémarrages, de se réconcilier, de journaliser son état et de s'arrêter en sécurité.**

Une fois cette cible atteinte, le serveur peut devenir le laboratoire permanent pour les expériences SNN-X, le Shadow Brain et les validations TESTNET.

---

## 2. Progression actuelle

| Bloc | Readiness estimée | État vérifié | Reste principal |
|---|---:|---|---|
| Core Alladin / architecture | **92%** | Très avancé | stabilisation et dette mineure |
| Journal / event sourcing | **92%** | Implémenté | enrichissement et observabilité |
| Risk Engine / garde-fous | **88%** | Implémenté et testé | recette endurance + cas réels |
| Opportunity / orchestration | **82%** | Implémenté | qualité de sélection et validation terrain |
| MT5 / Forex lifecycle | **86%** | ouverture DEMO réelle confirmée via RiskEngine → order_check → positions_get → journal | MODIFY_STOP / MODIFY_TARGET / PARTIAL_CLOSE / CLOSE + restart réel à valider |
| Replay causal / archive | **86%** | Implémenté | provenance tick/bid/ask plus fine |
| Outcomes / Reward | **82%** | Implémenté | exploiter les outcomes pour apprentissage/promotion |
| Mission Control | **90%** | Runtime Health UI opérationnelle et connectée aux données réelles | corriger cohérence Jafar PAPER : MODE N/A / banner OBSERVE-only / run-mode source |
| Jafar OBSERVE | **95%** | Fonctionnel | endurance 24/7 |
| Jafar PAPER engine | **94%** | boucle continue réelle sur `crypto-public` observée avec cycles successifs ; endurance déterministe déjà testée | soak 2–4h puis 24h, avec rapport final |
| Jafar Order Lifecycle | **88%** | Implémenté | tests d'intégration exchange prolongés |
| Jafar restart reconciliation | **88%** | Implémenté, fail-closed | validation avec cas exchange réels |
| Binance Testnet adapter | **72%** | submit/query/cancel implémentés, garde URL stricte | recette réelle TESTNET + intégration runtime continue |
| Jafar Execution Service | **78%** | TESTNET/LIVE_GATED/LIVE chain implémentée | raccordement opérationnel et validation bout en bout |
| SNN K1 | **82%** | fondations LIF/encodeur/R-STDP présentes | calibration expérimentale + benchmarks |
| Shadow Brain K2 | **65%** | intégré passivement au flux Jafar | comparaison outcomes à grande échelle |
| FAST/SLOW K3 foundation | **45%** | frontière FAST/SLOW présente | boucle learning complète + critères de promotion |
| World Model | **20%** | décision/architecture | runtime expérimental |
| Dream Engine | **25%** | frontière slow/replay prévue | consolidation et candidats réellement entraînés |
| Crash recovery global | **86%** | restart, restore, anti-duplication et fault injection testés | validation longue avec pannes réelles + supervision OS |
| Kill switches / fail-closed | **84%** | FAILED/STALE/STOPPING bloquent les nouvelles entrées ; tests endurance | validation terrain et supervision externe |
| Observabilité 24/7 | **84%** | heartbeat, health persistant, stale/provider state, API et UI Mission Control | alerting externe + validation long-run |
| Daemon/service autonome | **88%** | boucle continue, backoff, SIGINT/SIGTERM, graceful shutdown, health, exit 3 fail-closed | long-run réelle |
| Déploiement Linux | **82%** | units systemd, EnvironmentFile, install.sh, backup, verify.sh, DEPLOY_LINUX.md, 38 tests structurels | déploiement réel sur serveur |
| Serveur dédié | **10%** | non déployé | infrastructure physique + recette terrain |
| Autonomie OBSERVE/PAPER sur serveur | **~89%** | runtime réel + observabilité + packaging prêts ; smoke tests Windows concluants | corriger cockpit Jafar PAPER, soak réel, déploiement terrain |
| Autonomie LIVE fiable | **~35%** | volontairement bloquée | preuves statistiques + TESTNET/DEMO prolongés + autorisation explicite |


---

## 3. Graphes de progression

Pour éviter les libellés illisibles, la progression est séparée en deux vues.

### 3.1 Socle trading et exécution

```mermaid
xychart-beta
    title "Alladin — trading et execution"
    x-axis ["Core", "Risk", "MT5", "Jafar OBS", "Jafar PAPER", "Testnet"]
    y-axis "Readiness (%)" 0 --> 100
    bar [92, 88, 82, 95, 92, 72]
```

### 3.2 Intelligence, résilience et infrastructure

```mermaid
xychart-beta
    title "Alladin — intelligence et infrastructure"
    x-axis ["SNN K1", "Shadow K2", "Recovery", "Observ.", "Daemon", "Linux", "Serveur"]
    y-axis "Readiness (%)" 0 --> 100
    bar [82, 65, 86, 84, 88, 82, 10]
```

### 3.3 Chemin critique vers le serveur

```mermaid
flowchart LR
    A["Endurance harness<br/>IMPLEMENTED + TESTED"] --> B["Mission Control health<br/>IMPLEMENTED + TESTED"]
    B --> C["Packaging Linux<br/>systemd / secrets / backups"]
    C --> D["Long-run PAPER<br/>données publiques réelles"]
    D --> E["Recette MT5 DEMO<br/>lifecycle réel"]
    E --> F["Serveur dédié<br/>OBSERVE / PAPER 24/7"]
    F --> G["TESTNET prolongé"]
    G --> H["SNN-X K2/K3<br/>apprentissage continu"]
    H --> I["LIVE_GATED<br/>si preuves suffisantes"]
```

> **Readiness globale vers l'objectif serveur OBSERVE/PAPER : ~89 %.**  
> Le graphe représente l'état du code au HEAD de référence et ne remplace pas les validations d'endurance ou les recettes broker réelles.

---

## 4. Corrections par rapport aux anciennes estimations

Les estimations précédentes sous-évaluaient plusieurs blocs.

### Jafar PAPER

Ce n'est plus un simple squelette.

Le commit `347c6f1` ajoute notamment :

- `JafarPaperEngine` ;
- données Binance réelles avec exécution simulée ;
- slippage déterministe ;
- lifecycle `PROPOSED → FILLED` ;
- suivi cash, capital, PnL, drawdown et fees ;
- surveillance SL/TP ;
- restauration des positions au redémarrage ;
- commandes CLI `jafar positions`, `jafar open-orders`, `jafar reconcile`.

La CLI PAPER exécute désormais scanner → `JafarPaperBrain` baseline → `ActionProposal`
→ sizing `RiskEngine` → lifecycle → fill simulé → position persistée. Les biais SELL
restent abstention : Binance Spot ne doit pas être traité comme un marché permettant
d'ouvrir un short. L'idempotence d'une même proposition est testée.

Cette validation est désormais renforcée par un **Paper Endurance Harness** déterministe :
100 et 1 000 cycles propres, pannes provider, stale data, restart, duplicate storm,
SL/TP, graceful shutdown, fail-closed et replay même seed ont été testés sans
invariant failure. Cela reste une validation logicielle accélérée : une vraie session
longue 24/7 sur données publiques réelles reste à effectuer.

### Binance TESTNET

L'adapter n'est plus seulement planifié.

`BinanceTestnetOrderClient` et la chaîne d'exécution Jafar existent avec :

- séparation stricte du domaine Testnet ;
- garde avant toute écriture ;
- `clientOrderId` préfixé `jfr-` ;
- submit/query/cancel ;
- aucun renvoi automatique après timeout ;
- passage en `PENDING_CONFIRMATION` quand l'état exchange est incertain.

Il reste surtout la **recette réelle TESTNET** et le raccordement opérationnel permanent.

### Réconciliation au restart

La réconciliation est désormais une capacité réelle.

`JafarRestartReconciler` traite notamment :

- ordre local absent de l'exchange ;
- ordre rempli pendant une interruption ;
- partial fill ;
- annulation/expiration ;
- réponse perdue ;
- état ambigu ;
- ordre présent sur l'exchange mais inconnu localement.

Le principe est fail-closed : en cas d'ambiguïté, le runtime ne doit pas improviser ni resoumettre.

### SNN-X

La documentation historique qui indique « zéro ligne de code SNN » est obsolète.

K1 existe et K2 est déjà intégré en Shadow Brain passif. La frontière FAST/SLOW est également présente. En revanche, **cela ne signifie pas que le SNN est validé comme meilleur trader** : il reste un système expérimental qui doit gagner le droit d'être promu à partir de résultats OOS et d'outcomes comparables.

---

## 5. Chemin critique avant serveur autonome

### Étape A — Endurance logicielle PAPER (**IMPLEMENTED + TESTED**)

Le harness déterministe couvre déjà 100/1 000 cycles, pannes provider, stale data,
restart, duplications, SL/TP, graceful shutdown et fail-closed, avec rapport d'invariants.

**Reste :** transformer cette preuve accélérée en vraie session longue sur données Binance publiques réelles.

### Étape B — Terminer la recette MT5 réelle

Le code du lifecycle Forex est déjà largement présent.

À valider depuis Windows/MT5 DEMO :

- ouverture ;
- MODIFY_STOP ;
- MODIFY_TARGET ;
- PARTIAL_CLOSE ;
- CLOSE ;
- restart sans double ordre ;
- reconciliation avec l'état réel du broker.

### Étape C — Runtime 24/7 robuste (**fondation IMPLEMENTED + TESTED**)

Déjà présents :
- heartbeat persistant ;
- health states HEALTHY/DEGRADED/STALE/STOPPING/STOPPED/FAILED ;
- stale-data detection ;
- backoff/recovery provider ;
- fail-closed ;
- graceful SIGINT/SIGTERM ;
- restart/restore sans duplication dans le harness.

**Reste :** supervision OS/auto-restart et validation sur panne/réseau réels.

### Étape D — Observabilité serveur (**Mission Control health IMPLEMENTED + TESTED**)

Mission Control montre désormais le runtime health. Le périmètre opérationnel cible reste :

- état du runtime ;
- dernier heartbeat ;
- broker connecté/déconnecté ;
- dernière donnée marché ;
- dernière décision ;
- positions ;
- exposition ;
- PnL ;
- drawdown ;
- erreurs ;
- ordre en attente de confirmation ;
- état du Shadow Brain.

### Étape E — Déploiement Linux

Préparer :

- environnement reproductible ;
- secrets séparés du code ;
- stockage persistant ;
- migrations ;
- logs ;
- backup ;
- rotation ;
- service `systemd` ou conteneur ;
- auto-start après reboot ;
- health check.

**À la fin de cette étape : le PC personnel peut être éteint sans interrompre Alladin.**

---

## 6. Ce qui peut continuer après le déploiement serveur

Le serveur ne nécessite pas que toute la recherche soit terminée.

Les blocs suivants peuvent progresser pendant qu'Alladin fonctionne en OBSERVE/PAPER :

1. calibration SNN K1 ;
2. collecte d'outcomes Shadow Brain ;
3. comparaison Brain classique / SNN ;
4. K3 promotion gating ;
5. World Model ;
6. Dream Engine ;
7. Strategy Harvester ;
8. optimisation des features et régimes ;
9. expérimentations OOS.

Le serveur doit donc être vu comme **le laboratoire permanent d'Alladin**, pas comme la récompense obtenue seulement lorsque toute la recherche est terminée.

---

## 7. Conditions minimales pour déclarer « Alladin tourne de ses propres ailes »

La mention **AUTONOMOUS PAPER READY** ne doit être utilisée que si toutes les conditions suivantes sont vérifiées :

- [ ] runtime stable pendant une fenêtre prolongée sans intervention (smoke multi-cycles réel OK, soak restant) ;
- [x] restart logique sans duplication dans les tests/harness ;
- [ ] reconciliation cohérente après restart ;
- [x] PAPER ouvre et ferme des positions simulées dans les tests/harness ;
- [x] SL/TP et management de position validés logiciellement ;
- [x] heartbeat/health runtime opérationnels ;
- [ ] superviseur OS/watchdog externe opérationnel ;
- [x] stale market data détectée et bloque l'entrée ;
- [x] pannes provider simulées gérées avec backoff/fail-closed ;
- [ ] panne provider/réseau réelle validée sur longue durée ;
- [ ] kill switch testé ;
- [ ] logs et journal permettent de reconstruire un incident ;
- [x] Mission Control montre l'état runtime opérationnel ;
- [ ] service démarre automatiquement après reboot serveur ;
- [ ] secrets non stockés dans Git ;
- [ ] backup/persistence testés ;
- [x] suite software verte au checkpoint : 869 passed, 3 skipped ;
- [ ] recette d'acceptation serveur documentée.

---

## 8. Ce que « autonome » ne veut pas dire

Autonome ne signifie pas :

- trader en LIVE sans validation ;
- promouvoir automatiquement un modèle expérimental ;
- supprimer les garde-fous ;
- faire confiance à un SNN parce qu'il est complexe ;
- considérer un backtest positif comme une preuve de rentabilité future ;
- resoumettre un ordre quand l'état exchange est inconnu.

Autonome signifie :

> **observer, décider, exécuter dans le mode autorisé, gérer ses positions, persister son état, détecter ses erreurs, se réconcilier après interruption et s'arrêter en sécurité sans dépendre d'un humain devant le terminal.**

---

## 9. Priorité de travail recommandée

Ordre de priorité actuel :

```text
1. Corriger cohérence Mission Control Jafar PAPER
        ↓
2. Long-run PAPER sur données Binance publiques réelles
        ↓
3. Recette MT5 DEMO lifecycle réelle
        ↓
5. Déploiement serveur OBSERVE/PAPER
        ↓
6. TESTNET prolongé
        ↓
7. SNN-X K2/K3 + apprentissage expérimental continu
        ↓
8. LIVE_GATED uniquement après preuves suffisantes
```

---

## 10. Indicateur global

À partir du code présent au HEAD `22a608a` :

- **Socle logiciel général : ~88–90 %**
- **Jafar OBSERVE/PAPER : ~90–93 %**
- **Résilience/reconciliation : ~85–88 %**
- **SNN-X opérationnel expérimental : ~55–65 %**
- **Infrastructure 24/7 : ~80–84 %**
- **Déploiement serveur : ~25 %**
- **Objectif "Alladin autonome OBSERVE/PAPER sur serveur" : ~89 %**
- **Objectif "LIVE suffisamment prouvé pour être envisagé" : ~35 %**

Le principal risque n'est plus de manquer de fonctionnalités. Le principal risque est désormais de **confondre fonctionnalité implémentée avec fonctionnalité validée en conditions longues et réelles**.

---

## 11. Règle de mise à jour de ce document

À chaque jalon significatif :

1. mettre à jour le HEAD de référence ;
2. mettre à jour le nombre de tests ;
3. ne monter un pourcentage que si une capacité a été codée **et/ou validée** ;
4. distinguer `IMPLEMENTED`, `TESTED`, `VALIDATED` et `DEPLOYED` ;
5. ne jamais marquer LIVE comme prêt sur la seule base de tests unitaires.

Ce fichier sert de tableau de bord humain. Pour les détails d'architecture et les décisions, consulter :

- `docs/HANDOFF.md`
- `docs/IMPLEMENTATION_PLAN.md`
- `docs/DECISIONS/`
- `docs/SNN/`
