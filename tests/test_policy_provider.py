import os
import subprocess
import sys
from dataclasses import replace
from datetime import timedelta

import pytest

from alladin.brain import Action
from alladin.challenge.policy_archive import PolicyArchive
from alladin.challenge.policy_dossier import DossierRevocation
from alladin.challenge.policy_gate import GateVerdict
from alladin.challenge.policy_serialization import canonical_json, evidence_sha256
from alladin.core.enums import RunMode
from alladin.orchestration.policy_control import PolicyController
from alladin.orchestration.policy_provider import ArchivedPolicyProvider
from tests.test_calendar_composite import NOW
from tests.test_policy_archive import add_batch, dossier
from tests.test_policy_control import proposal


def setup(svc, tmp_path, *, sources=("a", "b")):
    archive = PolicyArchive(tmp_path / "policy.sqlite", clock=lambda: NOW)
    d = dossier(svc)
    archive.add_dossier(d)
    for source in sources:
        add_batch(archive, source)
    provider = ArchivedPolicyProvider(
        archive=archive,
        binding=svc.run.account_binding,
        program="fixture",
        phase="funded",
        mode=RunMode.PAPER,
        open_positions=lambda p: 0,
    )
    p = proposal(svc, Action.LONG).model_copy(update={"timestamp": NOW})
    c = PolicyController(binding=svc.run.account_binding, journal=svc.journal, context_provider=provider)
    return archive, provider, p, c


def test_archived_provider_evidence_and_restart(svc, tmp_path, monkeypatch):
    monkeypatch.setattr(svc.broker, "_send", lambda *a, **kw: pytest.fail("broker send forbidden"))
    archive, provider, p, c = setup(svc, tmp_path)
    assert c.assess(p, RunMode.PAPER).verdict is GateVerdict.ALLOW
    provider.archive = PolicyArchive(archive.path, clock=lambda: NOW)
    assert c.assess(p, RunMode.PAPER).verdict is GateVerdict.ALLOW
    rows = svc.repo.events(svc.run.run_id, types=["policy.decision"])
    assert len(rows) == 1
    assert rows[0].payload["dossier_id"] == "fixture-1"
    assert len(rows[0].payload["dossier_sha256"]) == 64
    assert rows[0].payload["calendar_gaps"] == []
    assert len(rows[0].payload["calendar_batch_sha256"]) == 2


@pytest.mark.parametrize(
    "kind", [Action.LONG, Action.CLOSE, Action.PARTIAL_CLOSE, Action.MODIFY_STOP, Action.MODIFY_TARGET]
)
def test_partial_provider_fail_closed(svc, tmp_path, kind):
    archive, provider, p, c = setup(svc, tmp_path, sources=("a",))
    p = proposal(svc, kind).model_copy(update={"timestamp": NOW})
    result = c.assess(p, RunMode.PAPER)
    assert result.verdict is (GateVerdict.BLOCK if kind is Action.LONG else GateVerdict.REVIEW)
    assert result.reason == "CALENDAR_COVERAGE_INCOMPLETE"
    assert svc.repo.events(svc.run.run_id, types=["policy.decision"])[0].payload["calendar_gaps"] == [
        "b:MISSING"
    ]


def test_revocation_restart_and_bad_mode_are_not_bypassed(svc, tmp_path):
    archive, provider, p, c = setup(svc, tmp_path)
    assert c.assess(p, RunMode.OBSERVE).reason == "POLICY_CONTEXT_UNAVAILABLE"
    p = proposal(svc, Action.CLOSE).model_copy(update={"timestamp": NOW})
    archive.revoke(DossierRevocation(dossier_id="fixture-1", available_at=NOW, reason="fixture revoked"))
    assert c.assess(p, RunMode.PAPER).verdict is GateVerdict.REVIEW


def test_collectors_fail_closed_and_no_implicit_exposure(svc, tmp_path):
    from alladin.challenge.account_policy import AccountConstraints

    archive, provider, p, c = setup(svc, tmp_path)
    d = dossier(svc, id="constraints", reviewed_at=NOW, available_at=NOW)
    d = d.model_copy(
        update={
            "profile": replace(
                d.profile,
                constraints=AccountConstraints(
                    account_ref=svc.run.account_binding.account_ref,
                    currency="USD",
                    max_aggregate_positions=2,
                    managed_accounts=frozenset({svc.run.account_binding.account_ref}),
                ),
            )
        }
    )
    archive.add_dossier(d)
    assert c.assess(p, RunMode.PAPER).reason == "EXPOSURE_UNAVAILABLE"


