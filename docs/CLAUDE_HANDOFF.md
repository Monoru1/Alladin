## Jalon Pepperstone multi-marchés — 2026-10-08 (validation utilisateur)

Sur Windows, l'utilisateur a exécuté la suite complète avec MT5 connecté à MetaQuotes-Demo : **1546 passed, 0 failed, 1 warning en 151.19 s**, dont **3 tests mt5_integration réussis** en lecture seule. Il s'agit de la base `a8c0a50`, avant les commits multi-marchés ; aucune nouvelle suite n'a encore été exécutée sur les commits ultérieurs.

Deuxième compte MT5 DEMO créé et connecté : `PepperstoneUK-Demo`, EUR, 50 000 EUR virtuels, levier 1:30 ; accès mobile MT5 confirmé par l'utilisateur. Ne pas enregistrer les identifiants. Découverte Python : **1725 symboles**, **94 Forex**, **91 Forex en trade_mode FULL** ; NAS100, US500, US30, XAUUSD, XAGUSD en FULL. Les cinq instruments ont cependant renvoyé **bid=ask=0** après sélection : aucune cotation exploitable, donc aucun signal ni exécution autorisés sur cette preuve.

Décision 031 maintenue. `docs/PEPPERSTONE_MULTI_MARKET_DISCOVERY.md` consigne l'inventaire. `config/universes/pepperstone_multimarket_research.yaml` est un **profil de recherche opt-in**, conservant toutes les catégories Forex et métaux de LAB et ajoutant explicitement les trois CFD indices cash sans ouvrir toute la catégorie OTHER. Aucun changement du profil par défaut `ftmo_2step_demo`, du runtime, des stratégies ou des permissions d'ordre. Les forwards/perpetuals ne sont pas inclus. Le profil challenge par défaut porte 100 000 EUR fictifs, différents du compte Pepperstone 50 000 EUR ; ne pas les confondre.

**À faire** : tests ciblés de chargement et découverte de cet univers ; valider classification INDEX dédiée fondée sur métadonnées broker ; contrôle tick/horaires/frais/contrat/risque et isolation des comptes ; ajouter une configuration DEMO Pepperstone spécifique avant toute recette. Pas de promesse de disponibilité 24/7, de performance, de conformité FTMO ou de trading autorisé. Préserver RiskEngine/PolicyGate/Jafar/SNN-X.

---

# ALLADIN — Claude Handoff

## Lot 8 — 2026-10-08 : campagnes trailing et transitions de phase

Base `8354460`. Challenge Factory compose le watchdog existant et les floors static/trailing_balance/trailing_equity/trailing_eod explicitement injectés en USD. Points de plus-haut d'equity avant creux, EOD explicite, reset d'ancrage de phase optionnel (false par défaut), état sérialisé/restart et observations de floors. POLICY_FAILED est terminal, non assimilé à un cas inachevé et sans récompense ; un creux négatif reste négatif, avec état non représentable signalé plutôt que fabriqué. Les autres contraintes (sessions/overnight/agrégats) et validation non flat restent rejetées. Aucun changement du watchdog opérationnel ou du RiskEngine.

32 replays supplémentaires versionnés (4 modes × 2 allocations nominales × 4 chemins), en plus des 16 replays initiaux. Script accepte --fixture ; inputs et hashes sont canoniques, JSON identique entre processus de PYTHONHASHSEED différents. Les profils/trajectoires restent SYNTHÉTIQUES : aucune probabilité réelle, performance OOS, récompense effectivement reçue ou capital détenu inféré. Rapports et docs CHALLENGE_CAMPAIGNS.md mis à jour.

ArchivedPolicyProvider accepte un sélecteur de phase explicitement injecté. Changer de phase exige un dossier disponible pour la nouvelle phase ; un dossier manquant bloque/revoit la proposition, sans fallback à l'ancienne phase. Aucun statut de compte financier découvert ou mode de trading promu automatiquement.

Validation : **127 tests ciblés réussis** ; suite finale **1501 passed, 3 skipped MT5, 0 failed, 1 warning Starlette**, 228.69 s. Ruff src/tests/deux scripts **PASS** ; mypy **PASS, 117 fichiers** ; diff --check **PASS**. Trois rapports régénérés octet par octet à l’identique, campagne trailing testée entre processus. Versions/outils et manifeste du code testé : `docs/reports/policy_software_current.json`.

