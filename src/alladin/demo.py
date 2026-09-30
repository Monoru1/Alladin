"""`python -m alladin demo` : banc d'essai 100 % simulé (MockBroker + MockAgent). Aucun MT5, aucun réseau."""

from __future__ import annotations

import tempfile
from collections import Counter
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

from alladin.agents.mock import MockAgent
from alladin.brokers.mock import MockBroker
from alladin.challenge.profiles import load_profile
from alladin.core.config import Settings
from alladin.core.enums import EntryType, MarketRegime, RunState, Side
from alladin.core.errors import IrreversibleStateError
from alladin.core.models import TradeIntent
from alladin.execution.models import ExecStatus
from alladin.market.universe import MarketUniverse
from alladin.orchestration.bootstrap import Components, build_services
from alladin.report import money, status_block

Out = Callable[[str], None]


def _intent(
    c: Components,
    symbol: str,
    side: Side,
    risk_pct: float | None,
    sl_pips: float | None,
    tp_pips: float = 50,
    **over: object,
) -> TradeIntent:
    b = c.broker
    tick, spec = b.tick(symbol), b.symbol_spec(symbol)
    assert tick is not None and spec is not None
    pip, px, now = spec.point * 10, (tick.ask if side is Side.BUY else tick.bid), b.now()
    data: dict[str, object] = dict(
        run_id=c.run.run_id, agent="demo", instrument=symbol, side=side, strategy_id="TREND-01", strategy_version="1.0.0",
        market_regime=MarketRegime.TREND, entry_type=EntryType.MARKET, entry=px,
        stop_loss=None if sl_pips is None else round(px - side.sign * sl_pips * pip, spec.digits),
        take_profit=round(px + side.sign * tp_pips * pip, spec.digits),
        requested_risk_pct_of_working_capital=risk_pct if risk_pct is not None else 1.0, confidence=0.7,
        reason="démo", created_at=now, expires_at=now + timedelta(minutes=10),
    )  # fmt: skip
    data.update(over)
    return TradeIntent(**data)


def _submit(c: Components, out: Out, label: str, intent: TradeIntent) -> ExecStatus:
    res = c.execution.submit(intent)
    if res.executed and res.decision:
        d = res.decision
        extra = f"  [réduit : {'; '.join(d.adjustments)}]" if d.adjustments else ""
        out(
            f"  {label:<44} -> APPROVED   {d.volume:.2f} lots, risque {money(d.risk_amount)} ({d.risk_pct_of_equity:.2f}% equity){extra}"
        )
    else:
        out(f"  {label:<44} -> {res.status.value}")
        for m in res.messages:
            out(f"      - {m}")
    return res.status


def _hit(c: Components, symbol: str, side: Side, target: str) -> None:
    """Fait toucher le TP ou le SL de la dernière position ouverte sur `symbol`."""
    b: MockBroker = c.broker  # type: ignore[assignment]
    pos = next(p for p in b.positions() if p.symbol == symbol and p.side is side)
    level = pos.tp if target == "TP" else pos.sl
    assert level is not None
    tick = b.tick(symbol)
    assert tick is not None
    spread = tick.ask - tick.bid
    b.set_price(
        symbol, level if side is Side.BUY else level - spread, (level + spread) if side is Side.BUY else level
    )
    c.monitor.sync()


def _reset_price(c: Components, symbol: str, bid: float) -> None:
    b: MockBroker = c.broker  # type: ignore[assignment]
    b.set_price(symbol, bid)


def _header(c: Components, out: Out, agent: str) -> None:
    acct = c.broker.account_info()
    c.monitor.sync()
    rep = c.run.watchdog.update(acct, c.broker.now())
    uni = MarketUniverse(c.broker, c.profile.universe).discover()
    cats = ", ".join(f"{v} {k.lower()}" for k, v in uni.by_category.items())
    out(
        status_block(
            run_id=c.run.run_id,
            mode="demo",
            account=acct,
            report=rep,
            working_capital_pct=c.profile.risk.working_capital_pct,
            max_trade_risk_pct=c.profile.risk.max_trade_risk_pct_of_working_capital,
            universe=f"{len(uni.members)} instruments découverts ({cats}) / {uni.total_discovered} au total",
            broker=c.broker.name,
            agent=agent,
        )
    )


def _footer(c: Components, out: Out) -> None:
    acct = c.broker.account_info()
    rep = c.run.watchdog.update(acct, c.broker.now())
    out("\n--- État final ---")
    out(
        f"Run {c.run.run_id}: {rep.run_state.value} | phase {rep.phase_number} | equity {money(acct.equity)} | progression {rep.profit_pct:+.2f} %"
    )
    for v in rep.violations:
        out(f"  violation [{v.source.value}] {v.rule}: {v.message}")
    counts = Counter(e.type for e in c.repo.events(c.run.run_id))
    ok, msg = c.repo.verify_chain(c.run.run_id)
    out(
        f"Journal: {sum(counts.values())} événements ({', '.join(f'{k}={v}' for k, v in sorted(counts.items()))})"
    )
    out(f"Intégrité du journal (chaîne de hachage): {'OK' if ok else 'ALTÉRÉ'} — {msg}")


