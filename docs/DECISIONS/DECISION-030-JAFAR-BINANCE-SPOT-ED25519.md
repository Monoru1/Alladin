# DECISION-030 — Binance Spot natif pour Jafar et gestion locale des credentials

- **Date :** 2026-10-04
- **Statut :** ADOPTED
- **Workspace :** JAFAR

## Contexte

Jafar dispose désormais d'un compte Binance vérifié et d'une API Binance Spot Ed25519 créée sous le label `JAFAR-BINANCE`.

Le 2026-10-04, un appel signé réel en lecture seule vers `GET /api/v3/account` a retourné **HTTP 200** depuis le poste utilisateur. Cela valide la chaîne d'authentification réelle API Key + signature Ed25519 vers Binance. Le test n'a envoyé aucun ordre.

Au moment de cette validation, la clé API Binance a uniquement **Enable Reading** activé. Les permissions Spot/Margin trading, transferts, retraits, margin loan/repay/transfer, prediction, Alpha withdrawals et FIX ne sont pas activées.

## Décision

1. Binance Spot devient le premier adapter exchange natif réel de Jafar.
2. Jafar est conçu pour travailler sur **l'univers crypto disponible et éligible**, et non uniquement BTC/USDT. L'univers doit être découvert dynamiquement depuis l'exchange puis filtré par capabilities, liquidité, qualité des données, contraintes de marché et RiskEngine ; aucune liste fixe de quelques cryptos ne doit définir son identité.
3. Jafar doit réutiliser le core partagé Alladin/Jafar et respecter la chaîne `Brain -> ActionProposal -> Risk -> Execution -> Broker/Exchange`. Il ne doit pas créer un moteur parallèle contournant le RiskEngine.
4. L'intégration doit distinguer au minimum :
   - données publiques Spot ;
   - compte authentifié/read-only ;
   - exécution Spot, qui reste verrouillée tant que ses gates et tests ne sont pas validés.
5. Les credentials ne sont jamais stockés dans Git :
   - **API key Binance** : variable d'environnement `BINANCE_API_KEY` sur le runtime ;
   - **clé privée Ed25519** : fichier local Windows `%USERPROFILE%\.ssh\jafar_binance_private.pem` ;
   - **clé publique Ed25519** : fichier local `%USERPROFILE%\.ssh\jafar_binance_public.pem`, enregistré côté Binance ;
   - le repository ne contient que les noms/emplacements attendus, jamais leurs valeurs.
6. Les retraits doivent rester désactivés. L'activation future du trading Spot nécessite une étape explicite, testée et documentée ; elle ne doit pas être activée implicitement par du code.
7. La restriction IP doit être traitée avant une mise en service LIVE lorsque l'infrastructure d'exécution stable est connue.
8. Les modes et garde-fous existants restent applicables. Une capacité Binance disponible ne vaut pas autorisation Jafar de l'utiliser.

## Preuve actuelle

Validation manuelle réelle, 2026-10-04 :

```text
GET /api/v3/account
HTTP: 200
Connection: OK
```

La réponse indiquait `canTrade=True`, `canWithdraw=True`, `canDeposit=True` au niveau du compte. Ces champs ne doivent pas être interprétés comme les permissions de la clé API : la clé `JAFAR-BINANCE` reste configurée read-only au moment de la décision.

Aucune balance non nulle n'a été remontée par ce test et aucun ordre n'a été créé.

## Configuration runtime attendue

```text
BINANCE_API_KEY=<valeur locale, jamais commitée>
JAFAR_BINANCE_PRIVATE_KEY_PATH=%USERPROFILE%\.ssh\jafar_binance_private.pem
```

Le code doit permettre de configurer le chemin plutôt que de dépendre silencieusement d'un chemin codé en dur. Le chemin ci-dessus est la valeur locale actuelle/documentée pour gagner du temps lors des reprises.

## Sécurité repository

Les fichiers `*.pem` doivent être ignorés par Git en plus des règles existantes `.env` / `.env.*`. Aucun agent Claude/Codex/ChatGPT ne doit demander, afficher, logger ou committer la clé privée ou la valeur de `BINANCE_API_KEY`.

## Prochaines étapes

- intégrer un adapter Binance authentifié read-only dans le workspace Jafar ;
- conserver `crypto-public` comme source publique et ne pas confondre données publiques et compte authentifié ;
- tester exchange info, ticker/order book/streams et lecture du compte ;
- ajouter journalisation, erreurs de signature/horloge/rate-limit et tests ;
- construire l'exécution Spot derrière les gates Risk/Execution existants ;
- utiliser testnet/PAPER avant toute permission de trading réelle ;
- **mettre à jour explicitement les restrictions de la clé API Binance pour autoriser Spot trading** au moment du passage aux tests d'ordres authentifiés ; tant que cette permission n'est pas activée côté Binance, Jafar ne pourra pas envoyer d'ordres réels ;
- après activation, vérifier par test contrôlé que création/annulation/lecture d'ordre fonctionnent derrière RiskEngine/Execution avant toute autonomie ;
- activer le trading Spot réel seulement par décision explicite après validation ;
- ne jamais activer les retraits.

## Conditions de révision

Cette décision peut être supersédée si Binance n'est plus l'exchange cible, si le modèle d'authentification change, ou si l'architecture multi-exchange impose une abstraction différente. Les invariants de séparation des secrets, RiskEngine, auditabilité et fail-closed restent obligatoires.