Reprise Claude/Codex : lire les lots 7/8 et POLICY_ARCHIVE.md/CHALLENGE_CAMPAIGNS.md. Prochain chantier autonome : réservation atomique d'exposition et reconciliation PAPER, collecteurs complets/archives de couverture et campagnes de portefeuille/overnight. Dossiers toujours SIMULATION_ONLY, checkpoint toujours opt-in OBSERVE/PAPER. Contrats réels, sources complètes réellement vérifiées, MT5 DEMO, fills/reconciliation broker/endurance et validation de performance restent non qualifiés. Aucun compte financier, secret, achat ni trading réel ; Brain actif/Jafar/SNN-X préservés.

---


## Lot 7 — 2026-10-08 : dossiers, archive et composite causal

Base `b994334`. Dossiers persistants par AccountBinding/programme/phase, preuve documentaire et revue référencées, statut DRAFT/SIMULATION_ONLY, modes OBSERVE/PAPER uniquement. SQLite distinct du journal : documents bruts + batches liés à leur hash/réception, dossiers et révocations append-only/idempotents, intégrité des contenus, isolation et restart. Disponibilité inclut l'archivage local ; aucun fallback vers un ancien dossier/refresh permissif après expiration/révocation. Aucun compte/firme réellement admis.

Composite calendrier : sources exigées par symbole et horizons, preuve de batch, identifiants qualifiés par source, gaps explicites. Aucun assemblage de sources partielles n'est promu complet ; BLS/BEA restent partiels. ArchivedPolicyProvider assemble passivement les snapshots injectés, vérifie mode/binding et alimente le checkpoint existant sans réseau ni ordre. Journal enrichi des IDs/hashes dossier/batches/gaps. Hashes canoniques stables entre processus/fuseaux. Voir `docs/POLICY_ARCHIVE.md`.

Validation : **49 nouveaux tests ciblés réussis** ; suite **1484 passed, 3 skipped MT5, 0 failed, 1 warning Starlette**, 220.55 s. Ruff global src/tests/deux scripts **PASS** ; mypy **PASS, 117 fichiers** ; diff --check **PASS**. Environnement isolé Python 3.12.14 recréé, versions et hashes dans `docs/reports/policy_software_current.json`. Intégration de gestion PAPER via MockBroker sans envoi broker testée. Aucune activation globale, migration du journal existant, modification du Brain/RiskEngine/Jafar/SNN-X ou accès financier.

Limites : DOCUMENT_REFERENCE n'authentifie pas un contrat ; hashes locaux ne résistent pas à une réécriture malveillante totale de la base. Complétude des sources externes et mappings encore à vérifier. Collecteurs/réservations atomiques multi-comptes et recette MT5 DEMO/endurance non raccordés. Prochain lot : étendre la campagne aux floors trailing avec état causal et points d'observation explicites, puis réservations/reconciliation PAPER. Les anciens blocs restent historiques.

---


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


## Lot autonome 3 — 2026-10-08 : rapports et validation finale

Livré : `policy_quality.py`, `scripts/report_policy_quality.py`, `docs/POLICY_VALIDATION.md`, rapports versionnés dans `docs/reports/`. Rapport déterministe : **12 sondes labellisées, 0 divergence**, hash des fixtures et preuve profil/calendrier par décision. Les métriques économiques/opérationnelles absentes restent null ; PASS ne donne ni readiness ni autorisation d'exécution. Les événements simultanés donnent tous les IDs déclencheurs triés. Données numériques coercées et heures locales DST inexistantes rejetées.

Résultats exacts sur le code final :
- `python -m pytest -o addopts='' -q tests/test_economic_calendar.py tests/test_policy*.py tests/test_propfirm_policy_foundations.py` : **382 passed**.
- `python -m pytest -o addopts='' -q --junitxml=/tmp/alladin-final-tests.xml` : **1319 passed, 3 skipped, 1 warning**, 116.17 s. Les 3 skips sont uniquement MT5 sans terminal DEMO. Warning de dépréciation Starlette/httpx ; aucun échec.
- `python -m ruff check src/alladin tests scripts/report_policy_quality.py` : **PASS global**. Les 15 erreurs préexistantes sont corrigées uniquement par nettoyage/tri d'imports dans deux fichiers de tests Jafar.
- `python -m mypy src/alladin scripts/report_policy_quality.py` : **PASS, 107 fichiers**.
- `git diff --check` : PASS ; régénération du rapport fixture comparée octet par octet : identique.
- Stress : simulateur existant BUY/SELL gap adverse + spread/commission/slippage ; état FAILED du watchdog restauré pendant l'heure DST répétée. Ces tests ne constituent pas un raccordement PolicyGate au backtest/runtime.

