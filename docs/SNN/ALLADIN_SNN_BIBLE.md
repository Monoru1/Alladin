# ALLADIN SNN — BIBLE D'ARCHITECTURE

**Statut : SOURCE DE VÉRITÉ — conception SNN-first**  
**Créé : 2026-10-02**  
**Portée : architecture cible, protocole scientifique, apprentissage, trading multi-instruments et migration d'Alladin.**

> Ce document est autonome. Pour toute décision concernant la nouvelle architecture SNN d'Alladin, il constitue le référentiel principal. Les anciens documents du dépôt restent des archives utiles mais ne définissent pas cette architecture.

## 1. Vision

Alladin évolue d'un orchestrateur de stratégies vers un laboratoire de trading adaptatif **SNN-first**.

Le but n'est pas de coder à la main une stratégie gagnante puis de demander au réseau de l'imiter. Le but est de construire un organisme neuronal artificiel qui :
1. perçoit le marché sous forme d'événements/spikes ;
2. conserve un état neuronal temporel ;
3. propose BUY, SELL ou NO_TRADE ;
4. subit les conséquences différées de ses décisions ;
5. reçoit des signaux de récompense, pénalité, surprise et survie ;
6. adapte ses connexions par plasticité, notamment R-STDP ;
7. apprend sous les contraintes déterministes d'un challenge ;
8. généralise hors échantillon et sur plusieurs instruments.

Le connectome biologique de drosophile **MaleCNS** est une hypothèse d'architecture à tester, pas une garantie d'alpha.

## 2. Principe non négociable : cerveau apprenant, lois déterministes

Le SNN peut apprendre à décider. Il ne peut jamais modifier ou contourner :
- le RiskEngine ;
- les limites du challenge ;
- les contrôles du broker ;
- le SL obligatoire ;
- le kill switch ;
- les contrôles DEMO/PAPER ;
- les limites d'exposition, de marge et de drawdown.

Le RiskEngine représente les lois physiques de l'environnement.

Aucun passage en argent réel ne peut être justifié par la seule performance d'entraînement. La progression prévue est : replay/backtest -> validation chronologique/OOS -> PAPER -> MT5 DEMO prolongé -> décision humaine séparée.

## 3. Architecture cible

```text
                         ALLADIN SNN
                              |
                  Market / MT5 / archive
                              |
                    Sensory Normalizer
                              |
                       Spike Encoder
                              |
                              v
                  +---------------------+
                  |      SNN BRAIN      |
                  | MaleCNS / controls  |
                  | LIF/AdEx            |
                  | STDP / R-STDP       |
                  | temporal state      |
                  +----------+----------+
                             |
                    BUY / SELL / HOLD
                             |
                       TradeIntent
                             |
                  +----------v----------+
                  |   RISK ENGINE       |
                  |   DETERMINISTIC     |
                  +----------+----------+
                             |
                       PAPER / DEMO
                             |
                         Outcome
                             |
          +------------------+------------------+
          |                  |                  |
        Reward        negative signal        Surprise
          |                  |                  |
          +------------------+------------------+
                             |
                      Metabolic State
                             |
                           R-STDP
                             |
                    future behaviour
```

## 4. Ce que l'on conserve d'Alladin

On ne réécrit pas ce qui fonctionne uniquement pour obtenir une architecture plus élégante.

À préserver autant que possible :
- BrokerAdapter / MT5Broker ;
- ExecutionService ;
- RiskEngine et PositionSizer ;
- ChallengeWatchdog et profils de challenge ;
- journal append-only et audit ;
- RunManager / notion de RUN ;
- PositionMonitor / reconciliation ;
- modes OBSERVE/PAPER/DEMO ;
- protections DEMO-only actuelles ;
- MarketUniverse et découverte d'instruments ;
- infrastructure de tests ;
- cockpit et observabilité lorsqu'ils restent compatibles ;
- données/replay existants lorsqu'ils sont réutilisables.

