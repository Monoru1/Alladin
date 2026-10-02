# Strategy — Multi-Factor Regime Routing

## But
Ne pas demander « quelle stratégie gagne ? », mais « quel comportement est cohérent avec l'état courant ? ».

Features candidates :
- trend strength ;
- realized volatility ;
- spread/liquidity ;
- mean-reversion score ;
- breakout state ;
- cross-asset/currency context ;
- carry lorsque disponible ;
- challenge/risk state.

Le routeur classique sert de **baseline**. Le SNN doit idéalement apprendre une sélection/combinaison plus riche sans recevoir le futur.

## Test
Comparer :
1. stratégie unique ;
2. règles de routing fixes ;
3. modèle statistique de routing ;
4. SNN.

Même RiskEngine et mêmes coûts pour tous.
