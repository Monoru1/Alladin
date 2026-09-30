from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from alladin.orchestration.bootstrap import Components
from alladin.replay import ReplayContext
from alladin.research.models import (
    ExperimentResult,
    ResearchSource,
    SourceType,
    StrategyStatus,
    StrategyVersion,
)


def test_research_models_keep_sources_versions_and_safe_default_status() -> None:
    now = datetime.now(UTC)
    source = ResearchSource(source_id="SRC-1", title="Paper", retrieved_at=now, source_type=SourceType.ACADEMIC)
    version = StrategyVersion(strategy_id="TREND-X", version="1.0.0", source_ids=[source.source_id],
                              code_hash="abc123", created_at=now)
    assert version.status is StrategyStatus.DISCOVERED
    assert version.status is not StrategyStatus.APPROVED
    with pytest.raises(ValidationError):
        ExperimentResult(experiment_id="E-1", trades=2, wins=2, losses=1)


def test_replay_reconstructs_cycle_without_broker_side_effect(svc: Components) -> None:
    svc.journal.current_cycle = "CYC-REPLAY"
    svc.journal.log(svc.run.run_id, "market.scan", {"analysed": 10})
    svc.journal.log(svc.run.run_id, "risk.decision", {"status": "APPROVED"})
    svc.journal.current_cycle = None
    before = list(svc.broker.positions())
    replay = ReplayContext.from_cycle(svc.repo, "CYC-REPLAY")
    assert replay.run_id == svc.run.run_id
    assert [event["type"] for event in replay.events] == ["market.scan", "risk.decision"]
    assert svc.broker.positions() == before
