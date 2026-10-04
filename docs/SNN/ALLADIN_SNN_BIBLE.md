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


# 26. Spécification détaillée héritée du concept SNN-BTC

Cette section préserve le raisonnement technique qui a conduit à l'architecture SNN-first, mais l'étend à Alladin multi-instruments. Les valeurs numériques ci-dessous sont des **points de départ expérimentaux** sauf lorsqu'elles sont explicitement marquées comme faits vérifiés.

## 26.1 Fondations MaleCNS

**Fait vérifié (Janelia MaleCNS, consultation 2026-10-02)** : le dataset MaleCNS contient environ **166 700 neurones** et **11 710 types neuronaux**. Il s'agit d'une collaboration incluant FlyEM/HHMI Janelia, University of Cambridge, MRC LMB et Google Research.

À vérifier directement lors de l'ingestion :
- nombre exact d'arêtes/synapses de la version de dataset utilisée ;
- version NeuPrint ;
- disponibilité et qualité des annotations ROI, neurotransmetteur et soma ;
- licences et provenance.

Le graphe doit être exporté sous une représentation reproductible :
- tables Parquet pour neurones/connexions/métadonnées ;
- matrices creuses CSR pour le calcul ;
- hash cryptographique de chaque snapshot de dataset ;
- manifeste contenant dataset/version/date/requêtes d'extraction.

## 26.2 Hypothèse de pruning biologique

L'objectif initial est de réduire radicalement le graphe afin de concentrer le calcul sur les circuits candidats et de rendre les expériences abordables.

**Hypothèse à tester, pas vérité neuroscientifique** :
- retirer les circuits principalement sensoriels/moteurs sans analogue utile pour le flux financier ;
- préserver en priorité MB, CX, relais pertinents, projections sensorielles sélectionnées et une petite population de sortie.

Architecture expérimentale proposée :

| Bloc | Taille de départ | Hypothèse fonctionnelle |
|---|---:|---|
| Mushroom Body | 4k–5k | contexte/régime et apprentissage |
| Central Complex | 3k–4k | état directionnel, persistance/hystérésis |
| projections d'entrée | 6k–9k | interface sensorielle marché |
| relais/modulation | 2k–4k | communication entre blocs |
| sorties | <300 | Long / Short / Flat |

Tailles d'expérience :
- Core : 8k–10k ;
- Standard : 15k–20k ;
- Large : 30k–40k.

Ces tailles ne sont pas « optimales » par définition. Elles doivent être comparées à coût calculatoire et protocole comparables.

Contrôles après pruning :
- composantes connexes ;
- chemins entrée -> circuits internes -> sortie ;
- distribution des degrés ;
- motifs ;
- ratio excitateur/inhibiteur lorsque l'annotation le permet ;
- conservation des propriétés du graphe par rapport au sous-graphe source.

## 26.3 Dynamique neuronale

Baseline : LIF. Variante : AdEx.

Point de départ expérimental :
- pas interne potentiel : 1 ms ;
- fenêtre d'intégration décisionnelle : 50–500 ms ;
- simulation event-driven à benchmarker contre pas fixe.

Poids initiaux candidats :

```text
w_ij(0) = g_global * synapse_count_ij * sign_ij
```

où `sign_ij` dépend de l'annotation excitatrice/inhibitrice disponible.

L'idée « rayon spectral proche de 1 / edge of chaos » est une **hypothèse de réglage reservoir**, pas un objectif biologique universel. Elle doit être mesurée et ablatée.

Prototype candidat : Brian2. Moteur optimisé ultérieur : Numba/C++/autre backend sparse seulement si le profilage le justifie.

## 26.4 R-STDP à trois facteurs

Forme centrale de travail :

```math
\Delta w_{ij}(t) = \eta \; D(t) \; e_{ij}(t)
```

avec :
- `eta` : taux d'apprentissage ;
- `D(t)` : troisième facteur/modulateur global ;
- `e_ij(t)` : trace d'éligibilité de la synapse.

Dynamique conceptuelle de la trace :

```math
\dot e_{ij} = -\frac{e_{ij}}{\tau_e} + STDP(pre_i, post_j)
```