La suite antérieure au dernier durcissement avait passé 1314 tests + 3 skips ; la relance finale ci-dessus inclut les cinq cas supplémentaires. Environnement Python et versions des outils, hash du code testé et skips sont conservés dans `docs/reports/policy_software_validation.json`.

**Limites et suite autorisée :** modules toujours isolés ; revue des sorties protectrices/SL/TP, fournisseur fiable et licencié, contrats par compte réellement vérifiés, règles weekend/overnight/copie/trailing/multi-comptes, intégration OBSERVE/PAPER désactivée puis MT5 DEMO et endurance restent à réaliser. Aucun avantage OOS ou rendement démontré, aucune qualification 24/7. RiskEngine/modes/exécution, fonctionnalités Alladin/Jafar/SNN-X préservés, aucun LIVE, compte financier ou migration.
Les notes plus anciennes de création indiquant « tests non exécutés » sont historiques ; les résultats de ce lot sont l'état logiciel actuel.

---


## Lot autonome 2 — 2026-10-08 : calendrier causal et conformité simulée

`economic_calendar.py` : ingestion JSON offline validée (schéma/version, provenance/licence explicites, heure de disponibilité ET collecte, valeurs finies, révisions monotones), snapshots complets et replay selon réception. Dernier refresh périmé conservé : aucun fallback permissif. Horodatages normalisés UTC pour éviter les comparaisons ambiguës pendant le DST. Aucune connexion fournisseur.
Fixtures `tests/fixtures/policy/firm_profiles.json` : **SYNTHÉTIQUES UNIQUEMENT**, six variantes phase/type/automatisation/news/limite. Aucun contrat réel vérifié ni support d'une firme déclaré. Un profil portant `restrict_news` ne peut être contredit par le contexte appelant.

Validation : `python -m pytest -o addopts='' -q tests/test_economic_calendar.py tests/test_policy*.py tests/test_propfirm_policy_foundations.py` : **361 passed** ; Ruff fichiers du lot : PASS ; mypy challenge : PASS (10 fichiers) ; diff --check : PASS. Couvre limites ±2 min et précaution, pannes de calendrier, profils périmés/futurs, isolation de contextes, sérialisation/restart, révisions retardées et DST. Tests unitaires/simulation seulement ; pas de fills ni recette broker dans ce lot.

Limites : calendrier complet déclaré par le fournisseur mais couverture non certifiée, association événement/symbole à fournir, pas de validation indépendante des sources/licences ; weekends, overnight, copy trading, trailing drawdown et exposition multi-comptes non modélisés par PolicyGate. Sorties protectrices/SL/TP broker toujours à revoir ; aucun raccordement au runtime, aucun LIVE ni qualification 24/7.

---


## Lot autonome 1 — 2026-10-08 : validation PolicyGate

Base reprise : `a5073c7` sur main. Tests initiaux : 14 passed. Après durcissement :
`python -m pytest -o addopts='' -q tests/test_policy_gate.py tests/test_propfirm_policy_foundations.py tests/test_policy_gate_validation.py` : **51 passed**.
Ruff modules challenge + ces trois fichiers : PASS ; mypy challenge : PASS (9 fichiers), mypy global : PASS (104 fichiers) ; diff --check : PASS.
Ruff global : 15 erreurs préexistantes dans les tests Jafar execution/testnet, non attribuées au lot.

Actions inconnues bloquées ; horloge/contexte invalides et automatisation interdite escaladent la gestion des positions en REVIEW (OPEN bloqué). Les montants non finis, symboles ambigus et révisions dupliquées dans un snapshot sont rejetés. HOLD reste sans transaction. Aucun branchement à ExecutionService ni changement des modes/risques. La suite globale est en cours ; aucun PASS global déclaré à ce stade.
Suite : calendrier causal et fixtures synthétiques ; revue des sorties protectrices, contrats réels, source licenciée, intégration OBSERVE/PAPER, MT5 DEMO et endurance restent nécessaires.

---


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
