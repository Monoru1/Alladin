# DECISION-023 — Outcomes audités et reward expérimental versionné

**Date :** 2026-10-04 (Europe/Paris)  
**Statut :** ADOPTED pour le contrat de données ; coefficients de reward EXPERIMENTAL.

## Contexte
Le lot J implémente la fondation Outcome/Reward après les lots F à I. Les décisions 017, 018 et 020 imposent des données traçables, une économie explicite et une séparation entre production et apprentissage. Cette fiche précise ces décisions sans les remplacer.

## Décision
1. Capturer les résultats uniquement après clôture PAPER/DEMO, sous forme de snapshots immuables liés au workspace, run, source et hash de politique. Snapshot et preuve journalisée sont insérés atomiquement ; une reprise ne crée pas de doublon et une source clôturée modifiée est signalée.
2. Conserver risque initial et conversion monétaire d'ouverture, décomposition du PnL, durée et excursions monétaires échantillonnées incluant les réalisations partielles. Les coûts DEMO sont rapportés par le broker ; les coûts PAPER sont explicitement modélisés.
3. Distinguer absence d'information et zéro. Données nécessaires absentes ou position adoptée sans risque initial fiable : résultat INCOMPLETE, sans reward d'apprentissage inventé.
4. Versionner et exposer les composantes du reward. La politique initiale expérimentale est `net_R + 0.1 * protection_quality - 0.25 * sampled_MAE_R`, bornée à ±5. Le proxy de qualité mesure la protection initiale et les retraits de SL observés ; il ne mesure pas une qualité prédictive calibrée. Les coefficients ne constituent pas un objectif optimisé ni une règle de trading.
5. Limiter les contrefactuels disponibles à NO_TRADE sans exposition et HOLD brut au prix/temps de sortie final réel, avec conversion d'ouverture figée. Ce HOLD est une comparaison rétrospective modélisée ; frais/financement alternatifs et trajectoires SL/TP ne sont pas inventés.
6. Collecter après le cycle ou hors connexion, consulter par API GET/CLI/cockpit et séparer les agrégats par mode, devise et hash de politique. Une erreur de recherche ne change ni l'exécution ni le Brain actif. Entraînement et promotion relèvent de la décision 020 et du travail suivant.

## Raisonnement
L'apprentissage futur doit reposer sur une conséquence identifiable et reproductible. Réécrire une observation, mélanger simulation et coûts réels, remplacer une donnée absente par zéro ou présenter un contrefactuel limité comme vérité de marché rendrait les expériences trompeuses.

## Invariants
- Isolation workspace/run et compte broker lié avant synchronisation.
- Reward dérivable des données et de la politique conservées, sans mutation rétroactive.
- Aucune auto-promotion ni modification des poids actifs par OutcomeEngine.
- MAE/MFE annoncées comme échantillonnées, sans prétendre mesurer les extrema continus.
- OBSERVE ne fabrique pas de résultat de trade ; Jafar reste OBSERVE uniquement.

## Conséquences
Le lot K peut exploiter cette fondation pour des expériences reproductibles. Les anciens trades incomplets restent consultables sans devenir artificiellement éligibles. Une nouvelle politique conserve ses propres snapshots sans écraser l'historique.

## Questions ouvertes
Calibration des coefficients et du proxy de qualité ; contrefactuels causaux sur trajectoires archivées ; couverture des extrema intracycle ; coûts crypto réels ; attribution journalière des réalisations partielles interjours ; validation OOS et lutte contre reward hacking.

## Conditions de révision
Réviser par une nouvelle décision si les expériences invalident le proxy/reward, si de meilleures données permettent des contrefactuels complets ou si le contrat d'éligibilité change. Les résultats d'une politique précédente restent conservés. Les validations logicielles ne remplacent pas la recette du terminal MT5 réel.

## Documents/code concernés
`src/alladin/research/outcomes.py`, `config/reward_policies/outcome_v1.yaml`, journal/repository, monitor, PAPER, API/CLI/cockpit, `tests/test_outcomes.py`, `docs/PC_ACCEPTANCE.md`, HANDOFF et IMPLEMENTATION_PLAN.
