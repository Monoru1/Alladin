# ALLADIN SNN — FONCTIONNEMENT DE LA « MOUCHE »

**Statut : document de fonctionnement — complément de la Bible SNN**  
**Créé : 2026-10-02**  
**But : expliquer comment la biologie de Drosophila inspire concrètement le moteur de décision SNN d'Alladin, du flux marché jusqu'à l'apprentissage.**

> La « mouche » est un organisme logiciel inspiré d'un connectome réel. Elle n'est ni une simulation complète d'une drosophile vivante, ni un cerveau conscient. Chaque analogie biologique doit produire un mécanisme informatique testable.

## 1. Pourquoi une mouche ?

Le projet part d'une propriété intéressante de Drosophila : un système nerveux compact réalise perception, mémoire, apprentissage, orientation et sélection d'actions avec des circuits récurrents très structurés.

MaleCNS fournit un graphe anatomique réel. La version 1.0 couvre le cerveau, les lobes optiques et le cordon nerveux ventral. La documentation Janelia indique 166 700 neurones et 11 710 types neuronaux.

Alladin ne suppose pas que cette topologie est meilleure pour le trading. Il teste l'hypothèse.

## 2. Ce que fait réellement la mouche biologique et ce que nous transposons

### 2.1 Mushroom Body (MB)

**Biologie établie :** le Mushroom Body joue un rôle majeur dans l'apprentissage et la mémoire chez Drosophila. Les Kenyon cells forment des représentations sensorielles clairsemées ; les sorties MBON et la modulation dopaminergique participent à l'apprentissage de valence.

**Transposition Alladin — hypothèse :**
- Kenyon cells -> expansion sparse du contexte de marché ;
- DAN -> signal modulateur reward/punishment ;
- MBON -> préférences comportementales/action ;
- plasticité KC->MBON -> association contexte / conséquence.

Nous ne disons pas « MB = détecteur de régime » comme fait biologique. Nous testons si ce circuit peut devenir un détecteur de contexte/régime lorsqu'il reçoit des données financières.

### 2.2 Central Complex (CX)

**Biologie établie :** le CX contient des circuits de navigation. Des populations du système de direction forment une dynamique de type ring attractor ; une bosse d'activité représente et maintient une direction et se met à jour avec les mouvements et indices sensoriels.

**Transposition Alladin — hypothèse :**
- direction physique -> direction/état latent du marché ;
- bump persistant -> conviction/persistance d'état ;
- changement de cap -> changement de régime/tendance ;
- inertie de l'attracteur -> hystérésis contre le flip LONG/SHORT permanent ;
- comparaison cap/but -> comparaison état marché / objectif-risque.

Le CX n'est donc pas déclaré « module de tendance ». Sa dynamique est utilisée comme primitive de mémoire directionnelle à tester.

### 2.3 Voies sensorielles

La mouche transforme des stimuli en événements neuronaux. Alladin remplace les capteurs biologiques par des capteurs financiers.

```text
BIOLOGIE                 ALLADIN
vision             ->    prix / returns / structure
mouvement          ->    vitesse / accélération du prix
contraste          ->    rupture / surprise
intensité          ->    volume / tick activity
contexte           ->    session / volatilité / spread
état interne       ->    capital / risque / challenge
```

## 3. La chaîne complète d'une décision

```text
BROKER / MARKET DATA
        |
        v
[1] NORMALISATION CAUSALE
        |
        v
[2] ENCODAGE SENSORIEL EN SPIKES
        |
        v
[3] PROPAGATION DANS LE SNN
        |
        +--> MB : contexte / associations apprises
        |
        +--> CX : état récurrent / persistance
        |
        v
[4] POPULATIONS DE SORTIE
     LONG / SHORT / FLAT
        |
        v
[5] READOUT + CONFIDENCE
        |
        v
[6] TRADE INTENT
        |
        v
[7] ALLADIN RISK ENGINE
        |
   reject | accept
        |     |
        |     v
        |   PAPER / MT5 DEMO
        |     |
        +-----+
              v
[8] OUTCOME ENGINE
              |
       +------+-------+----------+
       |              |          |
     reward         stress     surprise
       |              |          |
       +--------------+----------+
                      |
                    R-STDP
                      |
              poids synaptiques
                      |
              prochaine décision
```

