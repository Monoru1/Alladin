from dataclasses import replace
from datetime import timedelta

import pytest

from alladin.brain import Action
from alladin.challenge.policy_archive import DocumentReceipt, PolicyArchive
from alladin.challenge.policy_dossier import DossierRevocation, PolicyDossier
from alladin.challenge.public_calendar import URLS
from alladin.core.enums import RunMode
from tests.test_calendar_composite import NOW, batch, plan
from tests.test_policy_control import context, proposal


def receipt(source="a", **updates):
    values = dict(
        source=source,
        source_url=f"https://example.test/{source}",
        received_at=NOW - timedelta(minutes=1),
        media_type="text/plain",
        payload="synthetic fixture, no official release or contract",
    )
    values.update(updates)
    return DocumentReceipt(**values)


def add_batch(archive, source="a", **updates):
    document = receipt(source, received_at=updates.get("observed_at", NOW - timedelta(minutes=1)))
    archive.add_document(document)
    row = batch(source, document_sha256=document.sha256, **updates)
    archive.add_calendar(row)
    return row


def dossier(svc, **updates):
    profile = context(svc, proposal(svc, Action.LONG)).firm_profile
    # Shared synthetic dates are explicitly adapted to archive test NOW.
    profile = replace(profile, verified_at=NOW - timedelta(days=1), valid_until=NOW + timedelta(days=1))
    values = dict(
        id="fixture-1",
        binding=svc.run.account_binding,
        profile=profile,
        coverage_plan=plan(),
        status="SIMULATION_ONLY",
        evidence_kind="SYNTHETIC",
        source_document_sha256="a" * 64,
        review_reference="synthetic fixture review",
        reviewed_at=NOW - timedelta(minutes=2),
        available_at=NOW - timedelta(minutes=1),
        valid_until=NOW + timedelta(hours=1),
    )
    values.update(updates)
    return PolicyDossier(**values)


def resolve(archive, svc, **updates):
    values = dict(
        binding=svc.run.account_binding, program="fixture", phase="funded", mode=RunMode.PAPER, now=NOW
    )
    values.update(updates)
    return archive.resolve_dossier(**values)


def test_causal_calendar_archive_restore_and_idempotence(tmp_path):
    archive = PolicyArchive(tmp_path / "policy.sqlite", clock=lambda: NOW)
    row = add_batch(archive)
    archive.add_calendar(row)
    assert archive.calendars(now=NOW - timedelta(seconds=1)) == ()
    assert archive.documents(now=NOW - timedelta(seconds=1)) == ()
    restored = PolicyArchive(archive.path, clock=lambda: NOW + timedelta(minutes=1))
    assert restored.calendars(now=NOW) == (row,)
    assert len(restored.documents(now=NOW)) == 1
    assert restored.add_calendar(row) == archive.add_calendar(row)


def test_immutable_identity_no_partial_rewrite(tmp_path):
    archive = PolicyArchive(tmp_path / "policy.sqlite", clock=lambda: NOW)
    row = add_batch(archive)
    with pytest.raises(ValueError, match="immutable"):
        archive.add_calendar(row.model_copy(update={"coverage_complete": False}))
    with pytest.raises(ValueError, match="immutable"):
        archive.add_document(receipt(payload="different received document"))
    assert archive.calendars(now=NOW) == (row,)


def test_raw_document_and_public_coverage_cannot_be_forged(tmp_path):
    archive = PolicyArchive(tmp_path / "policy.sqlite", clock=lambda: NOW)
    with pytest.raises(ValueError, match="document"):
        archive.add_calendar(batch())
    doc = receipt("bls-ics", source_url=URLS["bls-ics"])
    archive.add_document(doc)
    values = dict(source_url=doc.source_url, document_sha256=doc.sha256)
    with pytest.raises(ValueError, match="full coverage"):
        archive.add_calendar(batch("bls-ics", **values))
    archive.add_calendar(batch("bls-ics", coverage_complete=False, **values))


