# Règles de challenge

Profil : `config/challenge_profiles/ftmo_2step_demo.yaml` (modèle `ChallengeProfile`). Quatre blocs :

| Bloc | Contenu | Source dans les violations |
|---|---|---|
| `official_rules` | perte journalière 5 %, perte totale 10 %, 4 jours de trading min, référence journalière, fuseau de reset | `official` |
| `extra_rules` | 14 jours max par phase, blocage souple à 3 %/jour, consistency (Best Day ≤ 50 %), flat pour valider | `extra` (ALLADIN, non FTMO) |
| `risk` | enveloppe de travail et plafonds du RiskEngine | — |
| `universe` | catégories autorisées, inclusions/exclusions, spread/ATR max, taille de shortlist | — |

`phases`: Phase 1 +10 %, Phase 2 +5 %. Solde de départ : celui du compte DEMO à la création du run (les pourcentages s'y appliquent). Chaque phase repart d'une **nouvelle base** (solde à la validation).

⚠ Les valeurs « officielles » sont une modélisation de travail du programme FTMO à vérifier contre les règles en vigueur ; elles sont volontairement dans le YAML.

## États du run

`CREATED → READY → RUNNING → TARGET_REACHED → PASSED`, plus `PAUSED` (reprenable), `FAILED`, `KILLED`.
`PASSED`, `FAILED`, `KILLED` sont **terminaux et irréversibles** : en mémoire (`IrreversibleStateError`) et en base (trigger). Un nouveau run doit être créé ; les anciens ne sont jamais réécrits.

## Évaluation (à chaque synchronisation, sur l'equity réelle du compte)

1. `equity ≤ plancher journalier` (référence `max(solde, equity)` au début du jour − 5 % de la base) ⇒ **FAILED** `max_daily_loss`.
2. `equity ≤ base − 10 %` ⇒ **FAILED** `max_total_loss`.
3. Objectif atteint (solde par défaut, `target_measured_on`) ⇒ `TARGET_REACHED`. Passage si : jours de trading ≥ minimum, consistency respectée (si activée), aucune position ouverte (si `require_flat_to_pass`). Phase 1 → Phase 2 ; dernière phase → `PASSED`.
4. Durée de phase ≥ `max_days_per_phase` ⇒ **FAILED** `max_days_per_phase` (règle ALLADIN).
5. Perte journalière ≥ seuil souple ⇒ nouveaux ordres bloqués jusqu'au lendemain (non éliminatoire).

Conséquence d'un FAILED : nouveaux ordres bloqués immédiatement, violation journalisée, fermeture contrôlée optionnelle (`close_positions_on_fail`), reprise impossible.

Limites : le « jour » démarre au premier snapshot de la journée (pas exactement à minuit si ALLADIN ne tourne pas) ; le `swap`/commissions sont comptés via les deals clôturés.