Le RiskEngine est hors du cerveau. Il reste déterministe.

## 4. Comment le marché devient des spikes

### 4.1 Event coding

Exemple :

```text
return franchit +delta -> spike ON
return franchit -delta -> spike OFF
volatilité explose     -> burst
spread s'élargit       -> population SPREAD_HIGH
```

`delta` doit être relatif à l'instrument, par exemple en ATR/ticks/volatilité.

### 4.2 Rate coding

Une variable continue active une population selon son amplitude.

Exemple : volatilité normalisée distribuée sur 16–32 neurones à courbes d'accord.

### 4.3 Normalisation

Le même cerveau doit pouvoir recevoir EURUSD, GBPJPY, BTC ou un CFD sans apprendre que « 50 » signifie la même chose partout.

On privilégie donc :
- returns ;
- z-score causal robuste ;
- médiane/MAD ;
- ATR ;
- spread/ATR ;
- tick-value/tick-size dans la couche de risque ;
- features relatives plutôt qu'absolues.

## 5. Le neurone

Baseline : Leaky Integrate-and-Fire.

Forme conceptuelle :

```math
\tau_m \frac{dV}{dt} = -(V - V_{rest}) + R I(t)
```

Quand `V >= V_threshold` :
1. émission d'un spike ;
2. reset du potentiel ;
3. période réfractaire éventuelle.

AdEx sera un contrôle plus riche, pas le choix automatique.

## 6. Les synapses

Initialisation candidate :

```math
w_{ij}(0) = g \cdot N_{syn,ij} \cdot s_{ij}
```

avec `N_syn` le nombre de synapses anatomiques et `s` le signe excitateur/inhibiteur lorsque l'annotation permet de l'inférer proprement.

Le connectome fournit la topologie. L'apprentissage modifie seulement les synapses autorisées par le protocole.

## 7. STDP et mémoire locale

Une synapse mémorise la proximité temporelle des spikes pré/post.

```text
pre -> post : contribution de potentiation
post -> pre : contribution de dépression
```

Une forme classique de fenêtre est :

```math
W(\Delta t) =
\begin{cases}
A_+ e^{-\Delta t/\tau_+}, & \Delta t > 0 \\
-A_- e^{\Delta t/\tau_-}, & \Delta t < 0
\end{cases}
```

Ce n'est pas encore le reward.

## 8. R-STDP : comment une conséquence future revient aux synapses

La trace d'éligibilité conserve temporairement l'empreinte de la co-activité :

```math
\dot e_{ij} =
-\frac{e_{ij}}{\tau_e}
+ STDP(pre_i, post_j)
```

Puis :

```math
\Delta w_{ij}(t) = \eta D(t)e_{ij}(t)
```

C'est essentiel pour le trading : la conséquence d'une décision arrive souvent longtemps après les spikes qui l'ont produite.

La littérature sur les règles à trois facteurs décrit précisément les eligibility traces comme un mécanisme reliant activité synaptique et récompense retardée.

## 9. Le reward n'est pas le PnL

Reward général :

```math
R_t =
\alpha R_{PnL}
+\beta R_{decision}
+\gamma R_{survival}
+\delta R_{prediction}
+\eta R_{calibration}
-\lambda P_{risk}
-\mu P_{drawdown}
-\nu P_{execution}
-\xi P_{rule}
```

Donc :
- gain chanceux + comportement dangereux != excellente décision ;
- perte propre et contrôlée != décision catastrophique ;
- bon NO_TRADE peut être récompensé ;
- proximité d'une limite de challenge peut coûter cher même avant l'échec.

Variante à tester :

```math
D_t =
\tanh(r^{diff}_{Sortino,t})
-\lambda \max(0,DD_t-DD_{seuil})
```

## 10. État métabolique

```math
M_t=(E_t,S_t,U_t,H_t,C_t)
```

où :
- `E` = énergie/capital de survie ;
- `S` = stress ;
- `U` = surprise ;
- `H` = pression liée à l'objectif ;
- `C` = confiance/calibration.

Énergie candidate :

```math
E_{t+1}=clip(E_t+G_t-L_t-Cost_t,0,E_{max})
```

