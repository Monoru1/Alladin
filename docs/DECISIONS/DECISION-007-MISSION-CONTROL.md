# DECISION-007 — Mission Control et décisions persistantes

**Date :** 2026-10-02  
**Statut :** ADOPTED

## Problème observé
Dans le cockpit actuel, certaines décisions disparaissent rapidement et leur JSON devient difficile à inspecter.

## Décision
Le frontend doit devenir un poste d'observation opérationnel et scientifique.

Chaque décision doit rester consultable et posséder un identifiant stable.

## Vue cible
- graphique marché ;
- chandeliers ;
- positions / SL / TP ;
- décisions SNN superposées ;
- décisions rejetées ;
- stratégie/signaux de contexte ;
- régime ;
- confiance ;
- reward ;
- surprise/stress ;
- état RiskEngine/challenge ;
- historique/replay.

## Inspection d'une décision
Un clic doit permettre de retrouver :
- timestamp ;
- données/features vues ;
- état/version du cerveau ;
- proposition ;
- confiance ;
- stratégies/signaux auxiliaires ;
- décision RiskEngine ;
- JSON brut ;
- outcome et reward lorsqu'ils deviennent disponibles.

MT5 reste la référence d'exécution broker, mais ne doit pas être nécessaire pour comprendre Alladin.
