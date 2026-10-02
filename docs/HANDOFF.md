# ALLADIN — Handoff / reprise de travail

**Dernière mise à jour : 2026-10-02**

Ce fichier est le point d'entrée pour un nouvel agent Claude/Codex/ChatGPT avant toute modification importante.

## Lire d'abord
1. `docs/DECISIONS/README.md`
2. toutes les décisions `ADOPTED` pertinentes dans `docs/DECISIONS/`
3. `docs/SNN/ALLADIN_SNN_BIBLE.md`
4. `docs/SNN/FLY_BRAIN_FUNCTION.md`
5. `docs/STRATEGIES/README.md` et les documents associés lorsque le travail touche aux stratégies

## Architecture actuelle
Alladin est SNN-first. Le cerveau propose ; le RiskEngine déterministe gouverne. Les décisions sont persistantes/auditables. Le système cible est multi-instruments, broker-agnostic et exploitable comme service autonome. Les stratégies externes sont des hypothèses/baselines, jamais une voie directe vers l'exécution. Jafar doit réutiliser le core plutôt que reconstruire l'architecture.

## Discipline de modification
- réutiliser avant de réécrire ;
- ne jamais contourner RiskEngine ;
- ne pas brancher de code Internet directement à l'exécution ;
- distinguer décision, hypothèse et preuve externe ;
- préserver journal/replay/auditabilité ;
- ajouter des tests ;
- toute nouvelle brique scientifique doit avoir baseline, métrique et critère de falsification ;
- ne pas modifier silencieusement une décision : créer une décision qui supersède l'ancienne.

## Avant de coder
Inspecter le repo réel et vérifier que la documentation correspond encore à l'implémentation. Ne jamais supposer qu'une décision documentée est déjà codée.

## Après le travail
Documenter :
- fichiers modifiés ;
- tests exécutés et résultats ;
- migrations/compatibilité ;
- nouvelles hypothèses ;
- décisions nouvelles ou supersédées ;
- limites et travail restant.

## Principe directeur
Construire Alladin pour qu'il puisse montrer quand une hypothèse est fausse, pas seulement produire des résultats séduisants.
