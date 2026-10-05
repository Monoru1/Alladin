# Jafar PAPER — runbook de soak

## État de validation

- SHORT SMOKE : VALIDATED
- 2–4H : NON VALIDATED
- 24H : NON VALIDATED
- SERVER : NON DEPLOYED

Le rapport et le validator sont strictement read-only. Ils ne doivent déclencher aucun ordre Binance.

## Smoke 15–30 minutes

```powershell
python -m alladin jafar new --broker crypto-public
python -m alladin jafar mode PAPER --broker crypto-public --run RUN-JAFAR-XXX
python -m alladin jafar run --broker crypto-public --mode PAPER --run RUN-JAFAR-XXX --cycles 10 --interval 30
python -m alladin jafar report --broker crypto-public --run RUN-JAFAR-XXX
python -m alladin jafar validate-paper --broker crypto-public --run RUN-JAFAR-XXX
```

Un verdict d'invariants `PASS` ne vaut pas qualification 2H ou 24H. Vérifier séparément `qualification.2H_VALIDATED` et `qualification.24H_VALIDATED`.

## Soak 2–4 heures

Lancer le runtime avec `--cycles 0 --interval 300`. Toutes les 30 minutes, vérifier `/api/runtime/health` : heartbeat et market progressent, provider `UP`, failures à zéro, runtime non `STOPPED`/`FAILED`.

```powershell
python -m alladin jafar validate-paper --broker crypto-public --run RUN-JAFAR-XXX --min-duration-h 2
```

Conserver le rapport JSON et le code retour. Ne passer au 24H qu'après un soak 2–4H propre.

## Soak 24 heures

Exécuter uniquement après validation 2–4H. Vérifier les transitions health, incidents stale/provider, intégrité journal, anomalies de duplication, cash/portefeuille, reprise après redémarrage et arrêt SIGTERM `STOPPING → STOPPED`.

## Codes retour validator

- `0` : PASS des invariants demandés
- `1` : WARN non bloquant
- `2` : FAIL d'un invariant ou d'une durée explicitement demandée

La qualification est indépendante : `SHORT_SMOKE`, `2H`, `24H`.
