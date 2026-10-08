# Alladin — programme offline après lot 8

Base vérifiée : `332eaeb2042c9d3f20fc5cf16056004fda149fbf` (2026-10-08). Ce document est un **plan d'exécution**, pas une fonctionnalité livrée ni une autorisation de trading.

## Ordre des travaux sans MT5

### A. Réservation atomique du risque (priorité bloquante)
- Ledger transactionnel SQLite avec transactions atomiques, version/lease et idempotency key par proposition ; identité de compte, phase, scope et devise explicites.
- Réserver avant soumission, confirmer sur fill, libérer sur rejet/annulation vérifiée, réconcilier après crash ; ne jamais relâcher un risque inconnu sur simple timeout.
- Garantir la somme des risques/expositions réservés + consommés <= limites ; concurrence multi-processus, retries, restart et phase switch testés.
- Ne pas modifier les protections natives ni permettre LIVE/DEMO.

### B. Réconciliation PAPER
- Reconstruire positions, cash, commissions, P&L et ordres à partir des événements et du MockBroker ; vérifier partial fills, duplicate events, stop/target, restart et mismatch.
- Bloquer les nouvelles entrées en cas d'état divergent ; conserver la gestion protectrice ; rapport de divergences traçable.

### C. Economic Intelligence (passif)
- Réutiliser les archives BLS/BEA et leur disponibilité causale ; surprises vs consensus uniquement avec source/version/timestamp de consensus réellement archivé.
- Revisions, heure de réception, fenêtre d'embargo, symbol mapping, gaps et licence documentés ; pas de lookahead ni de faux score prédictif.
- Analyser les réactions réalisées sur données historiques OOS, coûts compris ; pas d'exécution déclenchée par une annonce.

### D. Official Signal Intelligence (passif)
- Registre allowlist de comptes et domaines institutionnels authentifiés ; priorité aux sites/API/RSS officiels, réseaux sociaux seulement si accès autorisé/licencié.
- Capturer URL canonique, auteur, identifiant de publication, publication/réception, hash du contenu, modifications, retrait, liens vers source primaire et niveau de vérification.
- Séparer fait confirmé, déclaration officielle, opinion/projection et reprise ; déduplication inter-canaux, gestion des rumeurs et sources contradictoires.
- Jamais de permission d'ordre ou de contournement du PolicyGate/RiskEngine depuis un message social.

### E. Market Observatory
- Ajouter graphiques OHLCV via bibliothèque adaptée (p.ex. Lightweight Charts sous licence compatible), données fournies par brokers/feeds autorisés.
- Afficher positions PAPER, SL/TP, refus, événements économiques et sociaux avec horodatages de disponibilité ; état des feeds et lacunes visibles.
- Frontend lecture seule initialement ; aucun ordre à partir du graphique.

### F. Campagnes portefeuille et qualification
- Scénarios multi-actifs, overnight, corrélations, panne feed, slippage, drawdown et restart ; tests déterministes et reproductibles.
- Performance hors échantillon, biais de sélection et stabilité mesurés avant toute revendication de rendement.

## Critères transversaux
- Tests pytest, Ruff, mypy, diff --check et rapports exacts à chaque lot ; pas de PASS inventé.
- OBSERVE/PAPER opt-in seulement ; dossiers SIMULATION_ONLY ; RiskEngine obligatoire ; Jafar et SNN-X préservés.
- Pas de clés/API payantes ni de contrats de prop firms admis sans revue.

## Travaux impossibles à qualifier sans environnement Windows/MT5 DEMO
- Liaison terminal/serveur/compte et ownership/magic ; horaires brokers et symboles réels.
- Fills SL/TP, ordres modifiés/partiels, latence/slippage, disconnects, redémarrage et réconciliation réelle broker.
- Endurance terminal et validation des règles effectives des comptes ; aucune qualification LIVE automatique.
