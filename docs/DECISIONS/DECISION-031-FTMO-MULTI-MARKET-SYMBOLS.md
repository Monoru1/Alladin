# DECISION-031 — Univers multi-marchés FTMO et sélection de symboles

- Date : 2026-10-08
- Statut : ADOPTED (architecture et programme de validation ; rentabilité EXPERIMENTAL)
- Contexte : Alladin doit explorer au-delà du Forex les indices, métaux et autres CFD proposés par le broker, pour évaluer puis éventuellement réussir des challenges FTMO.

## Décision
1. Conserver l'univers Forex existant et ajouter progressivement les candidats US100/Nasdaq, US500/S&P 500, US30/Dow, XAUUSD/or, XAGUSD/argent, puis pétrole et autres symboles effectivement accessibles. Première cohorte de recherche : US100, XAUUSD, US500, EURUSD, GBPUSD, USDJPY.
2. Découvrir les noms exacts, spécifications, horaires, tailles de contrat, tick value, spread, marge et restrictions depuis le broker/compte actif : ne jamais présumer que les noms FTMO et MT5 sont identiques.
3. Séparer Market Scanner, Opportunity Ranking, calendrier macro, gestion des corrélations et Portfolio Risk Engine. Un signal sur plusieurs marchés corrélés ne vaut pas plusieurs risques indépendants.
4. Classer les opportunités nettes de coûts, qualité d'exécution, liquidité, régime, exposition et risque. NO_TRADE reste valide.
5. Ajouter une simulation de challenges multi-phases, avec règles configurables et versionnées selon programme/compte/date : objectifs, pertes quotidiennes/maximales, jours minimum, restrictions d'annonces et overnight/week-end si applicables. Ne pas figer des règles commerciales supposées universelles.
6. Progression : backtest causal OOS et stress tests -> PAPER -> MT5 DEMO -> validations simulées répétées -> décision humaine explicite avant toute évaluation payante ou activation d'un environnement à enjeu financier. Aucune promotion LIVE automatique.
7. Mesurer probabilité de validation complète, probabilité de ruine/violation, temps/trades nécessaires, drawdown, profit factor net, frais, slippage et robustesse par marché. Ne jamais promettre un nombre de trades ou un taux de réussite sans preuves.
8. Garder Jafar et SNN-X parallèles et isolés, sans casser le pipeline Alladin existant.

## Raisonnement
Un univers plus large donne davantage de candidats mais augmente la corrélation, le risque d'overfitting et la complexité d'exécution. La priorité est la probabilité de validation ET de conservation du compte, puis les récompenses réellement encaissées, pas le volume de transactions ni la taille nominale allouée.

## Invariants
RiskEngine déterministe, fail-closed, kill switch, journal/replay, isolation des modes, aucune exécution live sans autorisation explicite. Aucun changement de stratégie pour contourner les règles FTMO.

## Questions ouvertes
Symboles et règles exacts du compte cible ; données historiques fiables et calendrier économique ; qualité des fills ; performances OOS ; critères quantitatifs de promotion ; plafond d'allocation et conditions de récompense en vigueur.

## Conditions de révision
Réviser après résultats comparatifs OOS multi-régimes, changements de conditions broker/FTMO ou preuves d'un risque supérieur au bénéfice.

## Documents et code concernés
docs/HANDOFF.md ; docs/DECISIONS/README.md ; univers broker ; Strategy Lab ; RiskEngine ; ChallengeWatchdog ; Market Scanner et calendrier (cibles à auditer avant implémentation).
