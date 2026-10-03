# DECISION-016 — Command Center global et identités visuelles distinctes

**Date :** 2026-10-03  
**Statut :** ADOPTED

## Contexte

Alladin et Jafar doivent pouvoir être supervisés depuis une même plateforme sans fusionner leurs états. L'utilisateur veut pouvoir passer rapidement d'un workspace à l'autre et disposer à terme d'une vue globale.

## Décision

La plateforme pourra exposer un **Command Center global** qui agrège des informations de supervision des workspaces, sans devenir leur source d'état métier.

La navigation cible comprend :
- vue globale Alladin + Jafar ;
- accès au Mission Control propre à chaque workspace ;
- switch explicite `ALLADIN <-> JAFAR` qui change le contexte opérationnel affiché, pas les garanties de sécurité ni le moteur d'exécution.

Informations globales candidates : health, mode, broker/account, equity, positions, risk, last cycle, brain version, alerts.

## Isolation

Le dashboard global lit/agrège des états workspace-scopés. Il ne doit pas transformer deux runtimes en un état mutable commun.

## Identité visuelle

Même système de composants et même grammaire UX, avec identité impossible à confondre :
- **Alladin** : bleu/cyan, froid, analytique/institutionnel ;
- **Jafar** : rouge profond/crimson, sombre, agressif mais professionnel, sans esthétique casino/neon.

Le thème visuel ne définit pas le runtime : Jafar n'est pas « Alladin en rouge ».

## Conséquences

- les APIs futures doivent pouvoir filtrer/scoper par workspace ;
- le switch UI ne doit jamais changer silencieusement de compte ou de mode ;
- les composants partagés sont encouragés ;
- le Command Center global arrive après les fondations d'isolation et de lifecycle, pas avant.

## Invariants

- aucune ambiguïté visuelle sur le workspace actif ;
- aucun merge implicite des positions/risk states ;
- pas de logique de trading dans le dashboard global ;
- lecture/supervision globale compatible avec Mission Control en lecture seule.

## Documents/code concernés

- `docs/DECISIONS/DECISION-007-MISSION-CONTROL.md`
- `docs/DECISIONS/DECISION-009-JAFAR-SHARED-CORE.md`
- futur Command Center
