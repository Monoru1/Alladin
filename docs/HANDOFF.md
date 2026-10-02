# ALLADIN — Agent Handoff & Operating Manual

**Dernière mise à jour : 2026-10-02**  
**Audience : Claude Code, Codex, ChatGPT et tout agent travaillant sur le repository**  
**Rôle : point d'entrée obligatoire avant toute modification structurelle**

---

## 0. Mission de ce document

Ce fichier n'est pas un résumé marketing. C'est le contrat de reprise du projet.

Un agent qui arrive sur Alladin doit pouvoir comprendre :
1. ce qu'est Alladin aujourd'hui ;
2. où le projet veut aller ;
3. quelles décisions ont déjà été prises et pourquoi ;
4. ce qui existe réellement dans le code versus ce qui n'est encore qu'une cible ;
5. ce qu'il est interdit de casser ;
6. comment implémenter sans réinventer le projet ;
7. comment prouver qu'un changement améliore réellement le système.

**Règle absolue : la documentation décrit des décisions et des cibles, pas nécessairement du code déjà implémenté. Toujours inspecter le repository avant de coder.**

---

## 1. Vision

Alladin est un système de trading expérimental autonome, initialement construit autour de MetaTrader 5, qui évolue vers une architecture **SNN-first** inspirée du fonctionnement biologique et du connectome de drosophile.

La finalité n'est pas de produire un bot qui applique mécaniquement RSI/EMA/Breakout.

La cible est un organisme logiciel capable de :

```text
PERCEVOIR
   ↓
ENCODER LE MARCHÉ
   ↓
DÉCIDER
   ↓
PASSER PAR LES LOIS DE RISQUE
   ↓
AGIR
   ↓
OBSERVER LES CONSÉQUENCES
   ↓
RECEVOIR REWARD / PAIN / SURPRISE
   ↓
APPRENDRE
   ↓
RECOMMENCER
```

Le résultat financier compte, mais le projet doit distinguer performance, qualité de décision, risque, calibration et chance.

Aucune architecture, y compris le SNN, n'est présumée supérieure avant validation expérimentale.

---

## 2. Philosophie BlackRock Aladdin

Le nom et une partie de la philosophie d'intégration viennent d'Aladdin de BlackRock : données communes, vision portefeuille, risque transversal, chaîne analyse -> risque -> trading -> suivi et observabilité.

Voir :
- `docs/DECISIONS/DECISION-012-BLACKROCK-ALADDIN-INSPIRATION.md`

Cette inspiration est **conceptuelle**. Le projet ne prétend ni reproduire ni connaître les modèles, données, code ou infrastructure propriétaires de BlackRock.

Notre rupture expérimentale est l'ajout d'un cerveau autonome apprenant SNN et d'une boucle de plasticité.

---

## 3. Sources de vérité et ordre de lecture

Avant une tâche structurelle, lire dans cet ordre :

1. `docs/HANDOFF.md` — ce document.
2. `docs/DECISIONS/README.md` — registre et statuts.
3. Les décisions `ADOPTED` pertinentes.
4. `docs/SNN/ALLADIN_SNN_BIBLE.md` — architecture/recherche SNN.
5. `docs/SNN/FLY_BRAIN_FUNCTION.md` — fonctionnement détaillé du cerveau.
6. `docs/STRATEGIES/README.md` — bibliothèque de stratégies.
7. `docs/STRATEGIES/SOURCE_MAP.md` — hiérarchie des sources.
8. `docs/STRATEGIES/scripts/EXTERNAL_SCRIPT_AUDIT.md` — audit du code externe.
9. Le code et les tests réellement présents dans le repository.

Si documentation et code divergent : **ne pas choisir arbitrairement**. Identifier la divergence et déterminer si la documentation décrit une cible future ou si le code/document est obsolète.

---

## 4. Décisions structurantes déjà prises

Le registre `docs/DECISIONS/` est la mémoire décisionnelle. À la date de ce handoff :

