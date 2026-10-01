"""ALLADIN Mission Control : API strictement GET, alimentée par le journal et le broker."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from alladin.brokers.base import BrokerAdapter
from alladin.challenge.models import WatchdogState
from alladin.challenge.profiles import load_profile
from alladin.challenge.watchdog import ChallengeWatchdog
from alladin.core.config import Settings, get_settings
from alladin.core.enums import AccountType
from alladin.execution.models import comment_matches
from alladin.journal.models import EventType
from alladin.journal.repository import JournalRepository
from alladin.journal.service import JournalService
from alladin.market.universe import MarketUniverse
from alladin.research.models import StrategyStatus
from alladin.research.repository import ResearchRepository
from alladin.risk import sizing
from alladin.risk.exposure import compute_exposure
from alladin.strategies.registry import StrategyRegistry

INDEX = Path(__file__).with_name("static") / "index.html"


def create_app(settings: Settings | None = None, repo: JournalRepository | None = None,
               broker: BrokerAdapter | None = None) -> FastAPI:
    settings = settings or get_settings()
    repo = repo or JournalRepository.from_url(settings.db_url)
    journal = JournalService(repo)
    market_cache: dict[str, Any] = {}
    app = FastAPI(title="ALLADIN Mission Control", description="Lecture seule — aucune route de trading.")

    def latest(run_id: str | None = None) -> Any:
        records = repo.list_runs()
        rec = repo.get_run(run_id) if run_id else (records[-1] if records else None)
        if rec is None:
            raise HTTPException(404, "run inconnu")
        return rec

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return INDEX.read_text(encoding="utf-8")

    @app.get("/health")
    def health() -> dict[str, Any]:
        acct = broker.account_info() if broker else None
        return {"status": "ok", "broker_connected": broker is not None,
                "demo": acct is None or acct.account_type is AccountType.DEMO}

    @app.get("/api/overview")
    def overview(run_id: str | None = None) -> dict[str, Any]:
        rec = latest(run_id)
        acct = broker.account_info() if broker else None
        profile = load_profile(rec.profile_id, settings.profiles_dir)
        challenge = ChallengeWatchdog(profile, WatchdogState.model_validate(rec.watchdog_state))
        report = challenge.report(acct, broker.now()).model_dump(mode="json") if acct and broker else None
        equity = acct.equity if acct else float(rec.watchdog_state.get("last_equity") or rec.initial_balance)
        wc = sizing.working_capital(equity, profile.risk.working_capital_pct)
        cap = sizing.max_trade_risk(wc, profile.risk.max_trade_risk_pct_of_working_capital)
        mine = [p for p in broker.positions() if p.magic == rec.magic and
                comment_matches(p.comment, rec.run_id, rec.magic)] if broker else []
        specs = {p.symbol: s for p in mine if (s := broker.symbol_spec(p.symbol)) is not None} if broker else {}
        exposure = compute_exposure(mine, specs)
        ok, detail = repo.verify_chain(rec.run_id)
        return {"run": rec.model_dump(mode="json", exclude={"watchdog_state", "account"}),
                "account": acct.model_dump(mode="json") if acct else None, "challenge": report,
                "risk": {"working_capital": wc, "max_trade_risk": cap,
                         "open_risk": exposure.total_open_risk,
                         "available_risk": max(0.0, wc * profile.risk.max_total_open_risk_pct_of_wc / 100 - exposure.total_open_risk),
                         "exposure": exposure.model_dump(mode="json")},
                "execution_blocked": acct is not None and acct.account_type is not AccountType.DEMO,
                "journal": {"ok": ok, "detail": detail}}

    @app.get("/api/runs")
    def runs() -> list[dict[str, Any]]:
        return [r.model_dump(mode="json", exclude={"watchdog_state", "account"}) for r in repo.list_runs()]

    @app.get("/api/runs/{run_id}/cycles")
    def cycles(run_id: str) -> list[dict[str, Any]]:
        latest(run_id)
        return repo.cycles(run_id)

    @app.get("/api/runs/{run_id}/cycles/{cycle_id}")
    def cycle(run_id: str, cycle_id: str) -> dict[str, Any]:
        rows = repo.events(latest(run_id).run_id, cycle_id=cycle_id)
        if not rows:
            raise HTTPException(404, "cycle inconnu")
        return {"cycle_id": cycle_id, "events": [e.model_dump(mode="json") for e in rows]}

    @app.get("/api/positions")
    def positions(run_id: str | None = None) -> list[dict[str, Any]]:
        rec = latest(run_id)
        if broker is None:
            return []
        trades = {t.ticket: t for t in repo.trades_for_run(rec.run_id, "OPEN") if t.ticket is not None}
        result = []
        for pos in broker.positions():
            if pos.magic != rec.magic or not comment_matches(pos.comment, rec.run_id, rec.magic):
                continue
            trade = trades.get(pos.ticket)
            row = pos.model_dump(mode="json")
            row.update(trade=trade.model_dump(mode="json") if trade else None,
                       r_current=pos.profit / trade.risk_amount if trade and trade.risk_amount else None,
                       distance_to_sl=abs(pos.price_current - pos.sl) if pos.sl else None,
                       distance_to_tp=abs(pos.tp - pos.price_current) if pos.tp else None)
            result.append(row)
        return result

    @app.get("/api/market")
    def market(run_id: str | None = None) -> dict[str, Any]:
        rec = latest(run_id)
        rows = repo.events(rec.run_id, [EventType.SCAN.value], limit=1, desc=True)
        result = dict(rows[0].payload) if rows else {"status": "N/A", "candidates": [], "rejections": {}}
        if broker and not market_cache:
            profile = load_profile(rec.profile_id, settings.profiles_dir)
            universe = MarketUniverse(broker, profile.universe).discover()
            market_cache.update(broker_symbols=universe.total_discovered,
                                universe_size=len(universe.members), by_category=universe.by_category)
        return {**market_cache, **result}

    @app.get("/api/journal")
    def events(run_id: str | None = None, cycle_id: str | None = None,
               event: str | None = None, limit: int = Query(300, ge=1, le=1000)) -> list[dict[str, Any]]:
        rows = repo.events(latest(run_id).run_id, [event] if event else None,
                           limit=limit, desc=True, cycle_id=cycle_id)
        return [e.model_dump(mode="json") for e in rows]

    @app.get("/api/strategies")
    def strategies() -> list[dict[str, Any]]:
        rows = StrategyRegistry.from_config(settings.strategies_dir).catalogue()
        stats = {s.key: s for s in journal.stats("strategy")}
        for row in rows:
            row["performance"] = stats[row["id"]].model_dump() if row["id"] in stats else None
        return rows

    @app.get("/api/research")
    def research() -> dict[str, Any]:
        rr = ResearchRepository.from_engine(repo.engine)
        sources = [s.model_dump(mode="json") for s in rr.list_sources()]
        findings = [f.model_dump(mode="json") for f in rr.list_findings()]
        hypotheses = [h.model_dump(mode="json") for h in rr.list_hypotheses()]
        versions = [v.model_dump(mode="json") for v in rr.list_versions()]
        experiments = [e.model_dump(mode="json") for e in rr.list_experiments()]
        results: list[dict[str, Any]] = []
        for exp in rr.list_experiments():
            r = rr.get_result(exp.experiment_id)
            if r:
                results.append(r.model_dump(mode="json"))
        return {
            "pipeline": [status.value for status in StrategyStatus],
            "sources": sources,
            "findings": findings,
            "hypotheses": hypotheses,
            "versions": versions,
            "experiments": experiments,
            "results": results,
            "stats": rr.stats(),
        }

    return app
