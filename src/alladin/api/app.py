"""ALLADIN Mission Control : API strictement GET, alimentée par le journal et le broker."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
from alladin.core.workspace import WorkspaceId
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
    workspace = repo.workspace
    app = FastAPI(title=f"{workspace.value} Mission Control", description="Lecture seule — aucune route de trading.")

    def latest(run_id: str | None = None) -> Any:
        records = repo.list_runs()
        rec = repo.get_run(run_id) if run_id else (records[-1] if records else None)
        if rec is None:
            raise HTTPException(404, "run inconnu")
        return rec

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        html = INDEX.read_text(encoding="utf-8")
        if workspace is WorkspaceId.JAFAR:
            html = html.replace("ALLADIN", "JAFAR")
            theme = "<style>:root{--accent:#ef5350;--accent-dim:#ef535018;--cyan:#ff8a80;--cyan-dim:#ff8a8018}</style>"
            banner = '<div role="status" style="padding:12px;color:#ff8a80;text-align:center">JAFAR · OBSERVE uniquement · budget de référence virtuel · aucune stratégie active</div>'
            html = html.replace("</head>", theme + "</head>").replace("<body>", "<body>" + banner)
        return html

    @app.get("/api/workspace")
    def workspace_info() -> dict[str, Any]:
        caps = broker.capabilities() if broker else None
        return {"workspace": workspace.value, "allowed_modes": ["OBSERVE"] if workspace is WorkspaceId.JAFAR
                else ["OBSERVE", "PAPER", "DEMO"],
                "account_semantics": "virtual_reference_budget" if workspace is WorkspaceId.JAFAR else "broker_account",
                "capabilities": {"is_24_7": caps.is_24_7, "can_open_position": caps.can_open_position,
                                 "has_funding_rate": caps.has_funding_rate,
                                 "has_maker_taker_fees": caps.has_maker_taker_fees,
                                 "asset_categories": sorted(c.value for c in caps.supported_asset_categories)}
                if caps else None}

    @app.get("/health")
    def health() -> dict[str, Any]:
        acct = broker.account_info() if broker else None
        observed_at = datetime.now(UTC)
        runs = repo.list_runs()
        rec = next((r for r in reversed(runs) if r.kind == "RUN"), None)
        last_cycle_at: str | None = None
        run_mode: str | None = None
        if rec:
            evts = repo.events(rec.run_id, ["cycle.end"], limit=1, desc=True)
            if evts:
                last_cycle_at = evts[0].ts.isoformat()
            modes = repo.events(rec.run_id, ["mode.change"], limit=1, desc=True)
            if modes:
                run_mode = modes[0].payload.get("run_mode")
        last_dt = datetime.fromisoformat(last_cycle_at) if last_cycle_at else None
        stale = last_dt is None or observed_at - last_dt.astimezone(UTC) > timedelta(minutes=2)
        return {
            "status": "ok",
            "workspace": workspace.value,
            "observe_only": workspace is WorkspaceId.JAFAR,
            "reference_budget_virtual": workspace is WorkspaceId.JAFAR,
            "run_id": rec.run_id if rec else None,
            "run_kind": rec.kind if rec else None,
            "run_mode": run_mode,
            "account_type": acct.account_type.value if acct else None,
            "broker_connected": acct is not None,
            "daemon_state": rec.state if rec else None,
            "observed_at": observed_at.isoformat(),
            "stale": stale,
            "demo": acct is not None and acct.account_type is AccountType.DEMO,
            "last_cycle_at": last_cycle_at,
        }

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
        if workspace is WorkspaceId.JAFAR:
            return []
        rows = StrategyRegistry.from_config(settings.strategies_dir).catalogue()
        stats = {s.key: s for s in journal.stats("strategy")}
        for row in rows:
            row["performance"] = stats[row["id"]].model_dump() if row["id"] in stats else None
        return rows

    @app.get("/api/research")
    def research() -> dict[str, Any]:
        rr = ResearchRepository.from_engine(repo.engine, repo.workspace)
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


    @app.get("/api/outcomes")
    def trade_outcomes(run_id: str | None = None, limit: int = Query(200, ge=1, le=1000)) -> dict[str, Any]:
        from alladin.research.outcomes import OutcomeRepository, outcome_summary
        rid = latest(run_id).run_id
        try:
            rows = OutcomeRepository(repo, read_only=True).list(rid, limit=limit)
        except ValueError as exc:
            raise HTTPException(409, "outcome integrity failed") from exc
        return {"workspace": workspace.value, "run_id": rid, "limit": limit,
                "summary_scope": "RETURNED_ROWS", "summary": outcome_summary(rows),
                "outcomes": [row.model_dump(mode="json") for row in rows]}

    @app.get("/api/opportunities")
    def opportunities(run_id: str | None = None, cycle_id: str | None = None,
                      limit: int = Query(200, ge=1, le=1000)) -> dict[str, Any]:
        from alladin.journal.models import EventType
        rid = latest(run_id).run_id
        types = [EventType.OPPORTUNITY_CREATED.value, EventType.OPPORTUNITY_REJECTED.value]
        events = repo.events(rid, types, limit=limit, desc=True, cycle_id=cycle_id)
        qualified = [e.payload for e in events if e.type == EventType.OPPORTUNITY_CREATED.value]
        filtered = [e.payload for e in events if e.type == EventType.OPPORTUNITY_REJECTED.value]
        return {
            "run_id": rid,
            "cycle_id": cycle_id,
            "qualified": qualified,
            "filtered": filtered,
            "total_qualified": len(qualified),
            "total_filtered": len(filtered),
        }

    @app.get("/api/btc/experiments")
    def btc_experiments() -> dict[str, Any]:
        """BTC Three-Way Experiment status (read-only)."""
        # Look for BTC experiment data in journal
        try:
            runs = repo.list_runs()
            if not runs:
                return {"experiments": [], "active": 0, "total": 0}
            rid = next((r.run_id for r in reversed(runs) if r.kind == "RUN"), runs[-1].run_id)
            btc_events = repo.events(rid, ["btc.experiment"], limit=10, desc=True)
            experiments = [e.payload for e in btc_events] if btc_events else []
            return {"experiments": experiments, "active": 0, "total": len(experiments)}
        except Exception:
            return {"experiments": [], "active": 0, "total": 0}

    return app