À rendre secondaire, remplacer ou supprimer si nécessaire :
- StrategyRouter comme cerveau principal ;
- obligation de choisir parmi TREND/BREAKOUT/RANGE ;
- Claude/Codex comme décideurs de trade ;
- heuristiques qui empêchent le SNN d'apprendre directement.

Les anciennes stratégies restent utiles comme **baselines, enseignants éventuels, contrôles et contre-factuels**.

## 5. Univers multi-instruments

La conception n'est plus BTC-only. Alladin doit pouvoir apprendre sur les instruments compatibles avec son environnement et ses règles de risque.

Le réseau ne doit pas confondre les échelles physiques de marchés différents. Les entrées doivent donc être normalisées, par exemple :
- rendement plutôt que prix absolu ;
- ATR / volatilité réalisée ;
- spread relatif au mouvement/ATR ;
- volume normalisé localement ;
- tick size / tick value ;
- liquidité ;
- session ;
- momentum multi-horizon ;
- accélération ;
- distance normalisée aux niveaux ;
- corrélations et exposition ;
- order-flow/order-book lorsqu'ils sont réellement disponibles et comparables.

Une spécialisation par instrument, famille, session ou régime peut émerger. Elle ne doit pas être imposée sans preuve.

## 6. Encodage sensoriel

Le SNN ne reçoit idéalement pas simplement « EURUSD = 1.XXXX ». Le flux financier est transformé en événements neuronaux.

Deux familles doivent être comparées :
- **rate coding** : intensité d'une variable -> fréquence de spikes ;
- **event coding** : changement significatif -> événement/spike.

Des populations distinctes peuvent encoder :
- mouvement positif/négatif ;
- accélération/décélération ;
- volatilité ;
- volume ;
- spread ;
- déséquilibre acheteur/vendeur ;
- risque portefeuille ;
- état du challenge ;
- session et contexte temporel.

L'encodage fait partie de l'hypothèse expérimentale et doit être ablaté.

## 7. Connectome et SNN

Source cible : MaleCNS / connectome drosophile.

Étapes :
1. importer le graphe ;
2. conserver provenance, types et régions lorsque disponibles ;
3. construire des sous-graphes contrôlables ;
4. mesurer taille, densité, distribution des degrés et motifs ;
5. élaguer seulement avec justification mesurable ;
6. comparer le vrai graphe à des graphes contrôles de taille/densité comparables.

Modèles neuronaux :
- LIF d'abord ;
- AdEx seulement s'il apporte un bénéfice démontré.

Contrôles indispensables :
- graphe aléatoire ;
- degree-preserving rewiring ;
- small-world ;
- reservoir aléatoire ;
- connectome figé ;
- SNN sans plasticité ;
- SNN avec plasticité.

Le projet doit pouvoir conclure : **MaleCNS n'apporte aucun avantage**.

## 8. Plasticité : STDP et R-STDP

La STDP modifie une synapse en fonction de la relation temporelle entre spikes pré- et post-synaptiques.

Forme conceptuelle :

```text
pre avant post  -> potentiation selon fenêtre temporelle
post avant pre  -> depression selon fenêtre temporelle
```

R-STDP ajoute un modulateur global de récompense :

```text
Delta w_ij ~ eligibility_ij * reward_modulator
```

Une trace d'éligibilité permet d'attribuer plus tard une conséquence aux synapses impliquées auparavant.

La récompense ne doit donc pas nécessairement arriver au moment de la décision.

## 9. Reward Engine

Interdiction conceptuelle :

```text
reward = profit
```

Le signal doit être multidimensionnel.

Forme de travail :

```text
R_t =
  alpha * R_pnl
+ beta  * R_decision_quality
+ gamma * R_survival
+ delta * R_prediction
+ eta   * R_calibration
- lambda * P_risk
- mu     * P_drawdown
- nu     * P_execution
- xi     * P_rule_pressure
```

Les coefficients sont des hyperparamètres expérimentaux, pas des vérités.

