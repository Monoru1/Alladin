# ALLADIN

Laboratoire de trading Forex automatisé sur **MetaTrader 5 DEMO uniquement**.
Ce n'est pas un bot : c'est un orchestrateur expérimental qui explore largement, mesure tout, et laisse
un **Risk Engine déterministe** seul juge de l'exécution.

> **REAL MONEY TRADING = INTERDIT** dans cette version. Tout compte non DEMO (ou de type indéterminé) bloque l'exécution (*fail closed*).

## Installation (Windows, Python 3.12+)

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -e ".[dev]"
copy .env.example .env      # optionnel : le terminal MT5 déjà connecté suffit
```

Prérequis MT5 : terminal MetaTrader 5 ouvert, connecté à un compte **DEMO**, bouton **Algo Trading** activé.

## Commandes

| Commande | Effet |
|---|---|
| `python -m alladin demo [--scenario basic\|fail\|pass]` | Banc d'essai 100 % simulé (MockBroker/MockAgent) |
| `python -m alladin mt5 status` | Connexion, type de compte (DEMO/LIVE), solde, symboles découverts |
| `python -m alladin market scan` | Scanne l'univers réel du broker (aucun ordre) |
| `python -m alladin runs new` | Crée un run (RUN-001, RUN-002…) |
| `python -m alladin challenge status` | Equity, capital de travail, risque max, drawdowns, objectif, phase, état |
| `python -m alladin mt5 test-order` | Ordre DEMO contrôlé : récapitulatif puis **taper `EXECUTE`** pour envoyer |
| `python -m alladin run [--execute]` | Mode autonome (dry-run par défaut ; `--execute` exige de retaper le nom du run) |
| `python -m alladin kill [--clear]` | Kill switch : bloque toute exécution, run actif → KILLED |
| `python -m alladin positions close-all` | Fermeture explicite (confirmation `CLOSE`) des positions de ce run |
| `python -m alladin stats --by strategy` | Statistiques par stratégie / symbole / régime / session / agent |
| `python -m alladin runs verify RUN-001` | Vérifie la chaîne de hachage du journal |
| `python -m alladin serve` | API FastAPI en lecture seule |

## Tests et qualité

```bash
pytest                 # aucun MT5 requis (un faux module MetaTrader5 teste le vrai MT5Broker)
pytest --run-mt5       # + intégration MT5 réelle en lecture seule (compte DEMO connecté)
ruff check src tests && mypy src
```

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — composants, pipeline, garde-fous
- [docs/RISK_MODEL.md](docs/RISK_MODEL.md) — capital de travail, plafonds, sizing, exposition
- [docs/CHALLENGE_RULES.md](docs/CHALLENGE_RULES.md) — profils, règles officielles vs ALLADIN, états du run
- [docs/AGENTS.md](docs/AGENTS.md) — adapters Claude/Codex (sans clé API)

## Jafar — observation crypto isolée

Données spot avec budget de référence **virtuel**, sans stratégie active,
compte connecté ni ordre. Seul OBSERVE est autorisé. Journal, archive, runtime
et kill switch sont isolés d'Alladin.

    python -m alladin jafar new --broker crypto-mock
    python -m alladin jafar run --broker crypto-mock --cycles 3 --interval 0
    python -m alladin jafar serve --broker crypto-mock --port 8002
    python -m alladin jafar kill --broker crypto-mock

Choisir --broker crypto-public à la création ET à la reprise pour les données
spot publiques, ou crypto-testnet pour la source testnet. Aucun secret ni
abonnement API requis. Nouveau run pour changer de source. Après kill,
utiliser jafar kill --clear puis créer un nouveau run. Les accès réseau réels
restent à vérifier sur le poste ; mock et parseurs sont testés sans réseau.
