# Calendriers publics — adaptateurs de recherche

Les URLs fixes BLS iCalendar et BEA iCalendar/JSON sont téléchargées uniquement sur appel explicite de `fetch_public_calendar`. Aucun appel réseau au démarrage du runtime, aucun identifiant ni abonnement demandé par ces adaptateurs. Références éditeur :

- https://www.bls.gov/schedule/news_release/bls.ics
- https://www.bls.gov/schedule/news_release/icalendar.htm
- https://www.bea.gov/news/schedule
- https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics
- https://apps.bea.gov/API/signup/release_dates.json

La réutilisation et les conditions des éditeurs doivent être vérifiées avant production. Ces horaires de publications américaines ne constituent pas un calendrier mondial complet ; aucun consensus, valeur réalisée ni mapping contractuel de firme n'est inféré. FOMC, banques centrales étrangères, jours fériés et marchés non couverts nécessitent d'autres sources validées.

Contrat : document complet UTF-8 borné à 2 Mo, hash SHA-256, URL d'origine fixe, heure UTC de réception comme première disponibilité prouvée, TTL explicite. Les redirections sont refusées. `DTSTAMP` et `file_last_updated` ne servent jamais à avancer artificiellement la disponibilité. ICS : UID stable et SEQUENCE ; heure UTC ou TZID IANA/US-Eastern, pliage de lignes ; heure DST ambiguë/inexistante, all-day, récurrence et annulation non prises en charge sont rejetées. JSON BEA : doublons de dates supprimés ; IDs dérivés titre/date UTC (un report sur un autre jour change l'ID). Préserver les documents reçus pour reconstruire les reports/cancellations, pas seulement les événements parsés.

Chaque batch est `coverage_complete=False`. PolicyGate bloque OPEN et demande REVIEW pour la gestion transactionnelle lorsque cette couverture est incomplète. HOLD sans transaction garde son comportement existant. Compléter et certifier la couverture exige un collecteur/composite distinct ; ne pas transformer automatiquement un calendrier partiel en `True`. Les archives legacy gardent `None` pour compatibilité : ce champ ne certifie pas leur couverture.

Le contrôleur `orchestration/policy_control.py` est injecté explicitement dans `Components.engine(..., policy_controller=...)`, uniquement OBSERVE/PAPER. Le provider doit fournir des snapshots causaux complets et liés au compte/symbole/instant de la proposition. Aucune activation par configuration globale ni admission réelle de firme. RiskEngine et vérifications de position restent exécutés ensuite. Les SL/TP PAPER automatiques restent actifs avant les propositions ; le contrôleur n'annule jamais une protection native. Leur conformité contractuelle/endurance reste à valider.

Le journal conserve `policy.decision` et `policy.incident`. Même proposition/même preuve : pas de doublon ; identité rejouée avec preuve différente : incident et refus. Le journal n'est pas une réservation atomique d'exposition entre plusieurs processus/comptes. GET `/api/policy` expose verdicts/refus/données indisponibles/incidents/intégrité. Le taux porte sur les décisions observées ; la disponibilité temporelle reste inconnue. Aucun indicateur n'autorise l'exécution.