- **001 — SNN-first** : le SNN devient le cerveau cible.
- **002 — Reuse before rewrite** : préserver ce qui fonctionne.
- **003 — Deterministic Risk** : le cerveau apprend, le RiskEngine gouverne.
- **004 — Multi-broker** : format marché canonique, adapters.
- **005 — Strategy Lab** : les stratégies sont hypothèses/baselines/features.
- **006 — No LLM Runtime** : aucun LLM nécessaire dans le chemin critique H24.
- **007 — Mission Control** : cockpit scientifique + décisions persistantes.
- **008 — Autonomous Service** : Alladin doit tourner comme service supervisé.
- **009 — Jafar Shared Core** : la future branche crypto réutilise le core.
- **010 — No V1/V2** : développement incrémental, architecture cible unique.
- **011 — Autonomous Multi-Position Lifecycle** : autonomie sur toute la vie du trade.
- **012 — BlackRock Aladdin Inspiration** : inspiration conceptuelle documentée.

Ne pas réécrire silencieusement une décision. Une nouvelle conclusion qui invalide une ancienne décision doit créer une fiche qui la **SUPERSEDE**.

---

## 5. Architecture cible

```text
             MARKET / BROKER / EXCHANGE
                       │
                 BrokerAdapter
                       │
              Canonical Market Event
                       │
              Normalization / Features
                       │
                Sensory Encoding
                       │
                    SNN Brain
          ┌────────────┼─────────────┐
          │            │             │
       memory       plasticity    metabolism
                         │
                  ActionProposal
                         │
                 Deterministic
                   RiskEngine
                         │
                 ExecutionService
                         │
                 Broker / Exchange
                         │
                  PositionMonitor
                         │
                     Outcome
                         │
          reward / pain / surprise
                         │
                  learning loop

Journal + Replay + Observability traversent toute la chaîne.
```

---

## 6. Brain vs laws of physics

Le SNN peut :
- proposer LONG / SHORT / NO_TRADE ;
- produire confiance/incertitude ;
- réévaluer une position ;
- proposer HOLD, CLOSE, modification SL/TP, partial close ;
- apprendre à partir des conséquences.

Le SNN **ne peut pas** :
- contourner RiskEngine ;
- désactiver les limites de perte ;
- décider arbitrairement du volume final ;
- retirer les protections obligatoires ;
- brancher directement un ordre au broker ;
- modifier les lois de sécurité parce qu'il vient de perdre.

Principe : **Le cerveau apprend. Le RiskEngine gouverne.**

---

## 7. Deux vitesses d'adaptation

### Boucle rapide — runtime

Observe -> décide -> agit -> réévalue.

Elle permet l'adaptation contextuelle en temps réel.

### Boucle lente — évolution

Replay -> apprentissage -> validation -> OOS -> comparaison -> promotion.

Une mauvaise série de trades ne doit jamais pouvoir réécrire arbitrairement le cerveau actif.

Le système doit permettre de comparer un candidat au cerveau actuellement promu avant remplacement.

---

## 8. Cycle de vie autonome d'une position

```text
OBSERVE
 -> OPPORTUNITY
 -> LONG / SHORT / NO_TRADE
 -> RISK CHECK
 -> OPEN
 -> MONITOR
      -> HOLD
      -> MODIFY SL
      -> MODIFY TP
      -> PARTIAL CLOSE
      -> CLOSE
 -> OUTCOME
 -> REWARD / PAIN / SURPRISE
 -> LEARNING
```

Alladin peut générer un grand nombre d'opportunités et n'en exécuter qu'une fraction.

**Le nombre de trades n'est jamais un KPI.**

Une sortie anticipée est autorisée lorsque la thèse d'entrée devient invalide. Le système n'est pas obligé d'attendre mécaniquement TP ou SL.

Chaque décision intermédiaire doit être persistante et auditable.

---

## 9. Multi-position et portefeuille

Ne jamais traiter les trades simultanés comme indépendants par défaut.

Exemple : EURUSD LONG + GBPUSD LONG + EURGBP peut créer des expositions fortement liées.

Le RiskEngine/portfolio layer doit considérer :
- risque ouvert total ;
- concentration par devise/actif ;
- corrélations ;
- marge ;
- drawdown ;
- challenge headroom ;
- exposition directionnelle ;
- contraintes broker.

---

## 10. Reward n'est pas égal à PnL

Conceptuellement :

```text
Reward =
  PnL
+ qualité de décision
+ survie
+ qualité prédictive
+ calibration
- risque excessif
- drawdown
- mauvaise exécution
- violation de règle
```

Un trade gagnant peut être une mauvaise décision chanceuse.
Un trade perdant peut être une bonne décision statistique.

NO_TRADE doit pouvoir être récompensé lorsqu'il évite une exposition défavorable.

