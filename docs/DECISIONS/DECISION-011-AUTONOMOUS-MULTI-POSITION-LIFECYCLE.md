# DECISION-011 — Autonomous Multi-Position Lifecycle

**Date :** 2026-10-02  
**Statut :** ADOPTED

## Vision

Alladin doit pouvoir fonctionner sans intervention humaine trade par trade : observer simultanément de nombreux instruments, générer de nombreuses opportunités, n'en exécuter qu'une fraction, puis gérer chaque position jusqu'à sa fermeture.

Le nombre de signaux n'est pas un objectif de performance. Une journée peut produire 100 opportunités, 20 propositions acceptables et beaucoup moins d'exécutions si le cerveau ou le RiskEngine estime que les autres ne méritent pas d'exposition.

## Cycle d'une position

```text
OBSERVE
  -> OPPORTUNITY
  -> LONG / SHORT / NO_TRADE
  -> RISK VALIDATION
  -> OPEN
  -> CONTINUOUS RE-EVALUATION
       -> HOLD
       -> MODIFY_SL
       -> MODIFY_TP
       -> PARTIAL_CLOSE
       -> CLOSE
  -> OUTCOME
  -> REWARD / PAIN / SURPRISE
  -> LEARNING
```

Une entrée n'est donc pas une décision terminale. La vie entière du trade est une séquence de décisions auditables.

## Sortie anticipée

Alladin doit pouvoir proposer de fermer une position avant TP ou SL si l'information qui justifiait l'entrée disparaît ou si le nouvel état du marché rend la continuation défavorable.

Il ne doit pas attendre mécaniquement qu'un TP ou SL soit touché.

Toute fermeture/modification reste soumise aux règles déterministes de sécurité et d'exécution.

## Multi-position

Alladin raisonne portefeuille et non uniquement trade par trade. Plusieurs signaux corrélés peuvent représenter une seule exposition économique.

Le RiskEngine doit considérer au minimum :
- exposition totale ;
- exposition par devise/actif ;
- corrélation/concentration ;
- drawdown ;
- risque ouvert ;
- contraintes challenge ;
- marge et contraintes broker.

## Auto-adaptation vs auto-modification

Deux boucles sont séparées.

### Boucle rapide — production
Le cerveau observe, décide, réévalue et adapte les actions au contexte courant.

### Boucle lente — apprentissage/promotion
Les modifications durables du cerveau, paramètres ou politiques sont évaluées par replay, validation et OOS avant promotion vers le runtime actif.

Une expérience ou une mauvaise séquence de trades ne doit pas pouvoir réécrire arbitrairement le cerveau de production.

## H24

L'objectif d'exploitation est un système supervisé capable de tourner en continu lorsque l'infrastructure marché correspondante est ouverte/disponible, avec heartbeat, checkpoints, reprise, journalisation, stale-data detection et fail-closed.

H24 signifie disponibilité et observation continue, pas obligation de trader.

## Mesure du résultat

Le résultat financier compte, mais n'est pas la seule mesure. Alladin doit aussi mesurer la qualité de décision, le risque pris, le drawdown, la calibration, l'exécution, les contre-factuels et la survie.

Un trade gagnant peut être une mauvaise décision chanceuse ; un trade perdant peut être une bonne décision statistique.

## Invariant

**Le cerveau peut décider de sortir. Il ne peut jamais décider d'abolir les lois de risque qui l'encadrent.**
