"""ResearchPerformanceProvider : branche les resultats valides du ResearchRepository
dans le StrategyRouter sans creer de feedback circulaire.

Priorite :
1. DEMO_FORWARD si disponible
2. OUT_OF_SAMPLE valide
3. Rien (neutre) -- TRAIN seul ne compte pas

L'absence de donnees reste neutre (None), pas artificiellement negative ou positive.
"""

from __future__ import annotations

from alladin.core.enums import MarketRegime
from alladin.research.repository import ResearchRepository

# Splits dont les resultats sont dignes de confiance pour le routing
_TRUSTED_SPLITS = ("DEMO", "OUT_OF_SAMPLE")


class ResearchPerformanceProvider:
    """Fournit expectancy_r au StrategyRouter depuis le ResearchRepository.

    Seuls les splits OOS et DEMO_FORWARD alimentent le routeur.
    TRAIN et VALIDATION ne sont JAMAIS utilises pour le routing.
    """

    def __init__(self, repo: ResearchRepository) -> None:
        self._repo = repo
        self._cache: dict[tuple[str, str, str], float | None] = {}
        self._loaded = False

    def _load(self) -> None:
        """Charge les resultats depuis le repo (lazy, une seule fois)."""
        if self._loaded:
            return
        experiments = self._repo.list_experiments()
        for exp in experiments:
            if exp.split not in _TRUSTED_SPLITS:
                continue
            result = self._repo.get_result(exp.experiment_id)
            if result is None or result.trades < 10:
                continue
            # Key: (strategy_id, strategy_version, regime)
            # On ne filtre pas par regime ici car les experiments
            # couvrent souvent plusieurs regimes
            key = (exp.strategy_id, exp.strategy_version, "ALL")
            # Priorite DEMO_FORWARD > OOS
            existing = self._cache.get(key)
            if existing is None or exp.split == "DEMO":
                self._cache[key] = result.expectancy
        self._loaded = True

    def expectancy_r(
        self, strategy_id: str, strategy_version: str, regime: MarketRegime
    ) -> float | None:
        """Retourne l'expectancy R validee ou None si pas assez de donnees.

        None = neutre (pas de penalite, pas de bonus).
        """
        self._load()
        # Chercher d'abord par regime specifique, puis ALL
        for regime_key in (regime.value, "ALL"):
            val = self._cache.get((strategy_id, strategy_version, regime_key))
            if val is not None:
                return val
        return None

    def invalidate(self) -> None:
        """Force le rechargement au prochain appel."""
        self._cache.clear()
        self._loaded = False
