"""Passive official-source registry and publication classification.

An allowlisted origin authenticates only the configured URL boundary, not the
truth of its statements. No scraping, API calls or trading permissions here.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit


def _time(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("aware time required")
    return value.astimezone(UTC)


def _host(url: str) -> str:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or
            parsed.password or parsed.fragment or parsed.port not in (None, 443)):
        raise ValueError("canonical HTTPS URL without credentials/fragment required")
    hostname = parsed.hostname.lower()\n    if hostname.endswith(".") or not hostname.isascii() or any(\n        not label or len(label) > 63 or label.startswith("-") or label.endswith("-") or\n        not all(char.isalnum() or char == "-" for char in label)\n        for label in hostname.split(".")\n    ):\n        raise ValueError("noncanonical source hostname")\n    return hostname


@dataclass(frozen=True)
class OfficialSource:
    source_id: str
    hostname: str

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.hostname or self.hostname != self.hostname.lower():
            raise ValueError("invalid official source")
        if _host("https://" + self.hostname) != self.hostname:
            raise ValueError("invalid source hostname")


@dataclass(frozen=True)
class OfficialPublication:
    source_id: str
    publication_id: str
    url: str
    text: str
    published_at: datetime
    received_at: datetime
    kind: str  # STATEMENT, FACT, FORECAST, OPINION; NOT a truth guarantee

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.publication_id.strip() or not self.text.strip():
            raise ValueError("publication identity and text required")
        _host(self.url)
        if _time(self.received_at) < _time(self.published_at):
            raise ValueError("receipt cannot precede publication")
        if self.kind not in {"STATEMENT", "FACT", "FORECAST", "OPINION"}:
            raise ValueError("unknown classification")

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


def verify_publication(
    publication: OfficialPublication, *, sources: tuple[OfficialSource, ...], as_of: datetime,
) -> str:
    """Return status only; NEVER infer that a statement is true or actionable."""
    known_at = _time(as_of)
    matches = [source for source in sources if source.source_id == publication.source_id]
    if len(matches) != 1 or _host(publication.url) != matches[0].hostname:
        return "UNVERIFIED_ORIGIN"
    if max(_time(publication.published_at), _time(publication.received_at)) > known_at:
        return "NOT_YET_KNOWN"
    return "VERIFIED_CONFIGURED_ORIGIN"