La littérature sur les règles d'apprentissage à trois facteurs supporte l'usage de traces d'éligibilité comme mémoire transitoire permettant de relier activité synaptique et signal retardé. Cela justifie le mécanisme général, **pas notre choix de reward financier**.

Première restriction de plasticité à tester :
- entrées -> CX ;
- Kenyon cells -> MBON ;
- CX -> sorties.

Comparer :
1. poids gelés ;
2. STDP locale ;
3. R-STDP ;
4. R-STDP + métabolisme.

## 26.5 Readout et contrôles

Un readout Ridge/RLS doit rester disponible comme bras de comparaison.

Progression :
- A : reservoir/connectome figé + Ridge ;
- B : SNN figé + même protocole de readout ;
- C : SNN + R-STDP ;
- D : SNN + R-STDP + métabolisme.

Une amélioration du modèle D n'est attribuable au mécanisme ajouté que si les contrôles précédents sont comparables.

## 26.6 Encodage sensoriel hybride

### Event coding prix

```text
price move >= +delta -> spike ON
price move <= -delta -> spike OFF
volatility breakout -> burst / higher event density
quiet regime -> lower event density
```

`delta` doit être normalisé (ticks, ATR ou volatilité) afin de rendre les instruments comparables.

### Rate coding contexte

Variables candidates :
- return robuste normalisé ;
- volatilité réalisée ;
- volume/tick volume lorsque pertinent ;
- spread ;
- profondeur/imbalance lorsque disponible ;
- momentum multi-horizon ;
- état portefeuille/challenge.

Point de départ : 16–32 neurones d'entrée par variable avec courbes d'accord ; comparer Poisson coding à des encodeurs déterministes.

### Mapping spatial

Hypothèse : projeter une grille temps x niveaux relatifs au prix/mid sur une population sensorielle en utilisant une géométrie fixe.

Exemple initial lorsqu'un carnet existe :
- 32 pas temporels ;
- 32 niveaux relatifs ;
- 2 canaux bid/ask ou agressor buy/sell.

Pour MT5/Forex, ne pas supposer qu'un carnet Binance-like est disponible ou équivalent. L'encodeur doit gérer explicitement les capacités de chaque source.

### Normalisation causale

Préférence initiale :
- médiane glissante ;
- MAD ;
- aucune information future.

## 26.7 Reward : deux niveaux à comparer

### Reward composite général d'Alladin

```math
R_t =
\alpha R_{PnL}
+ \beta R_{decision}
+ \gamma R_{survival}
+ \delta R_{prediction}
+ \eta R_{calibration}
- \lambda P_{risk}
- \mu P_{drawdown}
- \nu P_{execution}
- \xi P_{rule}
```

### Variante financière « Sortino différentiel + drawdown »

À implémenter comme **candidat**, pas comme vérité :

```math
D_t = \tanh(r^{diff}_{Sortino,t})
      - \lambda \max(0, DD_t - DD_{seuil})
```

Le Sortino pénalise le risque baissier plutôt que toute volatilité. Une forme différentielle est intéressante pour l'apprentissage online, mais la définition exacte de `r_Sortino_diff` doit être documentée mathématiquement et testée numériquement avant utilisation.

Les deux reward families doivent être comparées contre :
- PnL net simple ;
- log-return net ;
- reward sans composante prédictive ;
- reward sans composante métabolique.

## 26.8 Signal négatif / « douleur » numérique

Le mot douleur est une métaphore fonctionnelle. Aucune sensation n'est postulée.

Forme candidate :

```math
\sigma_{noise,t} =
\sigma_0
+ k_1 DD_t
+ k_2 DownsideDeviation_t
+ k_3 ConsecutiveLosses_t
+ k_4 RulePressure_t
```

Cette quantité peut moduler un bruit contrôlé injecté dans certaines populations.

**Risque expérimental majeur** : injecter davantage de bruit après des pertes peut dégrader le réseau précisément au moment où la stabilité est nécessaire. Il faut donc comparer :
- aucun bruit métabolique ;
- bruit croissant avec stress ;
- exploration décroissante avec stress ;
- modulation des seuils plutôt que bruit.

