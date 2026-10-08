from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from alladin.challenge.event_policy import EventPolicy
from alladin.challenge.public_calendar import (
    MAX_BYTES,
    URLS,
    PublicCalendarDocument,
    fetch_public_calendar,
    parse_public_calendar,
)

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)
ICS = '''BEGIN:VCALENDAR
BEGIN:VEVENT
UID:release-1
DTSTART;TZID=America/New_York:20261009T083000
SUMMARY:Consumer
 price release
SEQUENCE:2
END:VEVENT
END:VCALENDAR'''


def parse(payload=ICS, source='bls-ics'):
    doc = PublicCalendarDocument(source=source, source_url=URLS[source], received_at=NOW, payload=payload)
    return parse_public_calendar(doc, impacts=frozenset({'EURUSD'}), licence='synthetic test fixture')


def test_revision_provenance_causal_and_partial():
    batch = parse()
    assert batch.revisions[0].revision == 3
    assert batch.revisions[0].release_at == datetime(2026, 10, 9, 12, 30, tzinfo=UTC)
    assert batch.revisions[0].known_at == NOW
    assert batch.revisions[0].actual is None
    assert batch.revisions[0].restricted is False
    assert len(batch.document_sha256) == 64
    assert batch.snapshot().coverage_complete is False
    assert EventPolicy().evaluate(now=NOW, symbol='EURUSD', snapshot=batch.snapshot(), restrict_news=False).reason == 'CALENDAR_COVERAGE_INCOMPLETE'


@pytest.mark.parametrize('old,new', [
    ('20261009T083000','20261101T013000'), ('20261009T083000','20260308T023000'),
    ('DTSTART;TZID=America/New_York:20261009T083000','DTSTART:20261009T083000'),
    ('DTSTART;TZID=America/New_York:20261009T083000','DTSTART;VALUE=DATE:20261009'),
    ('SEQUENCE:2','SEQUENCE:-1'), ('SEQUENCE:2','RRULE:FREQ=MONTHLY'),
    ('SEQUENCE:2','STATUS:CANCELLED'), ('END:VCALENDAR',''), ('END:VEVENT',''),
    ('UID:release-1','SUMMARY:duplicate'),
])
def test_uncertain_ics_rejected(old,new):
    with pytest.raises((ValueError, KeyError)):
        parse(ICS.replace(old,new))


def test_bea_json_duplicate_dates_and_utc():
    batch = parse('{"GDP":{"release_dates":["2026-10-30T08:30:00-04:00","2026-10-30T08:30:00-04:00"]},"file_last_updated":"2026-10-07T12:00:00"}', 'bea-json')
    assert len(batch.revisions) == 1
    assert batch.revisions[0].release_at.hour == 12
    assert batch.revisions[0].known_at == NOW


@pytest.mark.parametrize('payload', ['{}','{"GDP":{"release_dates":[]}}','{"GDP":{"release_dates":["2026-10-30T08:30:00"]}}','{"GDP":{"release_dates":[],"extra":1}}'])
def test_bad_bea_schema_rejected(payload):
    with pytest.raises(ValueError):
        parse(payload,'bea-json')


def test_bounded_fixed_fetch(monkeypatch):
    response = MagicMock()
    response.geturl.return_value = URLS['bls-ics']
    response.read.return_value = ICS.encode()
    opener = MagicMock()
    opener.open.return_value.__enter__.return_value = response
    monkeypatch.setattr('alladin.challenge.public_calendar.build_opener',lambda *args: opener)
    doc = fetch_public_calendar('bls-ics', clock=lambda: NOW)
    assert doc.payload == ICS
    response.read.assert_called_once_with(MAX_BYTES+1)
    assert opener.open.call_args.kwargs['timeout'] == 10
    response.geturl.return_value = 'https://example.test/redirect'
    with pytest.raises(ValueError):
        fetch_public_calendar('bls-ics')
    response.geturl.return_value = URLS['bls-ics']
    response.read.return_value = b'x'*(MAX_BYTES+1)
    with pytest.raises(ValueError):
        fetch_public_calendar('bls-ics')


def test_explicit_bounded_ttl_and_url():
    doc = PublicCalendarDocument(source='bls-ics',source_url=URLS['bls-ics'],received_at=NOW,payload=ICS)
    with pytest.raises(ValueError):
        parse_public_calendar(doc,impacts=frozenset({'EURUSD'}),licence='fixture',ttl=timedelta(days=2))
    with pytest.raises(ValueError):
        doc.model_copy(update={'source_url':'x'}).__class__.model_validate(dict(doc.model_dump(),source_url='x'))