Bruit/stress candidat :

```math
\sigma_t =
\sigma_0
+k_1DD_t
+k_2DownsideDev_t
+k_3ConsecutiveLosses_t
+k_4RulePressure_t
```

Attention : davantage de stress ne doit pas nécessairement produire davantage de bruit. Nous testerons aussi l'inverse : stress élevé -> exploration réduite / seuil d'action plus élevé.

## 11. Surprise

```math
U_t=d(\hat{x}_{t+1},x_{t+1})
```

La mouche formule implicitement ou explicitement une attente sur l'état futur. L'écart devient un signal d'apprentissage.

Une formulation free-energy-inspired candidate :

```math
J_t =
aU_t+bRisk_t+cLoss_t+dComplexity_t
```

Nous ne prétendons pas qu'une telle fonction est à elle seule le Free Energy Principle biologique.

## 12. NO_TRADE : comportement biologique d'abstention

Les sorties sont :

```text
LONG
SHORT
FLAT / NO_TRADE
```

NO_TRADE n'est pas une absence de réponse. C'est une action.

Après coup :

```text
choix réel : HOLD
si BUY  -> ?
si SELL -> ?
si HOLD -> résultat réel
```

Le replay permet donc d'apprendre qu'une abstention était parfois la meilleure décision.

## 13. Une décision n'est pas jugée une seule fois

```text
T0       décision
T+court  réaction
T+moyen  MAE/MFE
T+close  résultat net
T+cf     contre-factuels
T+jour   conséquence portefeuille/challenge
```

Reward candidat :

```math
R =
0.4R_{trade}
+0.2R_{decision}
+0.2R_{portfolio}
+0.2R_{counterfactual}
```

Ces coefficients sont expérimentaux.

## 14. La mouche multi-instruments

L'objectif n'est pas « une mouche BTC ».

Architecture :

```text
Market Adapter
  +-- MT5
  +-- Binance (futur)
  +-- Deriv (futur)
  +-- Exness / autre broker compatible (futur)
          |
          v
Canonical Market Event
          |
          v
Normalizer
          |
          v
Spike Encoder
          |
          v
SNN
```

Le cerveau ne doit pas dépendre du protocole d'un broker.

Un événement canonique peut contenir :
- instrument ;
- timestamp ;
- bid/ask ;
- last si disponible ;
- volume/tick volume ;
- profondeur si disponible ;
- session/source ;
- qualité/fraîcheur des données.

Chaque adapter annonce ses capacités. Un encodeur ne doit jamais inventer un order book si la source n'en fournit pas.

## 15. La mouche n'exécute pas directement

Sortie cerveau :

```text
ActionProposal {
  instrument,
  action,
  confidence,
  horizon,
  optional desired_risk_signal,
  brain_version,
  state_id
}
```

Puis :

```text
ActionProposal
 -> Opportunity / TradeIntent
 -> ChallengeWatchdog
 -> RiskEngine
 -> PositionSizer
 -> BrokerAdapter
 -> Execution
```

Le lot final appartient à Alladin, jamais au SNN.

## 16. Essaim

Une seule mouche peut sur-apprendre. Nous testerons plusieurs organismes.

```text
Fly A --+
Fly B --+
Fly C --+--> Meta decision --> RiskEngine
Fly D --+
Control-+
```

Diversité :
- topologie/pruning ;
- seed ;
- horizon ;
- historique ;
- paramètres ;
- instruments/régimes spécialisés.

Score candidat :

```math
Score(a)=\sum_i q_i p_i(a)
```

avec `q_i` fondé sur calibration/performance récente, jamais sur un unique trade.

## 17. « Sélection naturelle »

Dans le laboratoire uniquement :

```text
population
 -> épisodes/challenges
 -> mesure OOS
 -> élimination/archivage des mauvais candidats
 -> mutation contrôlée
 -> nouvelle génération
```

Un organisme « mort » signifie simplement qu'une expérience est terminée. Les résultats négatifs restent archivés.

## 18. Fonctionnement H24

Le serveur H24 sert à accumuler **des observations et des expériences**, pas à garantir des profits.

Services conceptuels :

```text
ingest
encoder
brain workers
decision service
risk gateway
execution gateway
outcome worker
reward worker
checkpoint service
experiment registry
metrics/alerts
```