def run_demo(scenario: str, out: Out = print, db_url: str = "sqlite://") -> Components:
    settings = Settings(_env_file=None)
    profile = load_profile(settings.default_profile, settings.profiles_dir)
    broker = MockBroker(balance=profile.initial_balance)
    tmp = Path(tempfile.mkdtemp(prefix="alladin-demo-"))
    c = build_services(settings, broker, create_run=True, db_url=db_url, killswitch_path=tmp / "KILL_SWITCH")
    assert c is not None
    _header(c, out, "mock")
    c.manager.start(c.run, broker.account_info())
    out(f"\nRun démarré ({c.run.run_id} -> RUNNING). Scénario : {scenario}\n")

    if scenario == "basic":
        _basic(c, out)
    elif scenario == "fail":
        _fail(c, out)
    elif scenario == "pass":
        _pass(c, out)
    else:
        raise ValueError(f"scénario inconnu : {scenario}")
    _footer(c, out)
    return c


def _basic(c: Components, out: Out) -> None:
    b: MockBroker = c.broker  # type: ignore[assignment]
    out("1) Trades simulés passant par le RiskEngine")
    _submit(c, out, "BUY EURUSD  risque 4 % (SL 20 pips)", _intent(c, "EURUSD", Side.BUY, 4, 20))
    _hit(c, "EURUSD", Side.BUY, "TP")
    acct = b.account_info()
    out(f"     TP touché -> equity {money(acct.equity)}")
    _submit(c, out, "BUY EURUSD  SANS stop loss", _intent(c, "EURUSD", Side.BUY, 4, None))
    _submit(c, out, "BUY EURUSD  risque demandé 12 % (> plafond 8 %)", _intent(c, "EURUSD", Side.BUY, 12, 20))
    out("\n2) Exposition USD corrélée (BUY EURUSD + BUY GBPUSD + SELL USDCHF)")
    _submit(c, out, "BUY EURUSD  risque 8 %", _intent(c, "EURUSD", Side.BUY, 8, 20))
    _submit(c, out, "BUY GBPUSD  risque 8 %", _intent(c, "GBPUSD", Side.BUY, 8, 20))
    _submit(c, out, "SELL USDCHF risque 8 %", _intent(c, "USDCHF", Side.SELL, 8, 20))
    out("\n3) Un cycle autonome (dry-run, agent MOCK) : NO TRADE est une décision valide")
    engine = c.engine(MockAgent(), execute=False)
    res = engine.run_cycle()
    out(f"  cycle {res.cycle}: {res.decision} — {res.reason}")
    out(f"  shortlist: {', '.join(res.shortlist) or '(vide)'}")


def _fail(c: Components, out: Out) -> None:
    b: MockBroker = c.broker  # type: ignore[assignment]
    out(
        "Un trade perdant (SL), puis un événement externe (gap) de -5 200 $ dépasse la perte journalière de 5 %."
    )
    _submit(c, out, "BUY EURUSD  risque 8 %", _intent(c, "EURUSD", Side.BUY, 8, 20))
    _hit(c, "EURUSD", Side.BUY, "SL")
    out(f"     SL touché -> equity {money(b.account_info().equity)}")
    b.inject_pnl(-5_200)
    c.monitor.sync()
    out(
        f"     perte externe injectée -> equity {money(b.account_info().equity)}  => run {c.run.watchdog.run_state.value}"
    )
    _submit(c, out, "BUY EURUSD  (après FAILED)", _intent(c, "EURUSD", Side.BUY, 1, 20))
    try:
        c.manager.resume(c.run)
    except IrreversibleStateError as exc:
        out(f"  reprise refusée : {exc}")
    try:
        c.repo.update_run(c.run.run_id, "RUNNING", 1, {}, b.now())
    except Exception as exc:
        out(f"  réécriture en base refusée : {type(exc).__name__} (run FAILED immuable)")


def _pass(c: Components, out: Out) -> None:
    b: MockBroker = c.broker  # type: ignore[assignment]
    out("Une série de trades gagnants (1 par jour, TP 2,5R) jusqu'à la validation des deux phases.")
    last_phase = 1
    for day in range(1, 40):
        b.advance(timedelta(days=1))
        _reset_price(c, "EURUSD", 1.0850)
        if (
            _submit(
                c, out, f"J{day:02d} BUY EURUSD risque 8 %", _intent(c, "EURUSD", Side.BUY, 8, 20, tp_pips=50)
            )
            is not ExecStatus.EXECUTED
        ):
            break
        _hit(c, "EURUSD", Side.BUY, "TP")
        rep = c.run.watchdog.update(b.account_info(), b.now())
        out(
            f"       equity {money(b.account_info().equity)} | phase {rep.phase_number} | progression {rep.profit_pct:+.2f} % | {rep.run_state.value}"
        )
        if rep.phase_number != last_phase:
            out(f"  >>> PHASE {last_phase} VALIDÉE -> phase {rep.phase_number}")
            last_phase = rep.phase_number
        if rep.run_state is RunState.PASSED:
            out("  >>> CHALLENGE PASSED")
            break
