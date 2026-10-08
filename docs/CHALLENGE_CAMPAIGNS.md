# Campagnes reproductibles de Challenges simulés

```bash
python scripts/report_challenge_campaign.py --output docs/reports/challenge_campaign_fixture.json
python -m pytest -o addopts='' -q tests/test_challenge_factory.py
```

Le script rejoue exactement les entrées versionnées de `tests/fixtures/policy/challenge_campaign.json` : deux profils fictifs, deux allocations nominales (25 000 et 100 000 USD simulés), quatre trajectoires, soit seize résultats. Les profils ne sont pas des contrats officiels ; les objectifs, limites et frais sont des hypothèses de fixtures. Chaque comparaison utilise les mêmes trajectoires, sans génération aléatoire ni stratégie prétendument rentable.

`challenge/factory.py` compose le PolicyGate d'entrée et le ChallengeWatchdog existant. Il utilise une seule position fictive par épisode, refermée avant l'épisode suivant. Le PnL brut, le coût et le creux d'equity en pourcentage de la base de phase sont des **entrées exogènes**, pas des performances calculées à partir d'un marché. Le reset journalier est évalué avant la perte ; un creux éliminatoire arrête le chemin, même si une entrée ultérieure annoncerait un gain. La reprise sérialisée conserve le watchdog et les changements de phase. Panne de calendrier et annonce restreinte empêchent l'entrée, donc son PnL n'est pas ajouté.

Les sorties incluent états, cas inachevés, échecs/raisons, drawdown observé aux seuls points fournis, coûts simulés des épisodes refermés, frais et coûts opérationnels hypothétiques par campagne. Si un creux fatal interrompt un épisode, les coûts finaux restent incomplets. Une récompense hypothétique exige un montant explicite fourni par l'appelant ; elle reste null dans les fixtures publiées. Cash réel et probabilité réelle sont null : le simulateur ne les observe pas.

Le hash SHA-256 couvre tous les inputs canoniques ; un second hash identifie le fichier de fixtures. Régénérer deux fois donne le même JSON. La fraction de validation est une proportion des quatre scénarios choisis à poids égaux ; elle n'est ni un modèle de probabilité, ni un résultat OOS, ni une estimation de rendement réel. Les chemins inachevés restent RUNNING, jamais assimilés à des échecs.

Limites opérationnelles explicites : règles statiques du watchdog et quatre modes de drawdown explicitement configurés en USD ; les autres contraintes de compte restent rejetées plutôt qu'ignorées. Overnight, limites multi-comptes et portefeuilles doivent être raccordés à un replay runtime distinct. Aucun sizing/RiskEngine, fill broker/intrabar, stratégie active, compte financier, achat, allocation réellement possédée ou promotion DEMO/LIVE n'est impliqué. Le RiskEngine opérationnel n'est pas modifié.

## Campagne trailing (lot 8)

```bash
python scripts/report_challenge_campaign.py --fixture tests/fixtures/policy/challenge_trailing_campaign.json --output docs/reports/challenge_trailing_campaign_fixture.json
```

32 replays : quatre formules de drawdown × deux allocations nominales synthétiques × quatre chemins. Les paramètres sont des hypothèses, pas des clauses officielles. `peak_equity_pct` est un point d'observation explicitement fourni avant le creux ; son absence ne fabrique aucun plus-haut intrabar. `end_of_day` est un signal fourni, jamais déduit d'un jour UTC. `reset_drawdown_on_phase` vaut false par défaut et doit être explicitement activé pour changer l'ancrage à une transition de phase.

Les floors et états sérialisables sont conservés dans le résultat. Un seuil atteint donne POLICY_FAILED, arrête les épisodes suivants, ne compte pas comme chemin inachevé et n'accorde pas de récompense hypothétique. Le watchdog historique n'est pas modifié ; ses violations restent visibles. Une equity négative observée est enregistrée comme telle ; elle ne crée pas un AccountPolicyState non négatif fictif, et la raison NEGATIVE_EQUITY explique l'état manquant.

Le changement de phase du fournisseur archivé peut être injecté par un sélecteur explicite ; sans dossier pour la nouvelle phase, le checkpoint refuse/revoit la proposition et ne réutilise pas le dossier précédent. Aucun changement automatique de programme financier ou de mode d'exécution.

Les inputs et ensembles sont canoniques. Régénérer dans des processus de PYTHONHASHSEED différents donne des fichiers identiques. Les probabilités et performances réelles restent inconnues, et les allocations sont toujours simulées. Aucune enveloppe de risque ou stratégie active n'est modifiée. Les campagnes exigent une validation de phase à plat ; les politiques autorisant un passage non flat restent hors de ce modèle.
