# DECISION-035 — Autonomie surveillée, qualité et observabilité
- Date : 2026-10-08
- Statut : ADOPTED (architecture) ; PLANNED (qualification unattended)

## Contexte
Alladin doit pouvoir assurer surveillance, gestion autorisée et protection des positions sans présence constante de l'opérateur. La présence de tests unitaires ne prouve pas une exploitation 24/7 fiable.

## Décision
1. Exécuter une boucle supervisée avec heartbeat, watchdog, journaux append-only, idempotence, reconciliation au redémarrage, horloge synchronisée, monitoring data feed, état broker et calendrier, état des ordres et risque.
2. Sur perte réseau, feed périmé, profils contractuels expirés, absence de confirmation d'ordre, horloge incertaine ou incident majeur : bloquer nouvelles entrées, alerter, maintenir des protections natives côté broker si possible et tenter une réconciliation sûre. Ne jamais présumer qu'un stop local protège quand le processus est arrêté.
3. Superviser les positions, expositions corrélées, limites de drawdown, marge, spreads, slippage et limites de requêtes de la plateforme ; prévenir les tempêtes de modifications SL/TP et l'hyperactivité des EAs.
4. Mission Control affichera santé runtime, positions, événements macro, conformité par compte, décisions NO_TRADE, coûts, résultats et alertes ; un rapport quotidien rend compte des événements significatifs sans confondre exécution confirmée et ordre demandé.
5. Les modèles SNN-X et Jafar restent isolés ; pas d'auto-promotion de stratégie ni de contournement du RiskEngine. Les adaptations dynamiques passent par une promotion versionnée et éprouvée.
6. Qualification exigée : tests de panne réseau/data, DST/timezones, calendrier manquant, crash/restart, doublons d'ordres, fills partiels, week-end, gaps, kill switch, risque multi-comptes et soak prolongé sur environnement DEMO.
7. Les objectifs de service (disponibilité, latence, couverture des événements, faux signaux, temps de reprise, écarts de réconciliation) sont préenregistrés, mesurés et publiés en scorecards. Aucun statut READY sur simple réussite logicielle.
8. Passage à une infrastructure distante seulement après budget, sécurité des secrets, revue contractuelle, validation du broker et décision humaine explicite.

## Raisonnement
Autonomie implique gouvernance, audit et capacité de ne pas trader autant que prise de décisions.

## Invariants
Fail-closed, limites déterministes, journaux causalement rejouables, accès minimal aux secrets, pas d'exécution LIVE automatique.

## Questions ouvertes
Hébergement, coûts, disponibilité des flux, alertes hors bande, objectif de service réaliste.

## Conditions de révision
Tests d'endurance insuffisants, incident de sécurité, comportement inattendu ou évolution de la politique broker.

## Documents et code concernés
DECISION-007, 008, 011, 013, 017, 026, 028, 031-034 ; orchestration/, execution/, api/, journal/, tests/.
