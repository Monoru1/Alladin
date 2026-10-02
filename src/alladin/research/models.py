from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class SourceType(StrEnum):
    ACADEMIC = "ACADEMIC"
    DOCUMENTATION = "DOCUMENTATION"
    GITHUB = "GITHUB"
    ARTICLE = "ARTICLE"
    TRADER_IDEA = "TRADER_IDEA"
    QUANT_RESEARCH = "QUANT_RESEARCH"
    MANUAL = "MANUAL"


class StrategyStatus(StrEnum):
    DISCOVERED = "DISCOVERED"
    FORMALIZED = "FORMALIZED"
    BACKTESTING = "BACKTESTING"
    BACKTEST_PASSED = "BACKTEST_PASSED"
    OOS_TESTING = "OOS_TESTING"
    OOS_PASSED = "OOS_PASSED"
    DEMO_TESTING = "DEMO_TESTING"
    CANDIDATE = "CANDIDATE"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RETIRED = "RETIRED"


class ResearchSource(BaseModel):
    source_id: str
    url: str | None = None
    title: str
    author: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime
    source_type: SourceType
    notes: str = ""


class ResearchFinding(BaseModel):
    finding_id: str
    source_ids: list[str]
    claim: str
    market: str
    timeframe: str
    conditions: list[str] = []
    claimed_edge: str = ""
    limitations: list[str] = []


class StrategyHypothesis(BaseModel):
    hypothesis_id: str
    finding_ids: list[str]
    statement: str
    entry_logic: str
    exit_logic: str
    risk_assumptions: list[str]
    market_regime: str
    invalidation_conditions: list[str]


class StrategyVersion(BaseModel):
    strategy_id: str
    version: str
    parent_version: str | None = None
    source_ids: list[str] = []
    hypothesis_ids: list[str] = []
    parameters: dict[str, Any] = {}
    code_hash: str
    status: StrategyStatus = StrategyStatus.DISCOVERED
    created_at: datetime


class StrategyExperiment(BaseModel):
    experiment_id: str
    strategy_id: str
    strategy_version: str
    dataset: str
    dataset_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    dataset_provenance: str | None = None
    period_start: datetime
    period_end: datetime
    symbols: list[str]
    timeframes: list[str]
    parameters: dict[str, Any] = {}
    split: Literal["TRAIN", "VALIDATION", "OUT_OF_SAMPLE", "DEMO"]

    @model_validator(mode="after")
    def dataset_evidence_is_paired(self) -> StrategyExperiment:
        if (self.dataset_fingerprint is None) != (self.dataset_provenance is None):
            raise ValueError("dataset fingerprint and provenance must be provided together")
        return self


class ExperimentResult(BaseModel):
    experiment_id: str
    trades: int = Field(ge=0)
    wins: int = Field(ge=0)
    losses: int = Field(ge=0)
    win_rate: float | None = None
    expectancy: float | None = None
    profit_factor: float | None = None
    max_drawdown: float | None = None
    r_total: float | None = None
    sharpe: float | None = None
    passed: bool = False

    @model_validator(mode="after")
    def counts_are_consistent(self) -> ExperimentResult:
        if self.wins + self.losses > self.trades:
            raise ValueError("wins + losses dépasse trades")
        return self
