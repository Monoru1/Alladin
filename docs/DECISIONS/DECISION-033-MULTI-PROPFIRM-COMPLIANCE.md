# DECISION-033 — Moteur multi-prop-firm et conformité par compte
- Date : 2026-10-08
- Statut : ADOPTED (architecture) ; PLANNED (intégrations)

## Contexte
La réussite chez une firme ne garantit ni compatibilité des règles ni droit à l'automatisation chez une autre. Plusieurs comptes ne doivent pas créer de positions interdites ou de contournements.

## Décision
1. Créer une abstraction FirmProfile versionnée par firme, produit, phase (evaluation/verification/funded), type de compte, devise et date d'effet ; lier chaque profil à une source officielle vérifiable et à une date de dernière vérification.
2. Représenter séparément objectifs, perte quotidienne (base de calcul/heure de reset), drawdown statique ou trailing, perte maximale, règles de cohérence/best day, trading minimum, annonces, week-end/overnight, EA/API, copy trading, plafonds par trader/stratégie, symboles, frais et conditions de récompense.
3. ComplianceGate validera chaque proposition ET les actions de gestion de position selon les capacités réelles du broker, les conditions de la firme et les corrélations entre tous les comptes pilotés. Priorité aux mesures de protection autorisées.
4. Les comptes multi-firmes partageront un registre d'exposition et un registre de provenance des décisions. Interdire hedging inter-comptes destiné à contourner les règles, réplication non autorisée et découpage artificiel des stratégies ou identités.
5. Profil manquant, règle contradictoire, expirée ou non vérifiée : aucune nouvelle exposition sur le compte concerné. Les règles doivent pouvoir être revalidées indépendamment du déploiement de code.
6. Chaque firme sera admise seulement après revue officielle des contrats, test PAPER/DEMO des restrictions, capacités et procédure de récompense. Ne pas affirmer le support d'une firme tant que l'adapter n'est pas testé.
7. Journaliser chaque décision avec version du profil, source, compliance verdict et raison ; versionner les changements et enregistrer les exceptions humaines sans leur permettre de désactiver les protections fondamentales.

## Raisonnement
Une stratégie multi-firmes résiliente nécessite une séparation entre génération de signal, restrictions de chaque compte et risque portefeuille transversal.

## Invariants
Pas de contournement des plafonds/allocation, d'usage interdit d'EA/API ni de comptes prête-nom. Toute activation à enjeux financiers demande une autorisation humaine explicite.

## Questions ouvertes
Firmes candidates et clauses applicables, nature juridique des versements, plafonds agrégés et compatibilité des infrastructures de trading.

## Conditions de révision
Changement contractuel, incapacité de vérifier une règle, incident de conformité ou résultat de test.

## Documents et code concernés
DECISION-003, 004, 013, 015, 031, 032 ; challenge/, brokers/, risk/, execution/, journal/.
