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