La métaphore « le réseau fuit le désordre » reste une hypothèse à tester.

## 26.9 Énergie métabolique

État candidat :

```math
E_{t+1} = clip(E_t + G_t - L_t - C_t, 0, E_{max})
```

où :
- `G_t` = contribution positive nette ;
- `L_t` = pertes/risque réalisé ;
- `C_t` = coûts d'exécution/activité.

L'énergie peut moduler exploration, seuils ou intensité de plasticité.

`E = 0` ne doit pas directement commander l'exécution : il peut terminer l'épisode d'apprentissage, tandis que le vrai kill switch reste déterministe dans Alladin.

## 26.10 Surprise / Free-Energy-inspired

Minimum opérationnel :

```math
Surprise_t = d(\hat{x}_{t+1}, x_{t+1})
```

Objectif expérimental :

```math
J_t =
a \cdot Surprise_t
+ b \cdot Risk_t
+ c \cdot Loss_t
+ d \cdot Complexity_t
```

Le système tente de réduire `J` sans que cela remplace le reward économique ni les contraintes de risque.

L'appellation « Free Energy Principle » doit rester prudente : une simple erreur de prédiction + régularisation n'est pas automatiquement une implémentation complète du FEP.

## 26.11 Reward différé

Le crédit doit pouvoir être attribué sur plusieurs horizons.

```text
T0       décision
T+short  réaction immédiate
T+mid    MAE/MFE et changement de régime
T+close  résultat net
T+cf     contre-factuels
T+day    impact portefeuille/challenge
```

Forme initiale :

```math
R =
0.4 R_{trade}
+ 0.2 R_{decision}
+ 0.2 R_{portfolio}
+ 0.2 R_{counterfactual}
```

Les coefficients sont des valeurs de départ et doivent être optimisés uniquement sur TRAIN/VALIDATION.

## 26.12 Contre-factuels

Pour chaque opportunité, calculer si possible :

```text
chosen BUY  -> outcome BUY
counterfact -> SELL
counterfact -> HOLD

chosen HOLD -> outcome HOLD
counterfact -> BUY
counterfact -> SELL
```

Même modèle de frais, spread, slippage, latence et règles de remplissage pour toutes les branches.

Cela permet notamment de récompenser un bon NO_TRADE.

## 26.13 Essaim

Population initiale candidate : 5–10 organismes, plus contrôles.

Axes de diversité :
- pruning Core/Standard/Large ;
- seeds ;
- sous-graphes/hémisphères ;
- horizons 1 s / 5 s / 30 s / autres ;
- paramètres neuronaux ;
- historique d'apprentissage.

Vote candidat :

```math
score(a) = \sum_i q_i \; p_i(a)
```

où `q_i` est une mesure de qualité/calibration récente et `p_i(a)` la préférence de l'organisme pour l'action.

Ne pas dimensionner directement une position par consensus sans passage complet par le RiskEngine.

Mesurer continuellement la corrélation entre organismes : un essaim de clones corrélés n'apporte pas la diversité attendue.

## 26.14 Backend asynchrone cible

```text
P1 INGEST       -> flux marché / ring buffer
P2 ENCODER      -> features causales -> spikes
P3 SNN ENGINE   -> état neuronal en RAM
P4 DECISION     -> action/confidence
P5 RISK GATE    -> Alladin RiskEngine
P6 EXECUTION    -> MT5 PAPER/DEMO
P7 OUTCOME      -> conséquences et contre-factuels
P8 PERSISTENCE  -> journal/checkpoints/WAL asynchrones
```

Le chemin critique d'inférence ne doit pas dépendre d'une écriture disque synchrone non nécessaire.

Budget de latence historique proposé (à **benchmark réel**, pas promesse) :
- encodage : <2 ms ;
- SNN : 5–30 ms par organisme ;
- décision : <2 ms ;
- réseau/broker : variable et potentiellement dominant.

Ces chiffres sont des objectifs de benchmark, pas des caractéristiques garanties.

## 26.15 Persistance/WAL

