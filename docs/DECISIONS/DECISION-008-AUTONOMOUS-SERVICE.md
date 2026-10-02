# DECISION-008 — Alladin comme service autonome

**Date :** 2026-10-02  
**Statut :** ADOPTED

## Décision
Le terminal ne doit pas être l'interface normale d'exploitation.

Le processus Alladin doit pouvoir démarrer et rester actif comme service/daemon supervisé. Le cockpit est l'interface utilisateur.

Pour l'intégration MT5 actuelle, un nœud Windows connecté au terminal MT5 reste nécessaire. Le cerveau peut à terme être séparé sur Linux.

## Exigences
- démarrage automatique ;
- restart policy ;
- heartbeat ;
- logs ;
- état visible ;
- fail-closed ;
- accès distant sécurisé ;
- aucune action par défaut si cerveau/données indisponibles.