Conséquences :
- un trade gagnant obtenu par une décision dangereuse ne doit pas être automatiquement fortement récompensé ;
- un trade perdant issu d'une décision raisonnable ne doit pas être automatiquement traité comme une catastrophe ;
- NO_TRADE doit pouvoir être récompensé ;
- une proposition rejetée par le RiskEngine peut produire un signal négatif d'apprentissage sans permettre au cerveau de contourner le rejet.

## 10. État métabolique

État interne conceptuel :

```text
M_t = (Energy, Stress, Surprise, GoalPressure, Confidence)
```

Exemples :
- **Energy** : capacité de survie/capital disponible ;
- **Stress** : pression liée au risque, pertes récentes et proximité des limites ;
- **Surprise** : divergence entre attente et observation ;
- **GoalPressure** : distance à l'objectif sous contrainte temporelle ;
- **Confidence** : calibration empirique des décisions récentes.

Ce sont des variables numériques fonctionnelles. Elles ne supposent aucune conscience ou sensation réelle.

L'état métabolique peut moduler :
- seuils de firing ;
- exploration ;
- intensité de plasticité ;
- décision d'abstention ;
- allocation de populations neuronales.

## 11. NO_TRADE est une action

Le système doit pouvoir choisir explicitement :
- BUY ;
- SELL ;
- NO_TRADE/HOLD.

Sinon, l'apprentissage peut favoriser artificiellement l'overtrading.

Le NO_TRADE doit être évalué a posteriori via des contre-factuels raisonnables : que se serait-il passé avec BUY, SELL ou HOLD sur un horizon défini ?

## 12. Outcome Engine et attribution différée

Chaque décision doit produire un dossier d'outcome comprenant autant que possible :
- PnL net ;
- R multiple ;
- MAE ;
- MFE ;
- drawdown contribution ;
- spread ;
- slippage ;
- commissions/swap ;
- durée ;
- risque demandé/autorisé ;
- contexte du challenge ;
- calibration de confiance ;
- évolution future utilisée pour les contre-factuels.

Une récompense peut être distribuée à plusieurs horizons :

```text
T0       décision
T+5m     réaction immédiate
T+30m    MAE/MFE
T+n      clôture
T+n+k    contre-factuel
T+1j     conséquence portefeuille/challenge
```

Exemple de décomposition conceptuelle :

```text
R = 0.4 * trade_outcome
  + 0.2 * decision_quality
  + 0.2 * portfolio_consequence
  + 0.2 * counterfactual_quality
```

Ces valeurs ne sont que des paramètres initiaux à tester.

## 13. Surprise et principe de libre énergie

L'utilisation du principe de libre énergie est une inspiration de modélisation, pas une affirmation que le système reproduit un cerveau biologique.

On mesure au minimum une erreur de prédiction :

```text
surprise_t = distance(predicted_state, observed_state)
```

Le système peut apprendre à réduire une combinaison de surprise, risque et perte économique, tout en évitant la solution triviale « ne jamais agir ».

Toute extension dite free-energy doit être comparée à une version sans cette extension.

## 14. Challenge = environnement de survie

Un RUN Alladin peut servir d'épisode.

```text
RUN-001 -> episode
RUN-002 -> episode
...
```

L'environnement fournit :
- capital initial ;
- objectif ;
- limite de perte journalière ;
- limite de perte totale ;
- règles de risque ;
- éventuellement limite temporelle et règles de consistency.

Atteindre l'objectif n'est pas une preuve de robustesse. Échouer un challenge n'est pas une « mort » biologique ; c'est la terminaison d'un épisode expérimental.

Les règles FTMO utilisées doivent être vérifiées contre les règles publiques en vigueur au moment de l'expérience. Les règles personnalisées Alladin doivent être explicitement distinguées.

## 15. Contre-factuels et replay

Le Replay Engine est une dépendance critique.

Pour une décision donnée, on veut pouvoir comparer sur les mêmes données :