def test_canonical_evidence_is_stable_across_process_hash_seed(svc):
    values = {"symbols": frozenset({"EURUSD", "GBPUSD", "XAUUSD"}), "time": NOW}
    assert evidence_sha256(values) == evidence_sha256(dict(values))
    text = "from datetime import UTC,datetime; from alladin.challenge.policy_serialization import evidence_sha256; print(evidence_sha256({'symbols':frozenset({'EURUSD','GBPUSD','XAUUSD'}),'time':datetime(2026,10,8,12,tzinfo=UTC)}))"
    outputs = [
        subprocess.check_output(
            [sys.executable, "-c", text], env=dict(os.environ, PYTHONHASHSEED=str(seed)), text=True
        ).strip()
        for seed in (1, 17, 999)
    ]
    assert outputs == [evidence_sha256(values)] * 3
    with pytest.raises(ValueError):
        canonical_json({"risk": float("nan")})
    with pytest.raises(ValueError):
        canonical_json({"time": NOW.replace(tzinfo=None)})
    with pytest.raises(ValueError):
        canonical_json({1: "ambiguous"})


def test_provider_snapshot_is_causal_when_receipt_is_archived_late(svc, tmp_path):
    archive, provider, p, c = setup(svc, tmp_path, sources=())
    later = PolicyArchive(archive.path, clock=lambda: NOW + timedelta(seconds=1))
    add_batch(later, "a")
    add_batch(later, "b")
    assert c.assess(p, RunMode.PAPER).reason == "CALENDAR_COVERAGE_INCOMPLETE"


@pytest.mark.parametrize(
    "kind", [Action.HOLD, Action.CLOSE, Action.PARTIAL_CLOSE, Action.MODIFY_STOP, Action.MODIFY_TARGET]
)
@pytest.mark.parametrize("missing", [False, True])
def test_archived_provider_in_paper_orchestration(settings, tmp_path, monkeypatch, kind, missing):
    from alladin.agents.mock import MockAgent
    from alladin.brokers.mock import MockBroker
    from alladin.orchestration.bootstrap import build_services
    from tests.test_position_lifecycle import action, opened

    svc = build_services(settings, MockBroker(start=NOW), create_run=True, db_url="sqlite://")
    svc.manager.start(svc.run, svc.broker.account_info())
    archive, provider, p, c = setup(svc, tmp_path, sources=("a",) if missing else ("a", "b"))
    monkeypatch.setattr(svc.broker, "_send", lambda *a, **kw: pytest.fail("broker send forbidden"))
    paper = opened(svc, RunMode.PAPER)

    class ManagementBrain:
        source_id, source_version = "test", "1"

        def decide(self, ctx):
            return action(svc, RunMode.PAPER, kind, paper, cycle=ctx.cycle_id)

    engine = svc.engine(MockAgent(), brain=ManagementBrain(), run_mode=RunMode.PAPER, policy_controller=c)
    engine.paper_engine = paper
    result = engine.run_cycle()
    assert result.decision == ("NO_TRADE" if missing and kind is not Action.HOLD else kind.value), result
    events = svc.repo.events(svc.run.run_id, types=["policy.decision"])
    assert len(events) == 1 and events[0].payload["dossier_id"] == "fixture-1"


def test_phase_selector_does_not_reuse_previous_phase_dossier(svc, tmp_path):
    from alladin.brain import proposal_identity

    archive, provider, p, c = setup(svc, tmp_path)
    phase = ["funded"]
    provider.phase = lambda _: phase[0]
    assert c.assess(p, RunMode.PAPER).verdict is GateVerdict.ALLOW
    phase[0] = "verification"
    other = p.model_copy(
        update={
            "cycle_id": "C-next",
            "proposal_id": proposal_identity(
                p.run_id, "C-next", p.opportunity_id, p.source_id, p.source_version
            ),
        }
    )
    assert c.assess(other, RunMode.PAPER).reason == "POLICY_CONTEXT_UNAVAILABLE"
    d = dossier(svc, id="verification-dossier")
    d = d.model_copy(update={"profile": replace(d.profile, phase="verification")})
    archive.add_dossier(d)
    last = p.model_copy(
        update={
            "cycle_id": "C-last",
            "proposal_id": proposal_identity(
                p.run_id, "C-last", p.opportunity_id, p.source_id, p.source_version
            ),
        }
    )
    assert c.assess(last, RunMode.PAPER).verdict is GateVerdict.ALLOW
    assert (
        svc.repo.events(svc.run.run_id, types=["policy.decision"])[-1].payload["dossier_id"]
        == "verification-dossier"
    )
