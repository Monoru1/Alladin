# DECISION-032 — Economic Intelligence et décisions sensibles aux annonces
- Date : 2026-10-08
- Statut : ADOPTED (architecture) ; EXPERIMENTAL (efficacité prédictive)

## Contexte
Les nouvelles macroéconomiques modifient spreads, volatilité, liquidité, corrélations et parfois l'éligibilité réglementaire/contractuelle des ordres. DECISION-031 prévoit un calendrier sans définir son contrat.

## Décision
1. Introduire un EconomicEventService avec événements horodatés UTC, fuseau original, identifiant stable, pays/devise, importance, prévision, précédent, réalisé, source, heure de collecte, heure de publication et révisions. Enregistrer source/licence, fraîcheur, incertitudes et versions.
2. Relier chaque événement aux symboles réellement affectés, y compris indices, métaux, énergie et devises. Les expositions se combinent au niveau portefeuille. Ne pas conclure qu'une annonce USD ne touche que les paires Forex.
3. Modéliser PRE_EVENT, RELEASE_WINDOW, POST_EVENT et NORMAL. Les fenêtres sont paramétrées par firme/programme/phase/compte/symbole/événement, jamais codées globalement.
4. À chaque ActionProposal, l'EventPolicy produit ALLOW, REDUCE, DEFER, BLOCK ou EXIT_REVIEW avec reason_code, règles déclenchées et horodatage. RiskEngine/ComplianceGate garde le droit de veto ; les décisions stratégiques ne peuvent pas le contourner.
5. Utiliser prévision/réalisé/surprise exclusivement si disponibles de manière causale. En absence de publication fiable, désynchronisation, données périmées ou ambiguïté de règle : pas de nouvelle exposition concernée (fail-closed) ; les sorties de protection restent possibles suivant les capacités et règles du broker.
6. Tester séparément les comportements avant, au moment et après publication : écart prévision/réalisé, volatilité, spread, fills simulés pessimistes, gaps, slippage, coût net et événements révisés. Ne pas supposer de gain directionnel automatique lors d'une annonce.
7. Archiver les décisions NO_TRADE et la raison. Calendrier et signaux doivent être rejouables "as-of" sans lookahead.
8. Afficher dans Mission Control l'événement, le temps restant, la règle applicable et la décision explicable, sans confondre données réelles et hypothèses.

## Raisonnement
La valeur est le filtrage et la gestion du risque contextuels, puis seulement un éventuel alpha à démontrer expérimentalement.

## Invariants
Aucun trading interdit par une firme ; aucune exploitation de flux retardé, de gaps ou de règles d'annonce ; kill switch et modes existants conservés ; aucune activation LIVE automatique.

## Questions ouvertes
Fournisseurs autorisés de calendrier et SLA, latence, versions des annonces, règles par symbole, coût de données et accès hors PC local.

## Conditions de révision
Modification des conditions contractuelles, faiblesse des données, résultat OOS négatif ou violation de conformité constatée.

## Documents et code concernés
DECISION-017, 019, 021, 031 ; market/, research/, risk/, challenge/, api/ (cibles, non encore implémentées).

## Références consultées le 2026-10-08
- https://ftmo.com/fr/faq/puis-je-trader-les-annonces-economiques/
- https://ftmo.com/fr/forbidden-trading-practices/