```text
action choisie : BUY
BUY  -> résultat observé/simulé
SELL -> résultat contrefactuel
HOLD -> résultat contrefactuel
```

Les contre-factuels doivent inclure coûts, spread, slippage et règles d'exécution réalistes pour ne pas créer un enseignant irréaliste.

Les données brutes nécessaires au replay doivent être archivées avec horodatage et provenance.

## 16. Essaim

L'essaim n'est pas un simple vote majoritaire obligatoire.

Plusieurs organismes peuvent différer par :
- seed ;
- sous-graphe ;
- hyperparamètres ;
- historique d'apprentissage ;
- spécialisation instrument/régime.

Agrégations à tester :
- vote ;
- moyenne pondérée par calibration ;
- veto d'incertitude ;
- meta-readout ;
- spécialisation contextuelle.

Chaque mécanisme doit battre des contrôles plus simples hors échantillon.

## 17. Linux et MT5

Architecture cible possible :

```text
LINUX
- ingestion/archive
- feature engineering
- spike encoding
- simulation SNN
- R-STDP
- metabolism
- reward/outcome
- replay/training
- persistence/checkpoints

        intents / outcomes

WINDOWS + MT5
- MT5Broker
- deterministic RiskEngine
- ChallengeWatchdog
- ExecutionService
- PositionMonitor
```

Le protocole entre les deux doit être authentifié, versionné, idempotent et fail-closed.

Une panne du cerveau Linux ne doit jamais déclencher une action par défaut.

## 18. Persistance

Un SNN stateful doit pouvoir être restauré.

Checkpoint minimal :
- version du modèle ;
- hash/topologie du graphe ;
- poids synaptiques ;
- états neuronaux nécessaires ;
- traces d'éligibilité ;
- état métabolique ;
- RNG seed/state lorsque pertinent ;
- normaliseurs ;
- compteur d'épisode ;
- version du reward function ;
- version de l'encodeur ;
- provenance des données.

Les checkpoints doivent être associés aux expériences et non silencieusement écrasés.

## 19. Protocole scientifique

Ordre de comparaison recommandé :
1. baselines simples ;
2. modèles temporels conventionnels ;
3. reservoir aléatoire ;
4. graphe biologique figé ;
5. SNN biologique ;
6. SNN + STDP/R-STDP ;
7. état métabolique ;
8. mécanisme free-energy-inspired ;
9. essaim.

Règle : une complexité supplémentaire doit produire une amélioration robuste OOS ou apporter une valeur diagnostique clairement démontrée.

Validation :
- splits chronologiques ;
- purge/embargo ;
- aucune optimisation sur le test final ;
- plusieurs seeds ;
- coûts réalistes ;
- sensibilité au spread/slippage ;
- reporting des expériences négatives ;
- comparaison à complexité raisonnablement équivalente.

Métriques :
- expectancy en R ;
- max drawdown ;
- Sortino ;
- Calmar ;
- profit factor ;
- turnover ;
- stabilité entre seeds ;
- stabilité entre instruments/régimes ;
- calibration ;
- coût/latence ;
- taux de rejet RiskEngine ;
- performance de NO_TRADE.

## 20. Migration de l'Alladin actuel

### Phase 0 — Gel et cartographie
- garder la branche stable ;
- inventorier composants réutilisables ;
- figer les tests actuels ;
- aucune suppression sans remplacement testé.

### Phase 1 — Data + Replay
- archivage suffisant pour rejouer ;
- données normalisées multi-instruments ;
- coûts/exécution reproductibles.

### Phase 2 — Outcome Engine
- calcul PnL/R/MAE/MFE ;
- conséquences portefeuille ;
- contre-factuels BUY/SELL/HOLD.

### Phase 3 — Reward/Metabolism
- reward vector/scalar versionné ;
- stress/surprise/energy/confidence ;
- tests contre reward hacking.

### Phase 4 — Brain API
Interface conceptuelle :
```python
observe(market_state)
decide() -> action
learn(outcome)
checkpoint()
restore()
```