Pour les formules détaillées, lire la Bible SNN.

---

## 11. Replay et contre-factuels

Replay n'est pas un accessoire. Il est nécessaire à l'apprentissage et à la falsification.

Pour une décision à T0, le système doit progressivement pouvoir évaluer :
- ce qui s'est réellement passé ;
- MAE/MFE ;
- conséquences différées ;
- alternatives BUY / SELL / HOLD ;
- effet portefeuille ;
- coûts d'exécution.

Le replay doit utiliser les données réellement disponibles à l'instant de décision afin d'éviter look-ahead et leakage.

---

## 12. Strategy Research / Harvester

Les stratégies trouvées sur Internet ne sont jamais des vérités.

Sources possibles :
- littérature académique ;
- MQL5 CodeBase/articles ;
- QuantConnect et frameworks quant ;
- GitHub avec licence identifiable ;
- TradingView open source lorsque réutilisation permise ;
- documentation/éducation brokers ;
- Reddit et communautés pour les failure modes ;
- réseaux sociaux comme pistes, jamais comme preuve.

Pipeline cible :

```text
DISCOVER
 -> PROVENANCE
 -> LICENSE
 -> EXTRACT RULES
 -> AUDIT LEAKAGE / REPAINT
 -> CLEAN IMPLEMENTATION
 -> UNIT TESTS
 -> REPLAY
 -> TRAIN / VALIDATION / OOS
 -> COST / SLIPPAGE STRESS
 -> PAPER
 -> DEMO
 -> KEEP / MODIFY / KILL
```

Aucun script externe ne doit accéder directement à ExecutionService.

Une stratégie peut devenir :
- baseline ;
- feature ;
- signal auxiliaire ;
- enseignant ;
- contre-factuel ;
- expérience rejetée.

---

## 13. Trader Research

Étudier des praticiens ne signifie pas copier leurs trades.

Les idées doivent être transformées en hypothèses testables : trend following, volatility targeting, sizing, mean reversion, portfolio construction, etc.

Une réputation ou une performance déclarée n'est jamais une preuve suffisante.

Question systématique : **quelle règle précise peut-on extraire, reproduire et falsifier ?**

---

## 14. SNN / cerveau de mouche

Le projet explore le connectome MaleCNS de drosophile comme topologie biologique.

La documentation distingue explicitement :
- biologie observée ;
- analogie de conception ;
- hypothèse Alladin.

Ne jamais présenter « Mushroom Body = regime detector » ou « Central Complex = trend detector » comme un fait biologique.

Le premier objectif n'est pas de charger immédiatement le plus gros connectome possible. Il faut d'abord prouver la boucle avec un organisme réduit et des contrôles.

Comparaisons attendues :
- système classique ;
- SNN simple ;
- connectome biologique ;
- connectome rewired ;
- avec/sans R-STDP ;
- avec/sans surprise ;
- avec/sans mécanismes métaboliques.

Même data, coûts, splits, seeds et métriques.

---

## 15. Free Energy / surprise

Les concepts inspirés du Free Energy Principle sont des hypothèses de conception, pas une justification mystique.

Ils doivent être traduits en quantités mesurables : erreur de prédiction, surprise, incertitude, coût d'état, etc.

Si une formulation plus simple explique les mêmes résultats, préférer la formulation la plus falsifiable.

---

## 16. LLMs

Claude/Codex/ChatGPT sont des **ingénieurs et chercheurs autour d'Alladin**, pas le cerveau nécessaire au trading H24.

Usages :
- implémentation ;
- tests ;
- audit ;
- recherche ;
- documentation ;
- analyse d'expériences ;
- génération d'hypothèses.

Le runtime doit continuer à fonctionner sans appel LLM.

---

## 17. Mission Control

Le frontend cible n'est pas un clone décoratif de TradingView.

Il doit montrer ce qu'Alladin voit et pourquoi il agit :
- chart marché ;
- chandeliers ;
- positions ;
- SL/TP ;
- décisions SNN ;
- rejets RiskEngine ;
- stratégies/signaux auxiliaires ;
- régime ;
- confiance ;
- reward ;
- surprise/stress ;
- challenge ;
- état runtime ;
- historique/replay.

### Défaut actuel à éliminer

Une décision ne doit jamais disparaître de l'UI après quelques secondes.