À évaluer :
- snapshots complets périodiques ;
- WAL append-only des deltas de poids et états de plasticité ;
- fsync groupé ;
- restauration snapshot + replay WAL ;
- checksum et version de schéma ;
- test automatique de crash/recovery.

Technologies candidates : memmap/LMDB ou stockage équivalent, après benchmark.

## 26.16 Trading et sizing

Sortie du cerveau :

```text
target_action in {SHORT, FLAT, LONG}
confidence
optional desired_risk_signal
```

Le cerveau **ne fixe pas le lot final**.

Le sizing reste sous contrôle déterministe d'Alladin. Kelly fractionné peut être étudié comme expérience, mais n'est pas une règle par défaut et doit être plafonné par le RiskEngine.

## 26.17 Pipeline de validation complet

1. reproduire les baselines ;
2. reproduire toute référence ESN revendiquée avant de l'utiliser comme benchmark ;
3. connectome vs degree-preserving rewiring vs random reservoir ;
4. >10 seeds lorsque le coût le permet ;
5. walk-forward chronologique ;
6. purge + embargo ;
7. coûts et slippage partout ;
8. replay avec latence injectée ;
9. ablations encoding/R-STDP/metabolism/pruning ;
10. PAPER ;
11. MT5 DEMO continu pendant une durée définie à l'avance ;
12. revue humaine avant toute discussion d'un environnement réel.

Métriques additionnelles candidates :
- Deflated Sharpe lorsque les hypothèses et le nombre de trials sont correctement suivis ;
- stabilité des paramètres ;
- degradation TRAIN -> VALIDATION -> OOS ;
- tail risk ;
- time-under-water ;
- calibration action/confidence ;
- reward hacking indicators.

## 26.18 Référence ESN historique : statut NON VÉRIFIÉ

Le concept initial mentionnait une expérience « ESN Flywire Strategy » avec environ 7 500 neurones / 323 000 connexions et les performances suivantes :
- Random Forest : +3,62 % ;
- ESN recâblé : +3,78 % ;
- ESN connectome : +4,32 % ;
- leak rate 0,7 ;
- input gain 0,12 ;
- tanh.

**Ne pas utiliser ces nombres comme faits tant que la publication/repository exact, dataset, période, frais, splits et code n'ont pas été retrouvés et reproduits.**

Ils sont conservés ici uniquement pour ne pas perdre l'origine du raisonnement.

## 26.19 Sources scientifiques vérifiées au 2026-10-02

- Janelia MaleCNS media/dataset documentation : 166 700 neurons, 11 710 neuron types; collaboration FlyEM/Janelia, Cambridge, MRC LMB, Google Research.
- Frémaux & Gerstner, *Neuromodulated Spike-Timing-Dependent Plasticity, and Theory of Three-Factor Learning Rules*, Frontiers in Neural Circuits (2016): R-STDP, eligibility traces and delayed third-factor modulation.
- Gerstner et al./review literature on eligibility traces: eligibility traces bridge the temporal gap between neural activity and delayed reward/modulatory signals.
- Financial RL literature: downside-risk/Sortino-family rewards are legitimate experimental reward-shaping candidates, but implementation details materially affect results.

## 26.20 Principe final de cette spécification

Les métaphores biologiques servent à générer des mécanismes testables. Elles ne remplacent jamais les contrôles.

Pour chaque mécanisme M :

```text
baseline
vs
baseline + M
-> same data
-> same costs
-> same splits
-> multiple seeds
-> OOS comparison
```

Si `M` n'apporte pas de bénéfice robuste, il est retiré même s'il est biologiquement séduisant.


## Extension SNN-X adoptée le 2026-10-04

Les décisions 024–029 du registre `docs/DECISIONS/` complètent ce document sans le remplacer : modules optionnels et ablations, FAST/SLOW, surveillance BTC continue, objectif sous contraintes, Shadow Brain et Dream Engine. Voir `docs/HANDOFF.md` pour la reprise Claude. Architecture cible adoptée, non implémentée par cet ajout ; préserver les travaux en cours et gates de recette. Les variantes de reward et la plasticité restent expérimentales ; aucun accès direct du Brain à l’exécution, aucune auto-promotion.
