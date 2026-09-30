"""Rendu texte des états (partagé par la CLI et la démo)."""

from __future__ import annotations

from alladin.challenge.models import WatchdogReport
from alladin.core.models import AccountSnapshot
from alladin.risk import sizing


def money(x: float, ccy: str = "USD") -> str:
    sym = {"USD": "$", "EUR": "€", "GBP": "£"}.get(ccy)
    body = f"{abs(x):,.2f}" if abs(x) < 1000 and x != int(x) else f"{abs(x):,.0f}"
    sign = "-" if x < 0 else ""
    return f"{sign}{sym}{body}" if sym else f"{sign}{body} {ccy}"


def status_block(
    *,
    run_id: str,
    mode: str,
    account: AccountSnapshot,
    report: WatchdogReport,
    working_capital_pct: float,
    max_trade_risk_pct: float,
    universe: str,
    broker: str,
    agent: str,
    title: str = "ALLADIN LAB",
) -> str:
    c = account.currency
    wc = sizing.working_capital(account.equity, working_capital_pct)
    mtr = sizing.max_trade_risk(wc, max_trade_risk_pct)
    rows = [
        (f"RUN: {run_id}", None),
        (f"MODE: {mode.upper()}", None),
        ("", None),
        ("Equity:", money(account.equity, c)),
        ("Balance:", money(account.balance, c)),
        ("Floating P&L:", money(account.floating_pnl, c)),
        ("Working capital:", f"{money(wc, c)}  ({working_capital_pct:g}% equity)"),
        (
            "Max trade risk:",
            f"{money(mtr, c)}  ({max_trade_risk_pct:g}% du capital de travail = {mtr / account.equity * 100 if account.equity else 0:.2f}% equity)",
        ),
        ("", None),
        ("Phase:", f"{report.phase_number} ({report.phase_name})"),
        (
            "Target:",
            f"+{report.target_pct:g} %   (niveau {money(report.target_level, c)}, progression {report.profit_pct:+.2f} %)",
        ),
        (
            "Daily loss headroom:",
            f"{money(report.daily_headroom, c)}  (limite consommée {report.daily_loss_used_pct:.0f} %, plancher {money(report.daily_floor, c)})",
        ),
        (
            "Total loss headroom:",
            f"{money(report.total_headroom, c)}  (limite consommée {report.total_loss_used_pct:.0f} %, plancher {money(report.total_floor, c)})",
        ),
        (
            "Trading days:",
            f"{report.trading_days}/{report.min_trading_days} min   (jours écoulés {report.days_elapsed:.1f}/{report.max_days if report.max_days is not None else '∞'})",
        ),
        (
            "Best day share:",
            "n/a"
            if report.best_day_share_pct is None
            else f"{report.best_day_share_pct:.1f} %  (règle ALLADIN ≤ 50 %, optionnelle)",
        ),
        ("", None),
        ("Market universe:", universe),
        ("Broker:", broker.upper()),
        ("Agent:", agent.upper()),
    ]
    lines = [title, ""]
    for k, v in rows:
        lines.append(k if v is None else f"{k:<22}{v}")
    lines += ["", f"STATUS: {report.run_state.value}"]
    if run_id.startswith("("):  # aperçu sans run : pas de verdict sur les ordres
        pass
    elif report.run_state.value == "READY":
        lines.append("Nouveaux ordres: autorisés dès le démarrage du run (état READY)")
    elif report.blocked_reasons:
        lines.append("Nouveaux ordres: BLOQUÉS — " + "; ".join(report.blocked_reasons))
    else:
        lines.append("Nouveaux ordres: autorisés")
    for viol in report.violations:
        lines.append(f"  ! [{viol.source.value}] {viol.rule}: {viol.message}")
    return "\n".join(lines)
