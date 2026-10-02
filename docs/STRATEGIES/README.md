# ALLADIN — Strategy Research Library

Cette bibliothèque recense des stratégies **candidates à tester**, pas des promesses de rentabilité.

## Rôle dans Alladin SNN

Les stratégies ne remplacent pas le cerveau SNN. Elles servent de :
- baselines ;
- signaux sensoriels/contextuels ;
- enseignants/candidats de comparaison ;
- contre-factuels ;
- détecteurs de régime ;
- expériences falsifiables.

Chaque stratégie doit être évaluée avec les mêmes données, coûts, règles de risque et splits chronologiques.

## Grille d'évaluation

Pour chaque stratégie :
1. hypothèse économique/comportementale ;
2. marchés/régimes compatibles ;
3. données requises ;
4. formule du signal ;
5. paramètres à apprendre uniquement sur TRAIN/VALIDATION ;
6. coûts et fragilités ;
7. critères d'invalidation ;
8. protocole OOS ;
9. rôle potentiel comme entrée SNN ;
10. implémentation de référence dans `scripts/`.

## Priorités de recherche initiales

| Famille | Potentiel de recherche Alladin | Raison |
|---|---|---|
| Time-Series Momentum / Trend | Élevé | évidence multi-actifs, simple, falsifiable |
| Breakout / Volatility Expansion | Élevé | proche d'un détecteur événementiel, complément du trend |
| Mean Reversion | Moyen/élevé conditionnel | utile en range, dangereux en changement de régime |
| Pairs / Statistical Arbitrage | Élevé si données adaptées | signal relatif, contrôle naturel du beta directionnel |
| FX Carry | Moyen/élevé, spécialisé | signal macro structurel mais risque de crash |
| Multi-factor regime routing | Élevé | combine signaux sans imposer une stratégie universelle |

« Potentiel » signifie ici **intérêt expérimental**, pas rendement attendu.

## Sources de départ

- Hurst, Ooi & Pedersen, *A Century of Evidence on Trend-Following Investing*.
- Babu et al., *Trends Everywhere*.
- Gatev, Goetzmann & Rouwenhorst, *Pairs Trading: Performance of a Relative-Value Arbitrage Rule*.
- Clarida, Davis & Pedersen, *Currency Carry Trade Regimes*.
- Berge, Jordà & Taylor, *Currency Carry Trades*.
- Burnside, Eichenbaum & Rebelo, *Carry Trade and Momentum in Currency Markets*.

Tout script externe doit être audité, licencié correctement et revalidé sur nos propres données avant utilisation.