def test_future_receipt_and_payload_corruption_fail_closed(tmp_path):
    archive = PolicyArchive(tmp_path / "policy.sqlite", clock=lambda: NOW)
    with pytest.raises(ValueError):
        archive.add_document(receipt(received_at=NOW + timedelta(seconds=1)))
    add_batch(archive)
    with archive._connect() as conn:
        conn.execute("UPDATE policy_evidence SET payload='{}' WHERE kind='calendar'")
    with pytest.raises(ValueError, match="integrity"):
        archive.calendars(now=NOW)


def test_dossier_binding_phase_modes_and_restart(tmp_path, svc):
    archive = PolicyArchive(tmp_path / "policy.sqlite", clock=lambda: NOW)
    d = dossier(svc)
    digest = archive.add_dossier(d)
    assert archive.add_dossier(d) == digest
    restored = PolicyArchive(archive.path, clock=lambda: NOW)
    assert resolve(restored, svc) == d
    for updates in (
        {"phase": "evaluation"},
        {"program": "other"},
        {"mode": RunMode.DEMO},
        {"binding": svc.run.account_binding.model_copy(update={"server": "other"})},
        {"now": NOW - timedelta(seconds=1)},
    ):
        with pytest.raises(ValueError):
            resolve(restored, svc, **updates)


@pytest.mark.parametrize("update", [{"status": "DRAFT"}, {"allowed_modes": frozenset({RunMode.OBSERVE})}])
def test_draft_and_wrong_mode_unavailable(tmp_path, svc, update):
    archive = PolicyArchive(tmp_path / "policy.sqlite", clock=lambda: NOW)
    archive.add_dossier(dossier(svc, **update))
    with pytest.raises(ValueError):
        resolve(archive, svc)


def test_newest_expired_or_revoked_does_not_fall_back(tmp_path, svc):
    archive = PolicyArchive(tmp_path / "policy.sqlite", clock=lambda: NOW)
    archive.add_dossier(
        dossier(svc, id="old", available_at=NOW - timedelta(hours=1), reviewed_at=NOW - timedelta(hours=2))
    )
    archive.add_dossier(dossier(svc))
    archive.revoke(DossierRevocation(dossier_id="fixture-1", available_at=NOW, reason="synthetic revocation"))
    with pytest.raises(ValueError, match="revoked"):
        resolve(archive, svc)
    with pytest.raises(ValueError):
        resolve(archive, svc, now=NOW + timedelta(hours=2))
    with pytest.raises(ValueError):
        archive.revoke(DossierRevocation(dossier_id="missing", available_at=NOW, reason="test"))


def test_duplicate_effective_dossier_conflict(tmp_path, svc):
    archive = PolicyArchive(tmp_path / "policy.sqlite", clock=lambda: NOW)
    archive.add_dossier(dossier(svc, id="first"))
    archive.add_dossier(dossier(svc, id="second"))
    with pytest.raises(ValueError, match="ambiguous"):
        resolve(archive, svc)
    with pytest.raises(ValueError, match="immutable"):
        archive.add_dossier(dossier(svc, id="first", review_reference="changed"))


@pytest.mark.parametrize(
    "update",
    [
        {"allowed_modes": frozenset({RunMode.DEMO})},
        {"allowed_modes": frozenset()},
        {"valid_until": NOW + timedelta(days=2)},
        {"available_at": NOW - timedelta(days=2)},
        {"source_document_sha256": "bad"},
    ],
)
def test_bad_dossier_rejected(svc, update):
    with pytest.raises(ValueError):
        dossier(svc, **update)


@pytest.mark.parametrize(
    "url", ["http://example.test/a", "https://user:password@example.test/a", "https://example.test/a#secret"]
)
def test_document_credentials_or_unsafe_url_rejected(url):
    with pytest.raises(ValueError):
        receipt(source_url=url)
