# Strategy Script Specifications

Ce dossier documente des implémentations de référence **indépendantes du broker**.

Règles :
- aucun script ne passe directement un ordre ;
- sortie = signal/candidat ;
- aucune donnée future ;
- paramètres explicites ;
- coûts testables ;
- mêmes interfaces pour replay/PAPER/DEMO ;
- RiskEngine obligatoire après le signal.

Documents :
- `TREND_REFERENCE.md`
- `MEAN_REVERSION_REFERENCE.md`
- `BREAKOUT_REFERENCE.md`
- `PAIRS_REFERENCE.md`

Le code tiers trouvé sur Internet n'est pas copié automatiquement : licence, look-ahead, repainting, hypothèses de coûts et sécurité doivent d'abord être audités.
