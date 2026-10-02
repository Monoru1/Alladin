"""Reconstruction read-only d'un cycle, sans broker et sans exécution."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from alladin.core.enums import Timeframe
from alladin.core.models import Bar
from alladin.journal.repository import JournalRepository
from alladin.market.archive import MarketDataArchive


class ReplayContext(BaseModel):
    cycle_id: str
    run_id: str
    market_inputs: list[dict[str, Any]] = []
    market_bars: dict[str, dict[Timeframe, list[Bar]]] = {}
    events: list[dict[str, Any]] = []

    @classmethod
    def from_cycle(cls, repo: JournalRepository, cycle_id: str) -> ReplayContext:
        for run in repo.list_runs():
            events = repo.events(run.run_id, cycle_id=cycle_id)
            if events:
                archive = MarketDataArchive(repo.engine, read_only=True)
                return cls(cycle_id=cycle_id, run_id=run.run_id,
                           market_inputs=archive.cycle_inputs(cycle_id),
                           market_bars=archive.load_cycle(cycle_id),
                           events=[e.model_dump(mode="json") for e in events])
        raise ValueError(f"cycle inconnu : {cycle_id}")