### Phase 5 — Petit organisme
- petit SNN contrôlable ;
- données replay ;
- vérifier causalité et attribution ;
- vérifier que les poids changent comme prévu.

### Phase 6 — R-STDP
- traces d'éligibilité ;
- reward différé ;
- ablations frozen/STDP/R-STDP.

### Phase 7 — Challenge training
- milliers d'épisodes accélérés ;
- validation OOS ;
- détection du reward hacking.

### Phase 8 — MaleCNS
- importer/pruner ;
- contrôles de graphes ;
- benchmarks taille/latence/mémoire ;
- comparaison au petit SNN et reservoirs.

### Phase 9 — Swarm
Uniquement si les agents individuels produisent déjà un signal exploitable.

### Phase 10 — PAPER puis MT5 DEMO
- aucune adaptation non auditée en production ;
- shadow mode avant autorisation d'ordres ;
- comparaison cerveau vs baselines en parallèle.

## 21. Organisation de code cible

Structure indicative, à adapter au repo réel :

```text
src/alladin/
  snn/
    brain/
    connectome/
    neurons/
    synapses/
    plasticity/
    encoding/
    metabolism/
    reward/
    outcome/
    replay/
    swarm/
    checkpoints/
    experiments/
```

Ne pas créer ces dossiers mécaniquement avant que leurs responsabilités soient nécessaires.

## 22. Rôle de Claude et Codex

Claude/Codex servent principalement à :
- implémenter ;
- auditer ;
- écrire/faire tourner les tests ;
- analyser les expériences ;
- détecter les incohérences ;
- documenter ;
- proposer des hypothèses.

Ils ne doivent pas constituer un oracle opaque nécessaire au fonctionnement du SNN.

Pour réduire les tokens, chaque handoff doit fournir :
1. objectif précis ;
2. fichiers concernés ;
3. invariants ;
4. critères d'acceptation ;
5. commandes de tests ;
6. ce qu'il ne faut pas modifier.

## 23. Invariants

1. Le RiskEngine reste déterministe.
2. Le cerveau ne choisit jamais directement un volume final non contrôlé.
3. Toute action est journalisée.
4. Toute fonction de récompense est versionnée.
5. Toute expérience est reproductible autant que possible.
6. NO_TRADE est une action de premier rang.
7. Multi-instruments implique normalisation.
8. Aucun résultat in-sample ne justifie un passage réel.
9. MaleCNS doit battre des contrôles pour être conservé.
10. Un résultat nul ou négatif est un résultat scientifique valide.
11. Réutiliser avant de réécrire ; supprimer uniquement avec justification.
12. Les garde-fous ne sont jamais apprenants.

## 24. Définition de succès

Le succès scientifique n'est pas « gagner un trade ».

Le système doit démontrer, hors échantillon et après coûts :
- comportement reproductible ;
- risque contenu ;
- amélioration par apprentissage par rapport aux contrôles ;
- robustesse multi-régimes ;
- absence de dépendance à quelques trades extrêmes ;
- stabilité raisonnable entre seeds ;
- bénéfice démontré des composants biologiques ajoutés.

Le succès opérationnel d'une future version DEMO exige en plus stabilité, observabilité, reprise après panne et respect systématique des contraintes.

## 25. Question centrale

> Un système neuronal impulsionnel inspiré d'un connectome biologique, soumis à une boucle perception -> décision -> conséquence -> récompense/surprise -> plasticité, peut-il apprendre des comportements de trading multi-instruments robustes hors échantillon, tout en restant enfermé dans des contraintes déterministes de survie et de risque ?

Cette question doit rester falsifiable.

---

**Décision d'architecture du 2 octobre 2026 : Alladin devient SNN-first. Le SNN est le cœur apprenant du nouveau système ; l'infrastructure de risque, d'exécution, de challenge, de journalisation et de replay d'Alladin constitue l'environnement sécurisé autour de ce cerveau.**
