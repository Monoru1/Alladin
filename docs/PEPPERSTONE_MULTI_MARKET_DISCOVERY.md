# PepperstoneUK-Demo — inventaire multi-marchés et garde-fous (2026-10-08)

## Provenance et état
Relevés manuels de l'utilisateur via l'API Python MetaTrader5 sur PepperstoneUK-Demo (compte DEMO, devise EUR, capital virtuel initial 50 000 EUR). Les observations sont un instantané, pas une certification de disponibilité permanente.

- Catalogue : 1 725 symboles ; groupe Retail.
- Chemins contenant Forex : 94, dont 91 avec trade_mode=4 (FULL).
- Exemples Forex : EURUSD, GBPUSD, USDJPY, GBPJPY, EURJPY, AUDUSD, USDCAD ; exotiques dont EURTRY, USDMXN, USDZAR.
- Indices cash : NAS100, US500, US30 : trade_mode=4, contract_size=1, volume_min=0.1, volume_step=0.1, trade_tick_size=0.1, currency_profit=USD.
- Métaux : XAUUSD (contract_size=100, min/step=0.01, tick_size=0.01), XAGUSD (contract_size=5000, min/step=0.01, tick_size=0.001) : trade_mode=4.
- Contrats distincts : NAS100-F, US500-F, US30-F, XAUUSD-F, XAGUSD-F ; NAS100-PERP, US500-PERP, GOLD-PERP, SILVER-PERP. Ne pas assimiler à leurs équivalents cash.
- Après symbol_select(True), les cinq instruments NAS100, US500, US30, XAUUSD, XAGUSD ont renvoyé bid=ask=0.0 et spread=0. Aucun prix exploitable n'est établi. Le scanner doit rejeter ces ticks ; ne jamais interpréter spread=0 comme coût nul.

## État du code et limites
- config/universes/lab.yaml autorise déjà FOREX_MAJOR, FOREX_MINOR, FOREX_JPY, FOREX_EXOTIC, METAL : conserver la découverte dynamique Forex + métaux.
- src/alladin/market/universe.py classe les instruments non Forex et non métaux en OTHER. Une inclusion explicite d'un symbole contourne uniquement le filtre de catégorie, PAS les contrôles de négociabilité et de spécifications ; ne pas s'en servir comme substitut à une vraie catégorie INDEX.
- src/alladin/market/scanner.py rejette les ticks absents ou bid<=0 ou ask<=bid, et contrôle fraîcheur, spread/ATR et risque minimal.
- Le profil ftmo_2step_demo.yaml utilise un initial_balance de 100 000, alors que Pepperstone DEMO a 50 000 : ne pas le réutiliser tel quel pour un challenge ou un run existant.
- Validation utilisateur du commit local antérieur : 1546 tests passed, 1 warning, dont trois tests MT5 lecture seule. Cette validation ne certifie pas les modifications futures.

## Prochaine implémentation (OBSERVE/PAPER seulement, aucune activation DEMO)
1. Ajouter une catégorie INDEX explicite avec classification fondée sur les métadonnées broker (chemin Retail\\... et/ou identifiants exacts vérifiés), en refusant de classer actions, ETF, forwards ou perpetuals comme indices cash.
2. Ajouter un univers de recherche opt-in Forex + METAL + INDEX sans réduire les 91 paires Forex négociables découvertes ; garder exclusions et limites configurables.
3. Ajouter des tests unitaires pour classification indices, suffixes/forwards/perps, Forex exotiques, modes non négociables, bid/ask nuls, historique absent, taille du tick, conversion de devise de profit, sizing et corrélations.
4. Vérifier frais, marge, sessions, valeur de tick et fraîcheur des cours sur Pepperstone DEMO avant d'autoriser PAPER ; aucun ordre envoyé pendant la découverte.
5. Préserver RiskEngine déterministe, PolicyGate fail-closed, SL/TP, isolation des comptes, Jafar et SNN-X. Ne pas confondre un compte DEMO broker avec un challenge FTMO contractuellement qualifié.

Aucun identifiant de compte, mot de passe ou jeton ne doit être enregistré dans ce document.

