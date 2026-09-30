"""Calculs purs des règles de challenge (aucun état, aucun I/O)."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from alladin.challenge.models import DailyLossReference, OfficialRules


def day_key(now: datetime, rules: OfficialRules) -> str:
    """Clé de jour de trading selon le fuseau/heure de reset du profil (ex. minuit Europe/Prague)."""
    local = now.astimezone(ZoneInfo(rules.reset_timezone)) - timedelta(hours=rules.reset_hour)
    return local.date().isoformat()


def daily_loss_limit_amount(rules: OfficialRules, baseline_balance: float) -> float:
    return baseline_balance * rules.daily_loss_pct / 100


def daily_reference(rules: OfficialRules, day_start_balance: float, day_start_equity: float) -> float:
    match rules.daily_loss_reference:
        case DailyLossReference.START_BALANCE:
            return day_start_balance
        case DailyLossReference.START_EQUITY:
            return day_start_equity
        case _:
            return max(day_start_balance, day_start_equity)


def daily_floor(
    rules: OfficialRules, baseline_balance: float, day_start_balance: float, day_start_equity: float
) -> float:
    return daily_reference(rules, day_start_balance, day_start_equity) - daily_loss_limit_amount(
        rules, baseline_balance
    )


def total_floor(rules: OfficialRules, baseline_balance: float) -> float:
    return baseline_balance - baseline_balance * rules.max_total_loss_pct / 100


def target_level(baseline_balance: float, target_pct: float) -> float:
    return baseline_balance + baseline_balance * target_pct / 100


def best_day_profit(daily_closed_pnl: dict[str, float]) -> float:
    positives = [v for v in daily_closed_pnl.values() if v > 0]
    return max(positives) if positives else 0.0


def best_day_share_pct(daily_closed_pnl: dict[str, float], total_profit: float) -> float | None:
    """Part du meilleur jour dans le profit total (None si pas de profit total positif)."""
    if total_profit <= 0:
        return None
    return best_day_profit(daily_closed_pnl) / total_profit * 100