Chaque décision doit posséder un ID stable et une fiche persistante permettant de retrouver :
- timestamp ;
- input/features ;
- état/version cerveau ;
- proposition ;
- confiance ;
- RiskEngine result ;
- JSON brut ;
- outcome ;
- reward.

MT5 reste la référence broker pour l'exécution, mais l'utilisateur ne doit pas avoir à ouvrir MT5 pour comprendre Alladin.

---

## 18. Service H24

Le terminal n'est pas l'interface d'exploitation cible.

Alladin doit pouvoir fonctionner comme service supervisé avec :
- auto-start ;
- restart policy ;
- heartbeat ;
- health checks ;
- logs ;
- checkpoints ;
- reprise après crash ;
- stale-data detection ;
- fail-closed ;
- cockpit distant sécurisé.

Avec l'intégration MT5 Python actuelle, le nœud d'exécution reste lié à Windows/MT5. Une séparation Linux Brain / Windows Execution est une architecture envisagée.

H24 signifie disponibilité/observation continue lorsque le marché et la plateforme le permettent, pas obligation de trader.

---

## 19. Jafar

Jafar est la future spécialisation crypto.

Ne pas reconstruire :
- cerveau ;
- replay ;
- journal ;
- observabilité ;
- expérimentation ;
- cockpit ;
- formats canoniques.

Adapter :
- exchange connectors ;
- microstructure ;
- funding/basis ;
- fonctionnement 24/7 ;
- types d'ordres ;
- risque spécifique crypto.

Ne jamais supposer qu'un cerveau/paramétrage appris sur FX se transfère automatiquement au crypto.

---

## 20. État réel vs architecture cible

**CRITIQUE :** avant toute implémentation, inspecter le code.

Certaines briques de l'ancien Alladin existent déjà et doivent probablement être conservées/adaptées :
- MT5 integration ;
- RiskEngine ;
- ChallengeWatchdog ;
- journal ;
- execution safety ;
- modes OBSERVE/PAPER/DEMO ;
- Opportunity lifecycle ;
- cockpit ;
- Strategy Lab ;
- Research Lab ;
- tests.

Les nouvelles décisions SNN, Harvester, cerveau, metabolism, reward, outcome avancé, Mission Control enrichi et service distribué peuvent être partiellement ou totalement non implémentées.

**Ne jamais annoncer qu'une cible documentaire est déjà codée sans preuve dans le repository/tests.**

---

## 21. Reuse before rewrite

Avant de supprimer un composant :
1. identifier son rôle ;
2. rechercher ses dépendances ;
3. lire ses tests ;
4. déterminer s'il peut devenir adapter/baseline/compat layer ;
5. mesurer le coût de migration ;
6. seulement ensuite décider de supprimer.

Une refonte esthétique ou conceptuelle n'est pas une justification suffisante pour casser du code validé.

---

## 22. Méthode scientifique obligatoire

Pour toute nouvelle brique M :

```text
Baseline
vs
Baseline + M
```

Même :
- dataset ;
- splits ;
- coûts ;
- seeds ;
- conditions d'exécution ;
- métriques.

Définir **avant** l'expérience :
- hypothèse ;
- métrique ;
- critère de succès ;
- critère d'échec ;
- risques de leakage ;
- coûts réalistes.

Si M n'apporte aucun bénéfice robuste, la complexité doit pouvoir être supprimée.

---

## 23. Hiérarchie de preuve

Du plus fort au plus faible :

1. résultat reproductible OOS dans notre pipeline ;
2. littérature robuste/répliquée ;
3. documentation technique primaire ;
4. code open source auditable ;
5. retour communautaire ;
6. affirmation sociale/non reproductible.

Une source faible peut générer une hypothèse. Elle ne doit pas devenir une vérité architecturale sans validation.

---

## 24. Sécurité d'exécution

Avant toute modification de l'exécution :
- conserver DEMO/PAPER comme environnement de développement ;
- vérifier account/mode ;
- SL obligatoire selon règles actives ;
- order_check avant order_send lorsque pertinent ;
- vérifier le résultat réel après envoi ;
- ownership/magic/comment ;
- reconciliation au restart ;
- journal append-only/auditable ;
- kill switch ;
- fail closed.

Ne jamais affaiblir une protection pour faire passer un test.

---

## 25. Ce qu'un agent doit faire avant de coder

