# Agents (Claude / Codex / Mock)

`AgentAdapter.propose(AgentRequest) → AgentResponse`. Aucune clé API Anthropic/OpenAI n'est requise ni lue.

| Adapter | Mécanisme |
|---|---|
| `MockAgent` | déterministe (meilleur signal de stratégie, ou NO_TRADE) ; accepte un script pour les tests |
| `ClaudeAdapter` | `claude -p --output-format json --tools "" --no-session-persistence --max-turns 1`, prompt sur stdin |
| `CodexAdapter` | `codex exec --sandbox read-only --ephemeral --skip-git-repo-check -o <fichier> -` |

Ils s'appuient sur la **session déjà connectée** des CLI locaux (abonnement). Si elle est absente ou expirée, la réponse contient une erreur explicite et le cycle devient NO TRADE. Aucun scraping d'interface web.

## Ce que voit l'agent

Shortlist (régime, score, métriques), signaux des stratégies, enveloppe de risque chiffrée, catalogue de stratégies. **Jamais** : identifiants MT5, `.env`, broker. Environnement du sous-processus assaini par liste blanche ; répertoire de travail temporaire vide.

## Ce que l'agent peut répondre

```json
{"decision":"TRADE|NO_TRADE","reason":"...","intent":{"instrument":"GBPJPY","side":"BUY","strategy_id":"TREND-01",
 "strategy_version":"1.0.0","market_regime":"TREND","entry_type":"MARKET","entry":211.9,"stop_loss":211.3,
 "take_profit":213.1,"requested_risk_pct_of_working_capital":4.5,"confidence":0.76,"reason":"...","sources":[]}}
```
Champs inconnus (dont `volume`) ⇒ réponse invalide. L'instrument doit appartenir à la shortlist scannée ; la stratégie et sa version doivent exister et être actives. Puis RiskEngine : les chiffres de l'agent ne sont jamais crus.

## Limites

- Latence/coût en quota d'abonnement : un appel par cycle.
- Sorties non déterministes ; tout est journalisé (`agent.request`, `agent.response`).
- Les options exactes des CLI évoluent : adapters isolés dans `agents/claude.py` et `agents/codex.py`.
