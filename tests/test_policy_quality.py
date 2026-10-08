"""Quality reports retain missing evidence and never confer execution permission."""
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from alladin.challenge.capital_metrics import CapitalLedger
from alladin.challenge.policy_gate import GateVerdict, ProposedAction
from alladin.challenge.policy_quality import PolicyProbe, build_policy_quality_report
from tests.test_policy_compliance_simulation import context


def probe(**changes):
    data = dict(probe_id="p1", account_ref="synthetic-1", action=ProposedAction.OPEN,
                context=context("funded_standard"), expected_verdict=GateVerdict.BLOCK,
                expected_reason="FIRM_RESTRICTED_EVENT")
    data.update(changes)
    return PolicyProbe(**data)


def test_labelled_report_retains_audit_evidence_without_readiness():
    report = build_policy_quality_report((probe(),))
    assert report["expectation_status"] == "PASS"
    assert report["reason_counts"] == {"FIRM_RESTRICTED_EVENT": 1}
    assert report["records"][0]["event_ids"] == ["CPI"]
    assert report["records"][0]["profile"]["version"] == "fixture-2026-10-08"
    assert report["records"][0]["calendar"]["source"] == "synthetic"
    assert all(v is None for v in report["measurements"].values())
    assert report["execution_authorized"] is False
    assert report["runtime_integrated"] is False and report["unattended_qualified"] is False
    assert json.loads(json.dumps(report, allow_nan=False)) == report


@pytest.mark.parametrize("change", [{"expected_verdict": GateVerdict.ALLOW}, {"expected_reason": "wrong"}])
def test_mismatch_is_failure(change):
    report = build_policy_quality_report((probe(**change),))
    assert report["expectation_status"] == "FAIL" and report["expectation_mismatches"] == 1


def test_unlabelled_or_empty_is_not_pass():
    assert build_policy_quality_report(())["expectation_status"] == "UNASSESSED"
    assert build_policy_quality_report((probe(expected_verdict=None),))["expectation_status"] == "UNASSESSED"


def test_restart_duplicate_evidence_is_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        build_policy_quality_report((probe(), probe()))


def test_hold_is_not_a_confirmed_fill_and_cash_excludes_allocation():
    report = build_policy_quality_report((probe(action=ProposedAction.HOLD,
        expected_verdict=GateVerdict.ALLOW, expected_reason="NO_BROKER_TRANSACTION"),),
        ledger=CapitalLedger(200000, 500, 0, 100, 0))
    assert report["measurements"]["confirmed_fills"] is None
    assert report["capital"]["net_cash_generated"] == -600


def test_order_independent_counters_and_isolated_accounts():
    a = probe()
    b = probe(probe_id="p2", account_ref="synthetic-2", context=context("funded_swing"),
              expected_verdict=GateVerdict.DEFER, expected_reason="MACRO_VOLATILITY_WINDOW")
    first = build_policy_quality_report((a, b))
    second = build_policy_quality_report((b, a))
    assert first["verdict_counts"] == second["verdict_counts"] == {"BLOCK": 1, "DEFER": 1}
    assert len(first["records"]) == 2
    assert build_policy_quality_report((a, b)) == first


def test_script_reproduces_json(tmp_path):
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "quality.json"
    result = subprocess.run([sys.executable, str(root / "scripts/report_policy_quality.py"),
                             "--output", str(output)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text())
    assert report["samples"] == report["labelled_samples"] == 12
    assert report["expectation_mismatches"] == 0
    assert len(report["fixture_sha256"]) == 64


def test_invalid_probe_identity():
    with pytest.raises(ValueError):
        replace(probe(), account_ref=" ")


def test_refusals_data_failure_and_match_fraction_are_distinct():
    a=probe(probe_id='news')
    b=probe(probe_id='outage',context=replace(probe().context,calendar=None),
            expected_reason='CALENDAR_MISSING')
    report=build_policy_quality_report((a,b))
    assert report['refused_decisions'] == 2
    assert report['data_unavailable_decisions'] == 1
    assert report['labelled_expectation_match_fraction'] == 1.
    assert report['records'][0]['calendar']['coverage_complete'] is None
    assert report['unattended_qualified'] is False
