# Recette PC — Alladin / Jafar

Depuis PowerShell dans le dépôt, terminal MT5 fermé pour la première sauvegarde :

```powershell
git status
git pull --ff-only origin main
.\scripts\Invoke-AlladinChecks.ps1
```

Si Git signale des changements locaux ou une divergence, les conserver et résoudre avant de continuer ; ne pas utiliser `reset --hard`. Le script exige l’environnement `.venv` existant et Python 3.12+. Si nécessaire, installer les dépendances avec `.\.venv\Scripts\python.exe -m pip install -e ".[dev]"`.

Le script sauvegarde les bases SQLite existantes avant toute initialisation applicative, vérifie les copies, puis lance Ruff, mypy et les tests logiciels. Les journaux, sauvegardes et `report.json` sont dans `acceptance_reports/<date>/`, exclus de Git. Un code de sortie non nul signifie échec ; ouvrir le journal concerné. `-BackupOnly` ne réalise que la sauvegarde. Les bases externes exigent leur propre sauvegarde et sont refusées par cette procédure.

## Terminal DEMO en lecture seule

Ouvrir MT5 connecté au compte DEMO attendu, puis :

```powershell
.\scripts\Invoke-AlladinChecks.ps1 -Mt5ReadOnly
```

Les trois tests supplémentaires lisent compte, symboles, ticks et barres. Aucun ordre n’est envoyé. Ils ne valident pas les ouvertures, modifications SL/TP, clôtures partielles ou fermetures réelles.

Pour observer trois cycles avec l’agent mock (aucun abonnement agent nécessaire), créer un run si aucun run compatible n’existe, puis utiliser son identifiant :

```powershell
.\.venv\Scripts\python.exe -m alladin runs new --broker mt5 --system-test
.\.venv\Scripts\python.exe -m alladin run --broker mt5 --agent mock --mode OBSERVE --cycles 3 --interval 1 --run SYSTEM-TEST-001
.\.venv\Scripts\python.exe -m alladin serve --broker mt5 --port 8001
```

Remplacer `SYSTEM-TEST-001` par l’identifiant réellement affiché. Ouvrir http://127.0.0.1:8001. Ne pas réutiliser un run lié à un autre compte ou broker. Le cockpit est en lecture seule. Le mode OBSERVE ne crée pas de résultat de trade puisqu’il n’exécute pas de trade.

## Jafar sans connexion externe

```powershell
.\.venv\Scripts\python.exe -m alladin jafar new --broker crypto-mock
.\.venv\Scripts\python.exe -m alladin jafar run --broker crypto-mock --cycles 3 --interval 1
.\.venv\Scripts\python.exe -m alladin jafar serve --broker crypto-mock --port 8002
```

Ouvrir http://127.0.0.1:8002 : cockpit rouge, montants USDT, cycles archivés, NO_TRADE. Jafar reste OBSERVE uniquement ; son budget est virtuel. L’accès public crypto réel reste à vérifier séparément avec un nouveau run du bon broker.

## Résultats persistés

Pour un run contenant des trades PAPER ou DEMO clôturés :

```powershell
.\.venv\Scripts\python.exe -m alladin outcomes refresh RUN-001
.\.venv\Scripts\python.exe -m alladin outcomes show RUN-001
```

Remplacer l’identifiant ; ajouter `--workspace JAFAR` pour lire ce workspace. Ces commandes consultent uniquement la base, sans MT5. Le panneau « Résultats & récompenses » présente les mêmes snapshots. Une liste vide après OBSERVE est normale. Une donnée ancienne incomplète affiche `INCOMPLETE`, sans récompense inventée. Les résultats séparent mode, devise et version de politique.

## Validation réelle encore nécessaire

F/G sont validés par simulation logicielle. Sur un compte DEMO dédié, il reste à vérifier ouverture, SL/TP, resserrement du stop, clôture partielle, clôture complète, redémarrage et absence de renvoi d’un ordre ambigu. Ne pas lancer ces opérations sur un compte réel. La commande de recette ci-dessus ne les automatise pas.

Le lot J prépare des données de recherche : excursions échantillonnées, coût DEMO rapporté par le broker, coût PAPER explicitement modélisé, reward expérimental. Il ne démontre ni rentabilité ni apprentissage SNN. Le prochain lot K pourra utiliser cette base sans modifier automatiquement le cerveau actif.
