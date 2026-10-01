"""Persistance SQLite des modèles Research.

Tables append-only : les enregistrements ne sont jamais modifiés, seul
`updated_at` + `status` sont mis à jour sur les StrategyVersion
(pour refléter la progression du lifecycle).

Garanties :
- Les sources, findings et hypothèses sont immuables après création.
- Les StrategyVersion sont immuables sauf pour `status` (lifecycle).
- Les ExperimentResult sont immuables.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Engine,
    Float,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    text,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from alladin.research.models import (
    ExperimentResult,
    ResearchFinding,
    ResearchSource,
    StrategyExperiment,
    StrategyHypothesis,
    StrategyStatus,
    StrategyVersion,
)

_meta = MetaData()

_LIFECYCLE = (
    StrategyStatus.DISCOVERED, StrategyStatus.FORMALIZED,
    StrategyStatus.BACKTESTING, StrategyStatus.BACKTEST_PASSED,
    StrategyStatus.OOS_TESTING, StrategyStatus.OOS_PASSED,
    StrategyStatus.DEMO_TESTING, StrategyStatus.CANDIDATE,
    StrategyStatus.APPROVED,
)


def _validate_transition(old: StrategyStatus, new: StrategyStatus) -> None:
    if old == new:
        return
    if new in (StrategyStatus.REJECTED, StrategyStatus.RETIRED):
        return
    if old not in _LIFECYCLE or new not in _LIFECYCLE or _LIFECYCLE.index(new) != _LIFECYCLE.index(old) + 1:
        raise ValueError(f"invalid strategy lifecycle transition: {old} -> {new}")

_sources = Table(
    "research_sources",
    _meta,
    Column("source_id", String, primary_key=True),
    Column("url", String, nullable=True),
    Column("title", String, nullable=False),
    Column("author", String, nullable=True),
    Column("published_at", DateTime, nullable=True),
    Column("retrieved_at", DateTime, nullable=False),
    Column("source_type", String, nullable=False),
    Column("notes", Text, default=""),
    Column("created_at", DateTime, nullable=False),
)

_findings = Table(
    "research_findings",
    _meta,
    Column("finding_id", String, primary_key=True),
    Column("source_ids", Text, nullable=False),  # JSON list
    Column("claim", Text, nullable=False),
    Column("market", String, nullable=False),
    Column("timeframe", String, nullable=False),
    Column("conditions", Text, default="[]"),
    Column("claimed_edge", Text, default=""),
    Column("limitations", Text, default="[]"),
    Column("created_at", DateTime, nullable=False),
)

_hypotheses = Table(
    "research_hypotheses",
    _meta,
    Column("hypothesis_id", String, primary_key=True),
    Column("finding_ids", Text, nullable=False),
    Column("statement", Text, nullable=False),
    Column("entry_logic", Text, nullable=False),
    Column("exit_logic", Text, nullable=False),
    Column("risk_assumptions", Text, default="[]"),
    Column("market_regime", String, nullable=False),
    Column("invalidation_conditions", Text, default="[]"),
    Column("created_at", DateTime, nullable=False),
)

_versions = Table(
    "research_strategy_versions",
    _meta,
    Column("strategy_id", String, nullable=False),
    Column("version", String, nullable=False),
    Column("parent_version", String, nullable=True),
    Column("source_ids", Text, default="[]"),
    Column("hypothesis_ids", Text, default="[]"),
    Column("parameters", Text, default="{}"),
    Column("code_hash", String, nullable=False),
    Column("status", String, nullable=False),
    Column("created_at", DateTime, nullable=False),
    Column("updated_at", DateTime, nullable=False),
)

_experiments = Table(
    "research_experiments",
    _meta,
    Column("experiment_id", String, primary_key=True),
    Column("strategy_id", String, nullable=False),
    Column("strategy_version", String, nullable=False),
    Column("dataset", String, nullable=False),
    Column("period_start", DateTime, nullable=False),
    Column("period_end", DateTime, nullable=False),
    Column("symbols", Text, nullable=False),
    Column("timeframes", Text, nullable=False),
    Column("parameters", Text, default="{}"),
    Column("split", String, nullable=False),
    Column("created_at", DateTime, nullable=False),
)

_results = Table(
    "research_experiment_results",
    _meta,
    Column("experiment_id", String, primary_key=True),
    Column("trades", Float, nullable=False),
    Column("wins", Float, nullable=False),
    Column("losses", Float, nullable=False),
    Column("win_rate", Float, nullable=True),
    Column("expectancy", Float, nullable=True),
    Column("profit_factor", Float, nullable=True),
    Column("max_drawdown", Float, nullable=True),
    Column("r_total", Float, nullable=True),
    Column("sharpe", Float, nullable=True),
    Column("passed", Boolean, nullable=False),
    Column("created_at", DateTime, nullable=False),
)


def _now() -> datetime:
    return datetime.now(UTC)


def _j(val: Any) -> str:
    return json.dumps(val)


def _from_j(val: str) -> Any:
    return json.loads(val)


class ResearchRepository:
    """Dépôt SQLAlchemy pour les modèles Research (SQLite)."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        _meta.create_all(engine)

    @classmethod
    def from_url(cls, db_url: str) -> ResearchRepository:
        return cls(create_engine(db_url, connect_args={"check_same_thread": False}))

    @classmethod
    def from_engine(cls, engine: Engine) -> ResearchRepository:
        return cls(engine)

    # ------------------------------------------------------------------ sources

    def save_source(self, source: ResearchSource) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                sqlite_insert(_sources).on_conflict_do_nothing(),
                {
                    "source_id": source.source_id,
                    "url": source.url,
                    "title": source.title,
                    "author": source.author,
                    "published_at": source.published_at,
                    "retrieved_at": source.retrieved_at,
                    "source_type": source.source_type.value,
                    "notes": source.notes,
                    "created_at": _now(),
                },
            )

    def get_source(self, source_id: str) -> ResearchSource | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                _sources.select().where(_sources.c.source_id == source_id)
            ).first()
        if row is None:
            return None
        return ResearchSource(
            source_id=row.source_id,
            url=row.url,
            title=row.title,
            author=row.author,
            published_at=row.published_at,
            retrieved_at=row.retrieved_at,
            source_type=row.source_type,
            notes=row.notes or "",
        )

    def list_sources(self) -> list[ResearchSource]:
        with self.engine.connect() as conn:
            rows = conn.execute(_sources.select().order_by(_sources.c.created_at)).all()
        return [
            ResearchSource(
                source_id=r.source_id,
                url=r.url,
                title=r.title,
                author=r.author,
                published_at=r.published_at,
                retrieved_at=r.retrieved_at,
                source_type=r.source_type,
                notes=r.notes or "",
            )
            for r in rows
        ]

    # ------------------------------------------------------------------ findings

    def save_finding(self, finding: ResearchFinding) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                sqlite_insert(_findings).on_conflict_do_nothing(),
                {
                    "finding_id": finding.finding_id,
                    "source_ids": _j(finding.source_ids),
                    "claim": finding.claim,
                    "market": finding.market,
                    "timeframe": finding.timeframe,
                    "conditions": _j(finding.conditions),
                    "claimed_edge": finding.claimed_edge,
                    "limitations": _j(finding.limitations),
                    "created_at": _now(),
                },
            )

    def list_findings(self) -> list[ResearchFinding]:
        with self.engine.connect() as conn:
            rows = conn.execute(_findings.select().order_by(_findings.c.created_at)).all()
        return [
            ResearchFinding(
                finding_id=r.finding_id,
                source_ids=_from_j(r.source_ids),
                claim=r.claim,
                market=r.market,
                timeframe=r.timeframe,
                conditions=_from_j(r.conditions),
                claimed_edge=r.claimed_edge,
                limitations=_from_j(r.limitations),
            )
            for r in rows
        ]

    # ------------------------------------------------------------------ hypotheses

    def save_hypothesis(self, hyp: StrategyHypothesis) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                sqlite_insert(_hypotheses).on_conflict_do_nothing(),
                {
                    "hypothesis_id": hyp.hypothesis_id,
                    "finding_ids": _j(hyp.finding_ids),
                    "statement": hyp.statement,
                    "entry_logic": hyp.entry_logic,
                    "exit_logic": hyp.exit_logic,
                    "risk_assumptions": _j(hyp.risk_assumptions),
                    "market_regime": hyp.market_regime,
                    "invalidation_conditions": _j(hyp.invalidation_conditions),
                    "created_at": _now(),
                },
            )

    def list_hypotheses(self) -> list[StrategyHypothesis]:
        with self.engine.connect() as conn:
            rows = conn.execute(_hypotheses.select().order_by(_hypotheses.c.created_at)).all()
        return [
            StrategyHypothesis(
                hypothesis_id=r.hypothesis_id,
                finding_ids=_from_j(r.finding_ids),
                statement=r.statement,
                entry_logic=r.entry_logic,
                exit_logic=r.exit_logic,
                risk_assumptions=_from_j(r.risk_assumptions),
                market_regime=r.market_regime,
                invalidation_conditions=_from_j(r.invalidation_conditions),
            )
            for r in rows
        ]

    # ------------------------------------------------------------------ strategy versions

    def save_version(self, version: StrategyVersion) -> None:
        now = _now()
        with self.engine.begin() as conn:
            existing = conn.execute(
                _versions.select()
                .where(_versions.c.strategy_id == version.strategy_id)
                .where(_versions.c.version == version.version)
            ).first()
            if existing is None:
                if version.status is not StrategyStatus.DISCOVERED:
                    raise ValueError("new strategy version must start DISCOVERED")
                conn.execute(
                    _versions.insert(),
                    {
                        "strategy_id": version.strategy_id,
                        "version": version.version,
                        "parent_version": version.parent_version,
                        "source_ids": _j(version.source_ids),
                        "hypothesis_ids": _j(version.hypothesis_ids),
                        "parameters": _j(version.parameters),
                        "code_hash": version.code_hash,
                        "status": version.status.value,
                        "created_at": version.created_at,
                        "updated_at": now,
                    },
                )
            else:
                # Seul le status peut être mis à jour
                _validate_transition(StrategyStatus(existing.status), version.status)
                conn.execute(
                    _versions.update()
                    .where(_versions.c.strategy_id == version.strategy_id)
                    .where(_versions.c.version == version.version),
                    {"status": version.status.value, "updated_at": now},
                )

    def update_status(self, strategy_id: str, version: str, status: StrategyStatus) -> None:
        with self.engine.begin() as conn:
            row = conn.execute(
                _versions.select().where(_versions.c.strategy_id == strategy_id)
                .where(_versions.c.version == version)
            ).first()
            if row is None:
                raise ValueError("unknown strategy version")
            _validate_transition(StrategyStatus(row.status), status)
            conn.execute(
                _versions.update()
                .where(_versions.c.strategy_id == strategy_id)
                .where(_versions.c.version == version),
                {"status": status.value, "updated_at": _now()},
            )

    def list_versions(self, strategy_id: str | None = None) -> list[StrategyVersion]:
        q = _versions.select().order_by(_versions.c.created_at)
        if strategy_id:
            q = q.where(_versions.c.strategy_id == strategy_id)
        with self.engine.connect() as conn:
            rows = conn.execute(q).all()
        return [
            StrategyVersion(
                strategy_id=r.strategy_id,
                version=r.version,
                parent_version=r.parent_version,
                source_ids=_from_j(r.source_ids),
                hypothesis_ids=_from_j(r.hypothesis_ids),
                parameters=_from_j(r.parameters),
                code_hash=r.code_hash,
                status=StrategyStatus(r.status),
                created_at=r.created_at,
            )
            for r in rows
        ]

    # ------------------------------------------------------------------ experiments

    def save_experiment(self, exp: StrategyExperiment) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                sqlite_insert(_experiments).on_conflict_do_nothing(),
                {
                    "experiment_id": exp.experiment_id,
                    "strategy_id": exp.strategy_id,
                    "strategy_version": exp.strategy_version,
                    "dataset": exp.dataset,
                    "period_start": exp.period_start,
                    "period_end": exp.period_end,
                    "symbols": _j(exp.symbols),
                    "timeframes": _j(exp.timeframes),
                    "parameters": _j(exp.parameters),
                    "split": exp.split,
                    "created_at": _now(),
                },
            )

    def list_experiments(self, strategy_id: str | None = None) -> list[StrategyExperiment]:
        q = _experiments.select().order_by(_experiments.c.created_at)
        if strategy_id:
            q = q.where(_experiments.c.strategy_id == strategy_id)
        with self.engine.connect() as conn:
            rows = conn.execute(q).all()
        return [
            StrategyExperiment(
                experiment_id=r.experiment_id,
                strategy_id=r.strategy_id,
                strategy_version=r.strategy_version,
                dataset=r.dataset,
                period_start=r.period_start,
                period_end=r.period_end,
                symbols=_from_j(r.symbols),
                timeframes=_from_j(r.timeframes),
                parameters=_from_j(r.parameters),
                split=r.split,
            )
            for r in rows
        ]

    # ------------------------------------------------------------------ results

    def save_result(self, result: ExperimentResult) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                sqlite_insert(_results).on_conflict_do_nothing(),
                {
                    "experiment_id": result.experiment_id,
                    "trades": result.trades,
                    "wins": result.wins,
                    "losses": result.losses,
                    "win_rate": result.win_rate,
                    "expectancy": result.expectancy,
                    "profit_factor": result.profit_factor,
                    "max_drawdown": result.max_drawdown,
                    "r_total": result.r_total,
                    "sharpe": result.sharpe,
                    "passed": result.passed,
                    "created_at": _now(),
                },
            )

    def get_result(self, experiment_id: str) -> ExperimentResult | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                _results.select().where(_results.c.experiment_id == experiment_id)
            ).first()
        if row is None:
            return None
        return ExperimentResult(
            experiment_id=row.experiment_id,
            trades=int(row.trades),
            wins=int(row.wins),
            losses=int(row.losses),
            win_rate=row.win_rate,
            expectancy=row.expectancy,
            profit_factor=row.profit_factor,
            max_drawdown=row.max_drawdown,
            r_total=row.r_total,
            sharpe=row.sharpe,
            passed=bool(row.passed),
        )

    def stats(self) -> dict[str, int]:
        with self.engine.connect() as conn:
            return {
                "sources": conn.execute(text("SELECT COUNT(*) FROM research_sources")).scalar() or 0,
                "findings": conn.execute(text("SELECT COUNT(*) FROM research_findings")).scalar() or 0,
                "hypotheses": conn.execute(text("SELECT COUNT(*) FROM research_hypotheses")).scalar() or 0,
                "versions": conn.execute(text("SELECT COUNT(*) FROM research_strategy_versions")).scalar() or 0,
                "experiments": conn.execute(text("SELECT COUNT(*) FROM research_experiments")).scalar() or 0,
                "results": conn.execute(text("SELECT COUNT(*) FROM research_experiment_results")).scalar() or 0,
            }
