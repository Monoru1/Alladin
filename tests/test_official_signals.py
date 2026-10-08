"""Offline official source verification tests."""
from datetime import UTC, datetime, timedelta

import pytest

from alladin.challenge.official_signals import (
    OfficialPublication,
    OfficialSource,
    verify_publication,
)

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)
SOURCE = OfficialSource("bank", "central.example.org")


def post(url="https://central.example.org/news"):
    return OfficialPublication("bank", "statement-1", url, "Rate decision",
                               NOW, NOW + timedelta(seconds=2), "STATEMENT")


def test_verified_origin_requires_receipt():
    assert verify_publication(post(), sources=(SOURCE,), as_of=NOW) == "NOT_YET_KNOWN"
    assert verify_publication(post(), sources=(SOURCE,), as_of=NOW + timedelta(seconds=3)) == "VERIFIED_CONFIGURED_ORIGIN"


def test_subdomain_lookalike_and_wrong_origin_rejected():
    for url in ("https://fake-central.example.org/news", "https://central.example.org.attacker.test/news"):
        assert verify_publication(post(url), sources=(SOURCE,), as_of=NOW + timedelta(seconds=3)) == "UNVERIFIED_ORIGIN"


def test_duplicate_source_identity_fails_closed():
    assert verify_publication(post(), sources=(SOURCE, SOURCE), as_of=NOW + timedelta(seconds=3)) == "UNVERIFIED_ORIGIN"


def test_bad_urls_and_impossible_receipts_rejected():
    with pytest.raises(ValueError):
        post("http://central.example.org/news")
    with pytest.raises(ValueError):
        post("https://central.example.org@evil.test/news#x")
    with pytest.raises(ValueError):
        OfficialPublication("bank", "p", "https://central.example.org", "text",
                            NOW, NOW - timedelta(seconds=1), "FACT")
