"""Immutable closed-trade outcomes. No broker access, promotion or training side effects."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Column, MetaData, String, Table, Text, inspect, text
from sqlalchemy.exc import IntegrityError

from alladin.core.enums import Side
from alladin.core.workspace import WorkspaceId
from alladin.journal.models import EventType
from alladin.journal.repository import JournalRepository, paper_positions, trades
from alladin.journal.service import JournalService


def fingerprint(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(body.encode()).hexdigest()


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class RewardPolicy(FrozenModel):
    version: str = Field(min_length=1)
    pnl_weight: float = Field(ge=0)
    quality_weight: float = Field(ge=0)
    drawdown_weight: float = Field(ge=0)
    clip_abs: float = Field(gt=0)

    @property
    def policy_hash(self) -> str:
        return fingerprint(self.model_dump(mode="json"))

    @classmethod
    def load(cls, path: Path) -> RewardPolicy:
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


class OutcomeInput(FrozenModel):
    workspace: WorkspaceId
    run_id: str
    mode: Literal["DEMO", "PAPER"]
    source_id: str
    proposal_id: str | None = None
    opportunity_id: str | None = None
    strategy_id: str
    strategy_version: str
    symbol: str
    side: Side
    currency: str | None = None
    opened_at: datetime
    closed_at: datetime
    entry_price: float | None = Field(default=None, gt=0)
    exit_price: float | None = Field(default=None, gt=0)
    original_volume: float = Field(gt=0)
    price_value_per_lot: float | None = Field(default=None, gt=0)
    initial_risk: float | None = Field(default=None, ge=0)
    gross_pnl: float | None = None
    commission_cashflow: float | None = None
    swap_cashflow: float | None = None
    net_pnl: float | None = None
    mae_amount: float | None = Field(default=None, ge=0)
    mfe_amount: float | None = Field(default=None, ge=0)
    excursion_samples: int = Field(default=0, ge=0)
    protected_initial: bool | None = None
    protection_incidents: int = Field(default=0, ge=0)
    evidence_hashes: tuple[str, ...] = ()
    adopted: bool = False
    cost_basis: str

    @model_validator(mode="after")
    def times_and_costs(self) -> OutcomeInput:
        if any(t.tzinfo is None or t.utcoffset() is None for t in (self.opened_at, self.closed_at)):
            raise ValueError("outcome timestamps must be timezone aware")
        if self.closed_at < self.opened_at:
            raise ValueError("closure precedes opening")
        parts = (self.gross_pnl, self.commission_cashflow, self.swap_cashflow, self.net_pnl)
        if all(v is not None for v in parts):
            assert self.gross_pnl is not None and self.commission_cashflow is not None
            assert self.swap_cashflow is not None and self.net_pnl is not None
            if not math.isclose(self.gross_pnl + self.commission_cashflow + self.swap_cashflow,
                                self.net_pnl, rel_tol=1e-9, abs_tol=1e-6):
                raise ValueError("net P&L inconsistent with reported components")
        return self


class Counterfactual(FrozenModel):
    name: str
    basis: str
    gross_pnl: float | None = None
    net_pnl: float | None = None
    delta_gross: float | None = None
    delta_net: float | None = None
    reason: str = ""


class TradeOutcome(FrozenModel):
    outcome_id: str
    engine_version: str = "outcome-v1"
    source_fingerprint: str
    source: OutcomeInput
    policy: RewardPolicy
    policy_hash: str
    created_at: datetime
    status: Literal["ELIGIBLE", "INCOMPLETE"]
    warnings: tuple[str, ...]
    holding_seconds: float = Field(ge=0)
    net_r: float | None = None
    mae_r: float | None = None
    mfe_r: float | None = None
    quality_score: float | None = None
    pnl_component: float | None = None
    quality_component: float | None = None
    drawdown_component: float | None = None
    reward_unclipped: float | None = None
    reward: float | None = None
    counterfactuals: tuple[Counterfactual, ...]


def evaluate_outcome(source: OutcomeInput, policy: RewardPolicy, now: datetime) -> TradeOutcome:
    if now.tzinfo is None or now.utcoffset() is None or now < source.closed_at:
        raise ValueError("outcome creation requires an aware clock after closure")
    warnings = []
    risk = source.initial_risk
    usable_risk = risk is not None and risk > 0 and not source.adopted
    if not usable_risk:
        warnings.append("initial risk unknown or adopted position; no learning reward")
    net_r = source.net_pnl / risk if source.net_pnl is not None and usable_risk and risk else None
    sampled = source.excursion_samples > 0
    mae_r = source.mae_amount / risk if usable_risk and sampled and source.mae_amount is not None and risk else None
    mfe_r = source.mfe_amount / risk if usable_risk and sampled and source.mfe_amount is not None and risk else None
    if mae_r is None or mfe_r is None:
        warnings.append("monetary excursions unavailable")
    if source.protected_initial is None:
        warnings.append("initial protection evidence unavailable")
    quality = None if source.protected_initial is None else (
        1.0 if source.protected_initial and source.protection_incidents == 0 else -1.0)
    if not source.currency:
        warnings.append("account currency unknown")
    if any(v is None for v in (source.gross_pnl, source.commission_cashflow, source.swap_cashflow, source.net_pnl)):
        warnings.append("cost decomposition unavailable")
    eligible = not warnings and net_r is not None and mae_r is not None and quality is not None
    pnl_component = policy.pnl_weight * net_r if eligible and net_r is not None else None
    quality_component = policy.quality_weight * quality if eligible and quality is not None else None
    drawdown_component = -policy.drawdown_weight * mae_r if eligible and mae_r is not None else None
    raw = (pnl_component + quality_component + drawdown_component
           if pnl_component is not None and quality_component is not None and drawdown_component is not None else None)
    counterfactuals = [Counterfactual(name="NO_TRADE", basis="ZERO_EXPOSURE", gross_pnl=0, net_pnl=0,
                                     delta_gross=source.gross_pnl, delta_net=source.net_pnl)]
    value = source.price_value_per_lot
    if value and source.entry_price is not None and source.exit_price is not None:
        gross = (source.exit_price - source.entry_price) * source.side.sign * value * source.original_volume
        counterfactuals.append(Counterfactual(name="HOLD_TO_ACTUAL_EXIT", basis="MODELED_OPENING_CONVERSION",
                                             gross_pnl=gross,
                                             delta_gross=source.gross_pnl - gross if source.gross_pnl is not None else None,
                                             reason="same actual final exit price/time; different fees and financing unknown"))
    else:
        counterfactuals.append(Counterfactual(name="HOLD_TO_ACTUAL_EXIT", basis="UNAVAILABLE",
                                             reason="opening price conversion or final prices unknown"))
    key = f"outcome-v1:{source.workspace}:{source.run_id}:{source.mode}:{source.source_id}:{policy.policy_hash}"
    return TradeOutcome(outcome_id=f"OUT-{uuid5(NAMESPACE_URL, key).hex}", source_fingerprint=fingerprint(source.model_dump(mode="json")),
                        source=source, policy=policy, policy_hash=policy.policy_hash, created_at=now,
                        status="ELIGIBLE" if eligible else "INCOMPLETE", warnings=tuple(warnings),
                        holding_seconds=(source.closed_at - source.opened_at).total_seconds(),
                        net_r=net_r, mae_r=mae_r, mfe_r=mfe_r, quality_score=quality,
                        pnl_component=pnl_component, quality_component=quality_component, drawdown_component=drawdown_component,
                        reward_unclipped=raw, reward=max(-policy.clip_abs, min(policy.clip_abs, raw)) if raw is not None else None,
                        counterfactuals=tuple(counterfactuals))


_meta = MetaData()
outcomes = Table("trade_outcomes", _meta,
                 Column("outcome_id", String, primary_key=True), Column("workspace", String, nullable=False),
                 Column("run_id", String, nullable=False, index=True), Column("mode", String, nullable=False),
                 Column("source_id", String, nullable=False), Column("policy_hash", String, nullable=False),
                 Column("source_fingerprint", String, nullable=False), Column("payload_hash", String, nullable=False),
                 Column("closed_at", String, nullable=False), Column("payload", Text, nullable=False))


class OutcomeRepository:
    def __init__(self, repo: JournalRepository, *, read_only: bool = False) -> None:
        self.repo = repo
        if not read_only:
            _meta.create_all(repo.engine)
            if repo.engine.dialect.name == "sqlite":
                with repo.engine.begin() as c:
                    for operation in ("UPDATE", "DELETE"):
                        c.execute(text(f"CREATE TRIGGER IF NOT EXISTS outcomes_no_{operation.lower()} BEFORE {operation} "
                                       "ON trade_outcomes BEGIN SELECT RAISE(ABORT, 'outcomes are immutable'); END"))
        self.available = inspect(repo.engine).has_table("trade_outcomes")

    def list(self, run_id: str, *, limit: int = 200) -> list[TradeOutcome]:
        if not self.available:
            return []
        with self.repo.engine.connect() as c:
            rows = c.execute(outcomes.select().where(outcomes.c.workspace == self.repo.workspace.value,
                                                    outcomes.c.run_id == run_id).order_by(outcomes.c.closed_at.desc(), outcomes.c.outcome_id).limit(limit)).mappings().all()
        evidence = {e.payload.get("outcome_id"): e.payload.get("outcome_fingerprint")
                    for e in self.repo.events(run_id, [EventType.OUTCOME.value])}
        decoded = [self._decode(row) for row in rows]
        if any(evidence.get(r.outcome_id) != fingerprint(r.model_dump(mode="json")) for r in decoded):
            raise ValueError("outcome differs from journal evidence")
        return decoded

    def _decode(self, row: Any) -> TradeOutcome:
        outcome = TradeOutcome.model_validate_json(row["payload"])
        if (fingerprint(outcome.model_dump(mode="json")) != row["payload_hash"]
                or outcome != evaluate_outcome(outcome.source, outcome.policy, outcome.created_at)
                or outcome.source.workspace is not self.repo.workspace
                or outcome.source.run_id != row["run_id"] or outcome.source.mode != row["mode"]
                or outcome.source.source_id != row["source_id"] or outcome.outcome_id != row["outcome_id"]
                or outcome.policy_hash != row["policy_hash"]
                or outcome.source_fingerprint != row["source_fingerprint"]):
            raise ValueError("outcome integrity failed")
        return outcome

    def persist(self, outcome: TradeOutcome, journal: JournalService) -> bool:
        outcome = TradeOutcome.model_validate_json(outcome.model_dump_json())
        expected = evaluate_outcome(outcome.source, outcome.policy, outcome.created_at)
        if outcome != expected:
            raise ValueError("outcome differs from deterministic evaluation")
        if outcome.source.workspace is not self.repo.workspace:
            raise ValueError("outcome outside workspace")
        self.repo.assert_run_scope(outcome.source.run_id)
        with self.repo.engine.begin() as c:
            if self.repo.engine.dialect.name == "sqlite":
                c.exec_driver_sql("BEGIN IMMEDIATE")
            existing = c.execute(outcomes.select().where(outcomes.c.outcome_id == outcome.outcome_id)).mappings().first()
            if existing:
                self._decode(existing)
                if existing["source_fingerprint"] != outcome.source_fingerprint:
                    raise ValueError("closed source changed after immutable outcome")
                return False
            c.execute(outcomes.insert().values(outcome_id=outcome.outcome_id, workspace=self.repo.workspace.value,
                      run_id=outcome.source.run_id, mode=outcome.source.mode, source_id=outcome.source.source_id,
                      policy_hash=outcome.policy_hash, source_fingerprint=outcome.source_fingerprint,
                      payload_hash=fingerprint(outcome.model_dump(mode="json")),
                      closed_at=outcome.source.closed_at.astimezone(UTC).isoformat(),
                      payload=outcome.model_dump_json()))
            self.repo.append(outcome.source.run_id, EventType.OUTCOME.value,
                             {"outcome_id": outcome.outcome_id, "source_id": outcome.source.source_id,
                              "mode": outcome.source.mode, "policy_hash": outcome.policy_hash,
                              "status": outcome.status, "reward": outcome.reward,
                              "source_fingerprint": outcome.source_fingerprint,
                              "outcome_fingerprint": fingerprint(outcome.model_dump(mode="json"))},
                             journal.clock(), journal.current_cycle, connection=c)
        return True


class CollectionReport(BaseModel):
    created: list[str] = []
    unchanged: int = 0
    errors: dict[str, str] = {}


class OutcomeEngine:
    def __init__(self, repo: JournalRepository, journal: JournalService, policy: RewardPolicy) -> None:
        self.repo, self.journal, self.policy = repo, journal, policy
        self.store = OutcomeRepository(repo)

    def collect_run(self, run_id: str, *, include_existing: bool = True) -> CollectionReport:
        if self.repo.get_run(run_id) is None:
            raise ValueError("run inconnu ou hors workspace")
        demo_query = trades.select().where(trades.c.workspace == self.repo.workspace.value,
                                          trades.c.run_id == run_id, trades.c.status == "CLOSED")
        paper_query = paper_positions.select().where(paper_positions.c.workspace == self.repo.workspace.value,
                       paper_positions.c.run_id == run_id, paper_positions.c.status != "OPEN",
                       paper_positions.c.closed_at.is_not(None))
        if not include_existing:
            for mode, id_col in (("DEMO", trades.c.trade_id), ("PAPER", paper_positions.c.paper_id)):
                exists = outcomes.select().where(outcomes.c.workspace == self.repo.workspace.value,
                         outcomes.c.run_id == run_id, outcomes.c.mode == mode, outcomes.c.source_id == id_col,
                         outcomes.c.policy_hash == self.policy.policy_hash).exists()
                if mode == "DEMO":
                    demo_query = demo_query.where(~exists)
                else:
                    paper_query = paper_query.where(~exists)
        with self.repo.engine.connect() as c:
            sources: list[tuple[str, Any]] = [("DEMO", self.repo._trade(row)) for row in c.execute(demo_query)]
            sources += [("PAPER", dict(row._mapping)) for row in c.execute(paper_query)]
        if not sources and not include_existing:
            return CollectionReport()
        ok, reason = self.repo.verify_chain(run_id)
        if not ok:
            raise ValueError(f"journal integrity failed: {reason}")
        events = self.repo.events(run_id, [EventType.POSITION_OPENED.value, EventType.POSITION_UPDATE.value])
        report = CollectionReport()
        for mode, row in sources:
            source_id = row.trade_id if mode == "DEMO" else row["paper_id"]
            try:
                if mode == "DEMO":
                    opening = next((e for e in events if e.type == EventType.POSITION_OPENED.value
                                    and e.payload.get("trade", {}).get("trade_id") == row.trade_id), None)
                    incidents = [e for e in events if e.type == EventType.POSITION_UPDATE.value
                                 and e.payload.get("ticket") == row.ticket and e.payload.get("alert") == "SL SUPPRIMÉ"
                                 and e.ts <= row.closed_at]
                    sl = opening.payload["trade"].get("stop_loss") if opening else None
                    source = OutcomeInput(workspace=self.repo.workspace, run_id=run_id, mode="DEMO", source_id=row.trade_id,
                              proposal_id=row.proposal_id, opportunity_id=row.opportunity_id,
                              strategy_id=row.strategy_id, strategy_version=row.strategy_version, symbol=row.symbol, side=row.side,
                              currency=row.account_currency, opened_at=row.opened_at, closed_at=row.closed_at,
                              entry_price=row.entry_executed, exit_price=row.close_price, original_volume=row.volume,
                              price_value_per_lot=row.price_value_per_lot, initial_risk=row.risk_amount,
                              gross_pnl=row.pnl_gross, commission_cashflow=row.commission, swap_cashflow=row.swap, net_pnl=row.net_pnl,
                              mae_amount=abs(min(row.mae, 0)), mfe_amount=max(row.mfe, 0), excursion_samples=row.excursion_samples,
                              protected_initial=sl is not None if opening else None, protection_incidents=len(incidents),
                              evidence_hashes=tuple([opening.hash] if opening else []) + tuple(e.hash for e in incidents),
                              adopted=row.adopted, cost_basis="BROKER_REPORTED_DEALS_SAMPLED_GROSS_EXCURSIONS")
                else:
                    intent = json.loads(row["intent_json"]) if row.get("intent_json") else {}
                    source = OutcomeInput(workspace=self.repo.workspace, run_id=run_id, mode="PAPER", source_id=row["paper_id"],
                              proposal_id=intent.get("proposal_id"), opportunity_id=intent.get("opportunity_id"),
                              strategy_id=intent.get("strategy_id", "UNKNOWN"), strategy_version=intent.get("strategy_version", "?"),
                              symbol=row["symbol"], side=row["side"], currency=row.get("account_currency"),
                              opened_at=datetime.fromisoformat(row["opened_at"]), closed_at=datetime.fromisoformat(row["closed_at"]),
                              entry_price=row["entry_price"], exit_price=row["exit_price"], original_volume=row.get("original_volume") or row["volume"],
                              price_value_per_lot=row.get("price_value_per_lot"), initial_risk=row.get("initial_risk"),
                              gross_pnl=row.get("realized_pnl"), commission_cashflow=0, swap_cashflow=0, net_pnl=row.get("realized_pnl"),
                              mae_amount=abs(row["mae_amount"]) if row.get("mae_amount") is not None else None,
                              mfe_amount=row.get("mfe_amount"), excursion_samples=row.get("excursion_samples") or 0,
                              protected_initial=intent.get("stop_loss") is not None if intent else None,
                              cost_basis="PAPER_SPREAD_EMBEDDED_COMMISSION_SWAP_ZERO_MODELED")
                outcome = evaluate_outcome(source, self.policy, self.journal.clock())
                if self.store.persist(outcome, self.journal):
                    report.created.append(outcome.outcome_id)
                else:
                    report.unchanged += 1
            except (ValueError, IntegrityError) as exc:
                report.errors[source_id] = str(exc)
        return report


def outcome_summary(rows: list[TradeOutcome]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[TradeOutcome]] = {}
    for row in rows:
        groups.setdefault((row.source.mode, row.source.currency or "UNKNOWN", row.policy_hash), []).append(row)
    result = []
    for (mode, currency, policy_hash), group in sorted(groups.items()):
        rewards = [r.reward for r in group if r.reward is not None]
        result.append({"mode": mode, "currency": currency, "policy_hash": policy_hash,
                       "policy_version": group[0].policy.version, "outcomes": len(group),
                       "eligible": sum(r.status == "ELIGIBLE" for r in group),
                       "net_pnl": sum(r.source.net_pnl for r in group if r.source.net_pnl is not None),
                       "mean_reward": sum(rewards) / len(rewards) if rewards else None})
    return result
