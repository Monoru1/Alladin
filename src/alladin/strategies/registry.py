"""StrategyRegistry : bibliothèque de stratégies versionnées, activables par configuration."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from alladin.core.enums import MarketRegime
from alladin.core.errors import ConfigError
from alladin.strategies.base import Strategy
from alladin.strategies.breakout import Breakout01
from alladin.strategies.range import Range01
from alladin.strategies.trend import Trend01

log = logging.getLogger(__name__)

BUILTIN: tuple[type[Strategy], ...] = (Trend01, Breakout01, Range01)


class StrategyConfig(BaseModel):
    id: str
    version: str
    enabled: bool = False
    params: dict[str, Any] = {}
    notes: str = ""
    research_paper: bool = False


class StrategyRegistry:
    def __init__(self) -> None:
        self._classes: dict[tuple[str, str], type[Strategy]] = {}
        self._active: dict[str, Strategy] = {}
        self.unavailable: dict[str, str] = {}  # id -> raison (config sans implémentation, etc.)
        self._research_paper: set[str] = set()

    def register(self, cls: type[Strategy]) -> None:
        self._classes[(cls.id, cls.version)] = cls

    def activate(self, cfg: StrategyConfig) -> None:
        cls = self._classes.get((cfg.id, cfg.version))
        if cls is None:
            self._active.pop(cfg.id, None)
            self.unavailable[cfg.id] = f"version {cfg.version} non implémentée" + (
                "" if cfg.enabled else " (planifiée)"
            )
            return
        if not cfg.enabled:
            self._active.pop(cfg.id, None)
            return
        self._active[cfg.id] = cls(cfg.params)
        if cfg.research_paper:
            self._research_paper.add(cfg.id)

    @classmethod
    def from_config(cls, strategies_dir: Path) -> StrategyRegistry:
        reg = cls()
        for k in BUILTIN:
            reg.register(k)
        path = strategies_dir / "strategies.yaml"
        if not path.is_file():
            raise ConfigError(f"configuration des stratégies introuvable : {path}")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for raw in data.get("strategies", []):
            reg.activate(StrategyConfig.model_validate(raw))
        return reg

    # ------------------------------------------------------------------ accès

    def enabled(self) -> list[Strategy]:
        return list(self._active.values())

    def get(self, strategy_id: str) -> Strategy | None:
        return self._active.get(strategy_id)

    def for_regime(self, regime: MarketRegime) -> list[Strategy]:
        return [s for s in self._active.values() if s.is_compatible(regime)]

    def catalogue(self) -> list[dict[str, Any]]:
        rows = [
            {
                "id": s.id,
                "version": s.version,
                "enabled": True,
                "regimes": sorted(r.value for r in s.compatible_regimes),
            }
            for s in self._active.values()
        ]
        rows += [{"id": i, "enabled": False, "note": why} for i, why in self.unavailable.items()]
        return rows

    def check_lifecycle(
        self,
        approved_ids: set[str],
        *,
        strict: bool = False,
    ) -> dict[str, str]:
        """Verifie que les strategies actives ont un statut APPROVED dans le Research repo.

        Retourne un dict {strategy_id: raison} pour les strategies non-approuvees.
        Si strict=True, retire les strategies non approuvees de _active.
        """
        violations: dict[str, str] = {}
        for strat_id in list(self._active.keys()):
            strategy = self._active[strat_id]
            if strat_id not in approved_ids and f"{strat_id}@{strategy.version}" not in approved_ids:
                reason = f"strategie {strat_id} non approuvee (lifecycle enforcement)"
                violations[strat_id] = reason
                if strict:
                    del self._active[strat_id]
                    self.unavailable[strat_id] = reason
        return violations

    def check_paper_lifecycle(self, approved_keys: set[str]) -> dict[str, str]:
        """PAPER: version approuvee ou opt-in research_paper explicite."""
        return self.check_lifecycle(approved_keys | self._research_paper, strict=True)

