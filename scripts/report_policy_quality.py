"""Reproduce a labelled synthetic policy report: python scripts/report_policy_quality.py.

Optional --output writes JSON. Uses no broker, network, credential or database.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from alladin.challenge.event_policy import CalendarSnapshot, EconomicEvent
from alladin.challenge.firm_policy import FirmProfile
from alladin.challenge.policy_gate import GateVerdict, PolicyContext, ProposedAction
from alladin.challenge.policy_quality import PolicyProbe, build_policy_quality_report

ROOT = Path(__file__).resolve().parents[1]


def fixture_report() -> dict[str, Any]:
    fixture = ROOT / "tests/fixtures/policy/firm_profiles.json"
    raw = fixture.read_bytes()
    data = json.loads(raw)
    if data.get("simulation_only") is not True or data.get("schema_version") != 1:
        raise ValueError("only synthetic fixture schema 1 accepted")
    now = datetime(2026, 10, 8, 12, tzinfo=UTC)
    calendar = CalendarSnapshot(now-timedelta(minutes=1), now+timedelta(minutes=1), "synthetic",
                                (EconomicEvent("CPI", now, frozenset({"XAUUSD"}), True),))
    probes = []
    for item in data["profiles"]:
        values = item["profile"]
        values["verified_at"] = datetime.fromisoformat(values["verified_at"])
        values["valid_until"] = datetime.fromisoformat(values["valid_until"])
        values["allowed_symbols"] = frozenset(values["allowed_symbols"])
        profile = FirmProfile(**values)
        identity = item["fixture_id"]
        # Explicit oracle for the release-time fixture, independent of gate implementation.
        expected_open = {"evaluation": GateVerdict.DEFER, "funded_standard": GateVerdict.BLOCK,
                         "funded_swing": GateVerdict.DEFER, "no_automation": GateVerdict.BLOCK,
                         "unknown_news": GateVerdict.BLOCK, "zero_positions": GateVerdict.BLOCK}[identity]
        expected_close = {"evaluation": GateVerdict.DEFER, "funded_standard": GateVerdict.BLOCK,
                          "funded_swing": GateVerdict.DEFER, "no_automation": GateVerdict.REVIEW,
                          "unknown_news": GateVerdict.REVIEW, "zero_positions": GateVerdict.DEFER}[identity]
        context = PolicyContext(now, "XAUUSD", 0, profile, calendar, profile.restrict_news)
        for action, expected in ((ProposedAction.OPEN, expected_open), (ProposedAction.CLOSE, expected_close)):
            probes.append(PolicyProbe(f"{identity}:{action}", identity, action, context, expected))
    report = build_policy_quality_report(tuple(probes))
    report["fixture_sha256"] = hashlib.sha256(raw).hexdigest()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = fixture_report()
    text = json.dumps(report, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0 if report["expectation_status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
