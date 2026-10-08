# Campagnes reproductibles de Challenges simulés

```bash
python scripts/report_challenge_campaign.py --output docs/reports/challenge_campaign_fixture.json
python -m pytest -o addopts='' -q tests/test_challenge_factory.py
```

Le script rejoue exactement les entrées versionnées de `tests/fixtures/policy/challenge_campaign.json` : deux profils fictifs, deux allocations nominales (25 000 et 100 000 USD simulés), quatre trajectoires, soit seize résultats. Les profils ne sont pas des contrats officiels ; les objectifs, limites et frais sont des hypothèses de fixtures. Chaque comparaison utilise les mêmes trajectoires, sans génération aléatoire ni stratégie prétendument rentable.

`challenge/factory.py` compose le PolicyGate d'entrée et le ChallengeWatchdog existant. Il utilise une seule position fictive par épisode, refermée avant l'épisode suivant. Le PnL brut, le coût et le creux d'equity en pourcentage de la base de phase sont des **entrées exogènes**, pas des performances calculées à partir d'un marché. Le reset journalier est évalué avant la perte ; un creux éliminatoire arrête le chemin, même si une entrée ultérieure annoncerait un gain. La reprise sérialisée conserve le watchdog et les changements de phase. Panne de calendrier et annonce restreinte empêchent l'entrée, donc son PnL n'est pas ajouté.

Les sorties incluent états, cas inachevés, échecs/raisons, drawdown observé aux seuls points fournis, coûts simulés des épisodes refermés, frais et coûts opérationnels hypothétiques par campagne. Si un creux fatal interrompt un épisode, les coûts finaux restent incomplets. Une récompense hypothétique exige un montant explicite fourni par l'appelant ; elle reste null dans les fixtures publiées. Cash réel et probabilité réelle sont null : le simulateur ne les observe pas.

Le hash SHA-256 couvre tous les inputs canoniques ; un second hash identifie le fichier de fixtures. Régénérer deux fois donne le même JSON. La fraction de validation est une proportion des quatre scénarios choisis à poids égaux ; elle n'est ni un modèle de probabilité, ni un résultat OOS, ni une estimation de rendement réel. Les chemins inachevés restent RUNNING, jamais assimilés à des échecs.

Limites opérationnelles explicites : règles de drawdown statique du watchdog uniquement ; les `FirmProfile.constraints` sont rejetées plutôt qu'ignorées. Trailing, overnight, limites multi-comptes et portefeuilles doivent être raccordés à un replay runtime distinct. Aucun sizing/RiskEngine, fill broker/intrabar, stratégie active, compte financier, achat, allocation réellement possédée ou promotion DEMO/LIVE n'est impliqué. Le RiskEngine opérationnel n'est pas modifié.