## Validation du jalon INDEX (Windows utilisateur, 2026-10-08)
- Commit code `6e4535e` : 10 tests ciblés réussis en 0.05 s ; Ruff PASS ; mypy PASS (1 fichier). Les 1546 tests précédents ont été exécutés **avant** ce commit, ne pas les présenter comme une suite complète post-INDEX.
- Chemins broker vérifiés : `Retail\\Indices\\Majors\\NAS100`, `Retail\\Indices\\Majors\\US500`, `Retail\\Indices\\Majors\\US30` ; `trade_calc_mode=2` pour les trois.
- La catégorie `INDEX` native et le profil `pepperstone_multimarket_research` sont en place ; la découverte effective et la fraîcheur des ticks restent à valider en OBSERVE, sans ordre.

## Découverte réelle Alladin validée par l'utilisateur — 2026-10-08
- Commande en lecture seule : `MT5Broker` + `MarketUniverse` + `UniverseRules` chargé depuis `config/universes/pepperstone_multimarket_research.yaml`.
- Serveur `PepperstoneUK-Demo`, type `DEMO`.
- **1725 découverts, 110 membres admissibles** : `FOREX_EXOTIC=62`, `FOREX_JPY=6`, `FOREX_MAJOR=7`, `FOREX_MINOR=15`, `INDEX=3`, `METAL=17`.
- `NAS100`, `US500`, `US30` classés `INDEX` ; `XAUUSD`, `XAGUSD` classés `METAL`.
- **Attention :** le diagnostic broker initial trouvait 91 paires Forex avec trade_mode=4, mais la découverte en admet 90. Examiner le motif d'exclusion de la paire manquante (catégorie ou spécifications) ; ne pas la forcer.
- Ce résultat prouve la découverte réelle du catalogue, **pas** la disponibilité des ticks/historiques, la réussite d'un scan complet, la rentabilité ou l'exécution DEMO. Aucune commande d'ordre n'a été lancée.
- Prochaine recette : analyser les exclusions Forex, vérifier les ticks non nuls et récents, puis lancer un cycle `OBSERVE` borné ; mesurer la latence sur 110 instruments et journaliser les rejets.

## Première cotation multi-marchés reçue (2026-10-08)
Diagnostic MT5 Python en lecture seule sur PepperstoneUK-Demo, après symbol_select, six instruments :
| Symbole | Bid | Ask | H1 bars | Âge brut du tick (s) |
|---|---:|---:|---:|---:|
| NAS100 | 31063.6 | 31064.6 | 100 | -10798 |
| US500 | 7787.7 | 7788.1 | 100 | -10798 |
| US30 | 51173.8 | 51175.8 | 100 | -10798 |
| XAUUSD | 4131.18 | 4131.29 | 100 | -10799 |
| XAGUSD | 59.241 | 59.269 | 100 | -10799 |
| EURUSD | 1.12026 | 1.12027 | 100 | -10799 |

Prix non nuls et 100 barres H1 reçues pour chacun. Âge brut négatif d'environ 3 heures : probable décalage du serveur, **non encore prouvé**. Le diagnostic utilisait `datetime.now(UTC) - tick.time` sans compensation. Vérifier la logique de `MT5Broker._detect_server_offset`, `offset_source`, et la fraîcheur après normalisation, sans désactiver les contrôles ; horodatages futurs doivent rester fail-closed si décalage non fiable. Aucun ordre exécuté ; aucune validation de rentabilité ou de fonctionnement continu. Le scanner multi-timeframe exige davantage que 100 barres H1.

## Horloge MT5 validée par l'utilisateur — 2026-10-08
- `MT5Broker` connecté à `PepperstoneUK-Demo` en DEMO ; `offset_source=auto`, `server_utc_offset_hours=3.0`.
- Âges normalisés observés : EURUSD 0.94 s, NAS100 0.94 s, XAUUSD 1.94 s.
- L'anomalie d'âge brut -3 h était donc expliquée pour ces trois symboles par le décalage du serveur. Cela ne prouve pas la fraîcheur de tous les 110 instruments, ni la disponibilité constante de données ou de fills.
- Prochaine étape : cycle scanner borné OBSERVE, mesurer nombre analysés/rejetés, temps d'exécution, couverture historique multi-timeframe ; aucune exécution d'ordre.