1. Lire ce handoff.
2. Lire les décisions pertinentes.
3. Inspecter l'arborescence et les fichiers concernés.
4. Lire les tests existants.
5. Identifier ce qui est déjà implémenté.
6. Identifier les divergences docs/code.
7. Proposer/choisir la plus petite modification compatible avec la cible.
8. Préserver les invariants.
9. Ajouter/adapter les tests.
10. Exécuter les validations pertinentes.

Ne pas demander à l'utilisateur de réexpliquer une décision déjà documentée sans raison technique.

---

## 26. Ce qu'un agent doit livrer après une tâche

Toujours donner :
- objectif réalisé ;
- fichiers modifiés ;
- comportement avant/après ;
- tests exécutés ;
- résultats des tests ;
- limites ;
- risques ;
- migrations éventuelles ;
- travail restant ;
- nouvelle décision documentaire si nécessaire.

Si une hypothèse n'est pas prouvée, l'appeler hypothèse.

---

## 27. Interdits

Ne pas :
- contourner RiskEngine ;
- laisser le SNN envoyer directement un ordre ;
- connecter un script Internet à l'exécution ;
- copier du code sans vérifier licence/provenance ;
- utiliser des données futures dans un backtest ;
- confondre performance in-sample et preuve ;
- optimiser sur le test final ;
- présenter une anecdote Reddit/X comme preuve ;
- supposer qu'un broker expose une capacité sans vérifier ;
- réécrire un composant stable sans justification ;
- supprimer l'auditabilité ;
- rendre le runtime dépendant d'un LLM ;
- modifier une décision historique pour cacher un changement de cap.

---

## 28. Definition of Done — changement logiciel

Une modification n'est pas terminée simplement parce qu'elle compile.

Minimum :
- comportement implémenté ;
- tests pertinents ;
- erreurs/failures traitées ;
- journal/observabilité si nécessaire ;
- compatibilité/migration évaluée ;
- documentation mise à jour ;
- aucune régression de sécurité connue ;
- résultat reproductible.

---

## 29. Definition of Done — expérience de recherche

Une expérience n'est pas « gagnée » parce qu'une equity curve monte.

Minimum :
- hypothèse écrite ;
- provenance des données ;
- split train/validation/OOS ;
- absence de leakage connue ;
- coûts réalistes ;
- baseline ;
- seeds/répétitions adaptés ;
- métriques ;
- drawdown/tails ;
- résultats négatifs conservés ;
- conclusion proportionnée aux preuves.

---

## 30. Roadmap logique actuelle

L'ordre exact doit suivre les dépendances du code réel, mais la direction est :

1. sécuriser/compléter archive + replay ;
2. Outcome Engine ;
3. reward / pain / surprise ;
4. Brain API générique ;
5. petit SNN contrôlable ;
6. prouver que R-STDP modifie effectivement le comportement ;
7. contre-factuels ;
8. entraînement accéléré/challenge simulation ;
9. intégration connectome MaleCNS ;
10. Mission Control enrichi ;
11. service H24 robuste ;
12. population/swarm si les étapes précédentes justifient la complexité ;
13. PAPER puis MT5 DEMO prolongé ;
14. seulement ensuite évaluer si une étape supplémentaire est justifiée.

Cette liste n'autorise pas à ignorer les tests intermédiaires.

---

## 31. Comment reprendre une session demain

Un prompt court devrait suffire :

> Lis `docs/HANDOFF.md`, `docs/DECISIONS/` et les documents SNN pertinents. Inspecte ensuite le repository réel et les tests. Ne suppose pas que les cibles documentées sont déjà implémentées. Reprends à partir de l'état du code en respectant les invariants, puis propose la prochaine modification minimale et testable.

Ensuite l'agent doit travailler à partir du repo, pas demander un résumé complet de la conversation.

---

## 32. Principe directeur

> **Construire Alladin pour qu'il puisse montrer quand nous avons tort.**

Le projet ne doit pas protéger nos idées. Il doit les tester.

La sophistication n'est pas un objectif.
L'autonomie n'est pas l'absence de lois.
Le nombre de trades n'est pas une performance.
Une stratégie Internet n'est pas une preuve.
Un SNN biologique n'est pas automatiquement un edge.
Un résultat positif sans contrôle n'est pas une validation.

Le but est de construire un système autonome, observable, falsifiable, reproductible et capable d'évoluer sans perdre ses contraintes de sécurité.
