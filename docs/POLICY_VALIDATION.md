# Validation offline du PolicyGate

Les modules de politique restent isolés de `ExecutionService`. Aucun ALLOW ne constitue une autorisation de trading : RiskEngine, modes, broker, ownership et watchdog restent des contrôles indépendants. REVIEW demande une procédure de protection et de conformité ; il ne désactive ni stop natif ni kill switch.

## Reproduire les preuves

Depuis la racine, avec Python 3.12 et les dépendances de développement :

```bash
python -m pytest -o addopts='' -q tests/test_economic_calendar.py tests/test_policy*.py tests/test_propfirm_policy_foundations.py
python -m ruff check src/alladin tests scripts/report_policy_quality.py
python -m mypy src/alladin scripts/report_policy_quality.py
python scripts/report_policy_quality.py --output docs/reports/policy_quality_fixture.json
python -m pytest -o addopts='' -q --junitxml=acceptance_reports/policy-software.xml
```

Le rapport JSON est déterministe et référence le SHA-256 du fichier de fixtures. Il comporte 12 sondes labellisées, les verdicts/raisons, la version et la source du profil, la fraîcheur du calendrier et les identifiants d'événements. Les tests couvrent une matrice plus large ; les 12 sondes ne résument pas toute la suite. PASS signifie uniquement que les attentes de ces sondes sont satisfaites. Une suite vide ou non labellisée est UNASSESSED, une divergence FAIL, et des identifiants dupliqués sont rejetés.

Les données absentes (fills confirmés, PnL, drawdown, slippage, disponibilité, récupération) restent null. `execution_authorized`, `runtime_integrated` et `unattended_qualified` restent false. Le capital nominal simulé est séparé du cash reçu. Le script sort avec code 2 si les attentes ne passent pas. Aucune base de données, credential, réseau ou commande broker n'est utilisée.

## Calendrier et replay

`CalendarBatch.model_validate_json()` est le point d'ingestion offline. Chaque refresh est **complet**, avec source, URL, licence déclarée, date d'observation, expiration et révisions. Les collections doivent précéder la réception du refresh. Les valeurs réalisées ne peuvent précéder la publication prévue. Des champs inconnus, timestamps naïfs, identifiants ambigus, valeurs non finies ou numériques coercées, doublons, révisions non monotones et heures locales inexistantes sont rejetés.

Les dates sont normalisées UTC. Le fuseau original reste une métadonnée valide IANA. Les heures répétées DST sont distinguées par leur instant UTC ; les offsets explicites sont nécessaires pour les fichiers JSON. Aucune heure locale naïve n'est interprétée implicitement.

`replay_calendar()` choisit le dernier refresh reçu à la date demandée. Il ignore les refreshes futurs, rejette les timestamps de réception dupliqués et conserve un refresh périmé pour que le gate bloque : aucun retour opportuniste à un ancien calendrier encore valide. Chaque événement n'a qu'une révision active par snapshot. Les archives sérialisées gardent forecast/previous/actual sans utiliser des données futures dans le verdict. Les identifiants de tous les événements déclencheurs sont triés pour un audit complet et indépendant de l'ordre d'ingestion.

Un refresh vide représente une déclaration explicite du fournisseur, pas une preuve de couverture. L'adapter ne certifie ni authenticité, ni exhaustivité, ni SLA/licence. Un futur provider doit fournir cette preuve et une archive fiable ; une erreur d'ingestion doit être traitée comme indisponibilité, jamais remplacée par un calendrier vide.

## Fixtures et simulation

`tests/fixtures/policy/firm_profiles.json` contient six variantes **SYNTHETIC-ONLY**, datées et expirables : évaluation, funded standard, funded swing, automatisation interdite, news inconnue et limite de positions nulle. Elles ne constituent ni des contrats FTMO ni une admission d'autres firmes. Leur structure vérifie la séparation phase/type/compte et les divergences de contraintes sans présumer un accès financier.

Les simulations couvrent OPEN/CLOSE/PARTIAL_CLOSE/MODIFY_STOP/MODIFY_TARGET/HOLD, les bornes et secondes extérieures des fenêtres, calendrier absent/périmé, profils futurs/expirés, restrictions contradictoires, indépendance des contextes et restart. Des tests de stress réutilisent `BacktestRunner` (gaps adverses BUY/SELL, spread, commission et slippage) et `ChallengeWatchdog` (perte flottante après restore pendant le DST). Ces tests ne raccordent pas PolicyGate au simulateur ni au runtime.

## Limites restantes

- Revue humaine des sorties protectrices et des déclenchements SL/TP broker avant intégration.
- Fournisseur économique fiable/licencié, couverture vérifiable, archivage et associations aux symboles effectivement exposés.
- Contrats officiels par compte et revalidation périodique : fixtures synthétiques exclues de toute admission réelle.
- Week-end/overnight, copy trading, trailing drawdown et exposition/corrélation multi-comptes non couverts par PolicyGate.
- Intégration OBSERVE/PAPER à exécution désactivée, puis MT5 DEMO, panne/reconciliation de bout en bout et soak prolongé.
- Ces preuves logicielles n'établissent ni avantage OOS, ni rendement, ni disponibilité 24/7.

Aucune migration de données et aucun changement des modes, des règles RiskEngine, de Jafar ou de SNN-X. Le nettoyage Ruff dans deux fichiers de tests Jafar retire uniquement des imports inutilisés et trie les imports.

## Contraintes de compte (lot 4)

`FirmProfile.constraints` est opt-in et décrit le compte/la devise. `MarketSchedule` exige un scope de symboles et des coupures explicites ; le code ne déduit pas les horaires d'un nom d'instrument ou d'un vendredi. `AccountPolicyState` maintient les high water marks et `advance()` refuse un retour dans le temps ; le mode EOD exige un signal explicite de fin de journée. Les floors sont calculés en devise de compte avec distance basée sur la balance initiale, cap de floor optionnel. Ce modèle ne présume pas la formule d'une firme réelle.

`ExposureSnapshot` exige le scope exact des comptes pilotés pour les limites agrégées, avec risques déjà convertis dans une devise commune et groupes explicites. Il n'est pas un collecteur de corrélations ni une preuve que tous les comptes externes ont été découverts. La concurrence entre deux futures soumissions nécessitera une réservation atomique hors de cette évaluation pure.

Protection et restriction d'annonce sont deux faits distincts : une simple précaution ne retarde pas une sortie protectrice conforme ; un conflit contractuel ou une incertitude exige REVIEW et une alerte. Aucun retrait d'une protection native n'est prévu. En cas de deadline de détention et de news simultanées, une politique peut devenir impossible à satisfaire : pas de transaction autorisée par ce seul gate.

Références officielles relues le 08/10/2026, sans admission d'un compte réel : [FTMO annonces](https://ftmo.com/en/faq/can-i-trade-news/) et [FTMO détention](https://ftmo.com/faq/do-i-have-to-close-my-positions-overnight-or-before-the-weekend/). Les clauses varient par programme/phase/type, et les horaires doivent être fournis par le broker. Les fixtures restent SYNTHÉTIQUES.
