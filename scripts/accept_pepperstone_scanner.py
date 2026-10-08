"""Pepperstone MT5 read-only, bounded scanner acceptance (DECISION-021/031-035).

Usage: python scripts/accept_pepperstone_scanner.py
No execution service, order_send, account mutations, or mode promotion.
"""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

import yaml

from alladin.brokers.mt5 import MT5Broker
from alladin.challenge.models import UniverseRules
from alladin.core.enums import AccountType, Timeframe
from alladin.market.scanner import MarketScanner
from alladin.market.universe import MarketUniverse

DEFAULT_SYMBOLS = ("EURUSD", "GBPUSD", "USDJPY", "NAS100", "US500", "US30", "XAUUSD", "XAGUSD")


class BoundedPepperstoneBroker(MT5Broker):
    """Limit discovery before scanning; never touch unrelated Market Watch symbols."""

    def __init__(self, symbols: tuple[str, ...]) -> None:
        super().__init__()
        self.symbols = frozenset(symbols)

    def list_symbols(self):
        return [s for s in super().list_symbols() if s.symbol in self.symbols]


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Pepperstone scanner acceptance")
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--bars", type=int, default=300)
    parser.add_argument("--max-tick-age", type=float, default=180.0)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    if not 100 <= args.bars <= 1000:
        parser.error("--bars must be between 100 and 1000")
    if not 0 < args.max_tick_age <= 1800:
        parser.error("--max-tick-age must be between 0 and 1800 seconds")
    symbols = tuple(dict.fromkeys(args.symbols))
    if not symbols or len(symbols) > 12:
        parser.error("Select between 1 and 12 symbols per bounded run")

    rules_path = Path("config/universes/pepperstone_multimarket_research.yaml")
    rules = UniverseRules.model_validate(yaml.safe_load(rules_path.read_text(encoding="utf-8")))
    broker = BoundedPepperstoneBroker(symbols)
    broker.connect()
    try:
        account = broker.account_info()
        if account.server != "PepperstoneUK-Demo" or account.account_type is not AccountType.DEMO:
            raise SystemExit("FAIL CLOSED: requires PepperstoneUK-Demo account")
        if broker.offset_source != "auto":
            raise SystemExit("FAIL CLOSED: broker clock offset is not auto-verified")

        universe = MarketUniverse(broker, rules)
        discovered = universe.discover()
        if any(s not in {m.symbol for m in discovered.members} for s in symbols):
            print("NOTICE: Some requested symbols are absent or excluded from universe")
        scanner = MarketScanner(
            broker, universe, rules,
            primary=Timeframe.H1,
            timeframes=(Timeframe.M15, Timeframe.H1, Timeframe.H4, Timeframe.D1),
            bars_count=args.bars,
            max_tick_age_s=args.max_tick_age,
        )
        start = time.monotonic()
        report = scanner.scan(limit=len(symbols))
        elapsed = round(time.monotonic() - start, 3)
        candidates = [
            {"symbol": c.symbol, "category": c.category.value, "regime": c.regime.value,
             "score": c.score, "spread_atr_ratio": c.spread_atr_ratio}
            for c in report.candidates
        ]
        result = {
            "mode": "OBSERVE_READ_ONLY",
            "broker": account.server,
            "offset_source": broker.offset_source,
            "offset_hours": broker.server_utc_offset_hours,
            "requested": list(symbols),
            "eligible": discovered.by_category,
            "analysed": report.analysed,
            "requested_count": len(symbols),
            "candidate_count": len(candidates),
            "rejected_requested_count": sum(sym in report.rejected for sym in symbols),
            "regime_counts": report.regime_counts,
            "candidates": candidates,
            "rejections": {k: v for k, v in report.rejected.items() if k in symbols},
            "rejection_reasons": dict(Counter(reason for sym, reasons in report.rejected.items()
                                              if sym in symbols for reason in reasons)),
            "notes": report.notes,
            "duration_seconds": elapsed,
            "execution": "NOT_INVOKED",
            "policy_and_portfolio_approval": "NOT_EVALUATED",
            "scores_are_probabilities": False,
        }
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    finally:
        broker.disconnect()


if __name__ == "__main__":
    main()