## Recette scanner bornée — 2026-10-08
- Script opt-in `scripts/accept_pepperstone_scanner.py` : appelle le MarketScanner existant sur 8 symboles maximum par défaut (EURUSD, GBPUSD, USDJPY, NAS100, US500, US30, XAUUSD, XAGUSD), quatre timeframes M15/H1/H4/D1, 300 barres demandées.
- Contrôle serveur PepperstoneUK-Demo, compte DEMO, offset_source=auto ; pas d'ExecutionService, d'ordre ou de promotion de mode.
- Sortie JSON : couverture, candidats, régimes, rejets, latence. `--symbols` permet un sous-ensemble de 1 à 12 ; `--output` enregistre le rapport localement.
- **Non encore exécuté par l'utilisateur ni testé sur son environnement** au moment du commit ; aucun résultat de scan, conformité, P&L ou qualité du feed n'est présumé.
- DECISION-021/031 : découverte distincte de l'éligibilité et de l'exécution ; DECISION-032/033 : calendrier et firm profile non automatiquement certifiés par ce scan ; DECISION-034 : aucune performance inférée ; DECISION-035 : qualité et durée mesurées, sans qualification unattended.
- Limitation connue du scanner existant : des ticks >10 min dans le futur sont notés comme suspects mais non rejetés. Corriger en fail-closed et tester avant toute promotion vers PAPER/DEMO ; le script exige déjà une horloge auto-vérifiée.

## Recettes utilisateur et durcissement scanner — 2026-10-08
- Recette 3 symboles : EURUSD/NAS100/XAUUSD, 3 analysés, 3 candidats, 0 rejet, 4.61 s, scores 0.7319/0.6421/0.5591, régime RANGE.
- Recette 8 symboles : 8 admissibles, 7 analysés, 7 candidats, 9.141 s ; EURUSD rejeté parce que bid=ask=1.12073. Rejet de données sain, pas une erreur du moteur. Tous les autres instruments ont fourni des candidats, sans garantie de rentabilité.
- Correctif scanner : ticks futurs >5 s, non finis, bid<=0, ask<=bid et ticks périmés rejetés avant historique/analyse ; tests déterministes ajoutés. Résultats tests post-correctif à exécuter, **aucun PASS inventé**.
- Rapport de recette enrichi : comptes candidats/rejets, régimes ; `execution=NOT_INVOKED`, `policy_and_portfolio_approval=NOT_EVALUATED`, scores non probabilistes. Les rapports précédents portent l'ancien champ `order_count=0` : ils ne constituent pas une preuve d'audit des ordres au niveau broker.
- À poursuivre selon décisions 021/031–035 : isoler la paire Forex absente de l'inventaire, qualité barres sur les quatre timeframes, risques de corrélation, frais/slippage, calendriers et conformité par compte, replay causal, supervision/restart, puis PAPER et DEMO seulement après validation. Jafar/SNN-X isolés ; aucune promotion automatique.

## Recette scanner 03 validée par l'utilisateur — 2026-10-08
- Windows PepperstoneUK-Demo, `offset_source=auto`, UTC+3 ; 8 demandés, 8 admissibles, 8 analysés, 8 candidats, **0 rejet**, 0.969 s ; 8 régimes RANGE.
- Candidats : XAGUSD 0.7674, EURUSD 0.7319, GBPUSD 0.6910, US30 0.6479, NAS100 0.6421, US500 0.6238, XAUUSD 0.5609, USDJPY 0.5447. Scores relatifs du scanner, **pas** des probabilités de profit ni autorisations d'ordres.
- `tests/test_scanner_tick_quality.py` + `tests/test_pepperstone_index_classification.py` : **21 passed** en 0.09 s. `mypy src/alladin/market/scanner.py` : PASS.
- Ruff : une seule erreur I001 (imports non triés dans scanner.py), corrigée dans le commit `1645f22` ; Ruff après correctif **non encore exécuté**. Ne pas présenter le lot comme globalement validé avant cette vérification.
- Aucun ordre ni PolicyGate/RiskEngine invoqué (`execution=NOT_INVOKED`, `policy_and_portfolio_approval=NOT_EVALUATED`). Cette recette n'évalue ni coûts nets, ni risque portefeuille, ni news, ni conformité prop firm, ni endurance.
- Suite : confirmer Ruff, lancer une recette progressive 12 symboles maximum, inspecter les rejets des Forex, instrumenter couverture temporelle/historique et latence ; ne pas confondre la forte proportion RANGE sur un instantané avec une loi de marché.
