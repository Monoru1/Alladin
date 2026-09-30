# Modèle de risque

Tout est déterministe (aucun LLM) et paramétré dans `config/challenge_profiles/*.yaml` (`risk:`).

## Capital de travail (dynamique)

```
working_capital = equity × 10 %
max_trade_risk  = working_capital × 8 %        ← PLAFOND (0,8 % de l'equity), pas un défaut
```

| equity | capital de travail | risque max / trade |
|---|---|---|
| 100 000 | 10 000 | 800 |
| 105 000 | 10 500 | 840 |
| 95 000 | 9 500 | 760 |

L'agent exprime `requested_risk_pct_of_working_capital` (ex. 4,5) ; jamais le lot. Au-dessus du plafond :
`over_cap_policy: reject` (défaut) ou `clip`.

## Position sizing

```
loss_per_lot = |entry − SL| / tick_size × tick_value_loss      (devise du compte)
volume       = floor_to_step( risk_amount / loss_per_lot ), borné par volume_max
```
- `entry` = prix **live** (ask pour BUY, bid pour SELL), jamais le prix annoncé par l'agent (écart > `max_entry_deviation_to_sl_ratio` × distance SL ⇒ rejet).
- `trade_tick_value` MT5 est déjà dans la devise du compte : aucune conversion de change n'est faite (vérifié sur compte EUR).
- Arrondi toujours vers le bas ; si `volume_min` dépasse le risque autorisé ⇒ rejet (jamais d'arrondi vers le haut).

## Contrôles du RiskEngine (toutes les raisons sont listées)

Mode DEMO / type de compte · kill switch · état du run et Watchdog · trading autorisé · run concordant · expiration · **SL obligatoire** · instrument négociable dans le sens · géométrie SL/TP · distance minimale broker · dérive de prix · spread (ratio au SL, points max) · ratio gain/risque · plafond par trade · nombre de positions · hedging · positions sans SL · marge de manœuvre **perte journalière / totale** (risque déjà ouvert + tampon) · plafond de risque ouvert total · **exposition nette par devise** · corrélation · marge requise vs marge libre.

Un risque trop grand pour la marge restante est **réduit** (et noté dans `adjustments`) ; s'il tombe sous le risque du volume minimum ⇒ rejet explicite.

## Exposition par devise

Chaque position contribue son risque au SL, signé : `BUY EURUSD` ⇒ +R EUR, −R USD. `BUY EURUSD + BUY GBPUSD + SELL USDCHF` = trois fois « USD court ». Limite : `max_currency_net_risk_pct_of_wc` (15 % du capital de travail). Message type : `correlated USD exposure exceeds threshold`.

## Valeurs par défaut (à calibrer)

`max_open_positions 5`, `max_total_open_risk_pct_of_wc 30`, `max_currency_net_risk_pct_of_wc 15`, `max_spread_to_sl_ratio 0.25`, `max_margin_usage_pct 50`, `headroom_buffer_pct_of_baseline 0.25`. Ce sont des hypothèses de départ, pas des résultats.