Exigences :
- heartbeat ;
- watchdog ;
- données périmées -> aucune nouvelle action ;
- crash brain -> aucune action par défaut ;
- checkpoint versionné ;
- journal append-only ;
- redémarrage déterministe autant que possible ;
- shadow mode ;
- métriques spikes/latence/reward/drawdown/calibration.

## 19. Linux + MT5 + brokers futurs

Le cerveau est portable.

```text
LINUX BRAIN SERVER
  ingestion / archive
  encoding
  SNN
  learning
  replay
  checkpoints
       |
       | authenticated intents/outcomes
       v
EXECUTION NODE(S)
  MT5 / broker adapter
  deterministic risk
  position monitor
```

On peut ensuite brancher d'autres adapters sans réentraîner le cerveau uniquement parce que le protocole d'exécution change. En revanche, différences de microstructure, coûts et données peuvent nécessiter recalibration ou apprentissage spécifique.

## 20. Pas besoin d'un LLM pour faire tourner la mouche

Le runtime cible ne dépend pas de Claude, Codex ou d'un autre LLM.

Il a besoin de :
- données ;
- calcul numérique ;
- moteur SNN ;
- état ;
- reward ;
- replay ;
- risk ;
- exécution ;
- observabilité.

Les IA génératives servent au développement, à l'audit, à l'analyse et à la recherche. Elles ne sont pas une dépendance du chemin critique.

Cela réduit coût, latence, non-déterminisme et dépendance externe.

## 21. Ce qu'il faut absolument démontrer

Avant de dire que « la mouche fonctionne » :

1. connectome > contrôles de graphes sur plusieurs seeds ;
2. SNN > baselines simples de façon robuste OOS ;
3. R-STDP > SNN gelé ;
4. reward composite > reward naïf ou apporte un avantage clair ;
5. métabolisme > version sans métabolisme ;
6. essaim > meilleur individu/ensemble simple ;
7. multi-instruments ne détruit pas la généralisation ;
8. coûts/slippage ne détruisent pas l'edge ;
9. le système ne reward-hack pas ;
10. le RiskEngine reste respecté à 100 %.

## 22. Sources scientifiques et techniques

Sources utilisées pour séparer faits biologiques et analogies d'ingénierie :

- Janelia MaleCNS Connectome, v1.0 : connectome complet du CNS mâle, accès neuPrint/neuprint-python, 166 700 neurones et 11 710 types.
- Heisenberg, *Mushroom body memoir: from maps to models*, Nature Reviews Neuroscience (2003) : rôle du Mushroom Body dans apprentissage/mémoire.
- littérature KC/MBON/DAN : modulation dopaminergique des synapses de sortie du Mushroom Body dans l'apprentissage de valence.
- Hulse et al., *A connectome of the Drosophila central complex reveals network motifs suitable for flexible navigation and context-dependent action selection*, eLife (2021/2022).
- Seelig & Jayaraman, *Neural dynamics for landmark orientation and angular path integration*, Nature (2015).
- Green et al., *A neural circuit architecture for angular integration in Drosophila*, Nature (2017).
- Pisokas et al., *The head direction circuit of two insect species*, eLife (2020).
- Frémaux & Gerstner, *Neuromodulated Spike-Timing-Dependent Plasticity, and Theory of Three-Factor Learning Rules*, Frontiers in Neural Circuits (2016).
- Gerstner et al., *Eligibility Traces and Plasticity on Behavioral Time Scales*, Frontiers in Neural Circuits (2018).

## 23. Résumé opérationnel

La mouche Alladin est donc :

```text
un connectome
+ une dynamique spiking
+ des capteurs financiers normalisés
+ une mémoire récurrente
+ une plasticité locale
+ une trace d'éligibilité
+ un signal global de conséquence
+ un état métabolique
+ une capacité d'abstention
+ un replay contrefactuel
+ des garde-fous déterministes externes
```

Le cœur scientifique du projet est de découvrir si cet ensemble apprend réellement quelque chose que des architectures plus simples n'apprennent pas aussi bien.

Si la réponse est non, Alladin doit être capable de le démontrer et de retirer le mécanisme inutile.
