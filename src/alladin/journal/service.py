"""JournalService : API typée au-dessus du dépôt + statistiques d'expérience."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from alladin.core.enums import MarketRegime
from alladin.journal.models import EventType, JournalEvent, TradeRecord
from alladin.journal.repository import JournalRepository


def _session(ts: datetime) -> str:
    h = ts.astimezone(UTC).hour
    parts = [n for n, on in (("TOKYO", h < 8), ("LONDON", 7 <= h < 16), ("NEWYORK", 12 <= h < 21)) if on]
    return "+".join(parts) or "OFF_HOURS"


class BucketStats(BaseModel):
    key: str
    trades: int
    wins: int
    win_rate: float
    net_pnl: float
    avg_r: float  # espérance en R
    worst_r: float
    best_r: float


class JournalService:
    def __init__(self, repo: JournalRepository, clock: Callable[[], datetime] | None = None) -> None:
        self.repo = repo
        self.clock = clock or (lambda: datetime.now(UTC))

    current_cycle: str | None = None  # cycle_id appliqué automatiquement aux événements journalisés

    def log(
        self,
        run_id: str,
        type_: EventType | str,
        payload: dict[str, Any] | None = None,
        cycle_id: str | None = None,
    ) -> JournalEvent:
        return self.repo.append(
            run_id, str(type_), payload or {}, self.clock(), cycle_id or self.current_cycle
        )

    def no_trade(
        self,
        run_id: str,
        *,
        studied: list[str],
        candidates: list[str],
        strategies_evaluated: dict[str, list[str]],
        rejections: dict[str, list[str]],
        agent: str | None,
        reason: str,
    ) -> JournalEvent:
        """NO TRADE est une décision valide : on journalise tout ce qui l'explique."""
        return self.log(
            run_id,
            EventType.NO_TRADE,
            {
                "instruments_studied": studied,
                "candidates": candidates,
                "strategies_evaluated": strategies_evaluated,
                "rejections": rejections,
                "agent_consulted": agent,
                "final_decision": "NO_TRADE",
                "reason": reason,
            },
        )

    # ------------------------------------------------------------------ statistiques

    def _stats(self, trades: list[TradeRecord], key: Callable[[TradeRecord], str]) -> list[BucketStats]:
        buckets: dict[str, list[TradeRecord]] = defaultdict(list)
        for t in trades:
            buckets[key(t)].append(t)
        out: list[BucketStats] = []
        for k, ts in sorted(buckets.items()):
            rs = [t.r_multiple or 0.0 for t in ts]
            wins = sum(1 for t in ts if (t.net_pnl or 0) > 0)
            out.append(
                BucketStats(
                    key=k,
                    trades=len(ts),
                    wins=wins,
                    win_rate=wins / len(ts),
                    net_pnl=sum(t.net_pnl or 0 for t in ts),
                    avg_r=sum(rs) / len(ts),
                    worst_r=min(rs),
                    best_r=max(rs),
                )
            )
        return out

    def stats(self, dimension: str, run_id: str | None = None) -> list[BucketStats]:
        trades = self.repo.trades_for_run(run_id, "CLOSED") if run_id else self.repo.all_closed_trades()
        keys: dict[str, Callable[[TradeRecord], str]] = {
            "strategy": lambda t: f"{t.strategy_id}@{t.strategy_version}",
            "symbol": lambda t: t.symbol,
            "regime": lambda t: t.regime,
            "session": lambda t: _session(t.opened_at),
            "agent": lambda t: t.agent,
        }
        return self._stats(trades, keys[dimension])

    # PerformanceProvider (utilisé par le StrategyRouter)
    def expectancy_r(
        self, strategy_id: str, strategy_version: str, regime: MarketRegime, min_trades: int = 10
    ) -> float | None:
        rel = [
            t
            for t in self.repo.all_closed_trades()
            if t.strategy_id == strategy_id
            and t.strategy_version == strategy_version
            and t.regime == regime.value
        ]
        if len(rel) < min_trades:
            return None
        return sum(t.r_multiple or 0.0 for t in rel) / len(rel)
