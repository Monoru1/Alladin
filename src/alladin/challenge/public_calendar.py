"""Credential-free official schedule adapters. Partial calendars, never trade authority.

Only fixed public URLs are fetched. Forecasts/actuals and firm-restricted event
labels are NOT inferred. The caller supplies symbol impacts and restriction tags.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from alladin.challenge.economic_calendar import CalendarBatch, CalendarRevision

Source = Literal["bls-ics", "bea-ics", "bea-json"]
URLS: dict[str, str] = {
    "bls-ics": "https://www.bls.gov/schedule/news_release/bls.ics",
    "bea-ics": "https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics",
    "bea-json": "https://apps.bea.gov/API/signup/release_dates.json",
}
MAX_BYTES = 2_000_000


class PublicCalendarDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source: Source
    source_url: str
    received_at: AwareDatetime
    payload: str = Field(min_length=1, max_length=MAX_BYTES)

    @model_validator(mode="after")
    def validate_document(self) -> PublicCalendarDocument:
        if self.source_url != URLS[self.source] or len(self.payload.encode()) > MAX_BYTES:
            raise ValueError("unexpected source URL or oversized document")
        return self

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.payload.encode()).hexdigest()


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: object, code: int, msg: str, headers: object, newurl: str) -> None:
        raise ValueError("calendar redirect requires independent source review")


def fetch_public_calendar(source: Source, *, timeout: float = 10.,
                          clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> PublicCalendarDocument:
    """One bounded public GET, no redirect to an arbitrary host and no retries."""
    if not 0 < timeout <= 30:
        raise ValueError("timeout must be bounded")
    url = URLS[source]
    request = Request(url, headers={"User-Agent": "Alladin-research-calendar/1.0"})
    with build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
        if response.geturl() != url:
            raise ValueError("calendar redirect requires independent source review")
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("calendar payload too large")
    return PublicCalendarDocument(source=source, source_url=url, received_at=clock(), payload=raw.decode("utf-8-sig"))


def _ics_time(value: str, parameters: dict[str, str]) -> datetime:
    if parameters.get("VALUE", "DATE-TIME") != "DATE-TIME":
        raise ValueError("all-day release lacks a precise publication time")
    if value.endswith("Z"):
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    tzid = parameters.get("TZID")
    if not tzid:
        raise ValueError("floating calendar time lacks timezone")
    zone = ZoneInfo("America/New_York" if tzid == "US-Eastern" else tzid)
    local = datetime.strptime(value, "%Y%m%dT%H%M%S")
    alternatives = {local.replace(tzinfo=zone, fold=fold).astimezone(UTC) for fold in (0, 1)
                    if local.replace(tzinfo=zone, fold=fold).astimezone(UTC).astimezone(zone).replace(tzinfo=None) == local}
    if len(alternatives) != 1:
        raise ValueError("ambiguous/nonexistent DST release; explicit UTC required")
    return alternatives.pop()


def _ics_events(payload: str) -> list[tuple[str, datetime, int, str]]:
    logical: list[str] = []
    for line in payload.splitlines():
        if line.startswith((" ", "\t")):
            if not logical:
                raise ValueError("orphan folded ICS line")
            logical[-1] += line[1:]
        else:
            logical.append(line)
    if "BEGIN:VCALENDAR" not in logical or "END:VCALENDAR" not in logical:
        raise ValueError("incomplete ICS calendar")
    current: dict[str, tuple[str, dict[str, str]]] | None = None
    rows = []
    for line in logical:
        if line == "BEGIN:VEVENT":
            if current is not None:
                raise ValueError("nested ICS event")
            current = {}
        elif line == "END:VEVENT":
            if current is None or not {"UID", "DTSTART", "SUMMARY"} <= current.keys():
                raise ValueError("incomplete ICS event")
            if any(name in current for name in ("RRULE", "RDATE", "RECURRENCE-ID", "EXDATE")):
                raise ValueError("recurring releases require explicit expansion")
            if current.get("STATUS", ("", {}))[0] == "CANCELLED":
                raise ValueError("cancelled release requires explicit coverage review")
            uid = current["UID"][0]
            release = _ics_time(*current["DTSTART"])
            sequence = int(current.get("SEQUENCE", ("0", {}))[0])
            if sequence < 0:
                raise ValueError("negative ICS revision")
            rows.append((uid, release, sequence+1, current["SUMMARY"][0]))
            current = None
        elif current is not None:
            if ":" not in line:
                raise ValueError("invalid ICS property")
            key, value = line.split(":", 1)
            parts = key.split(";")
            name = parts[0]
            if name in current:
                raise ValueError("duplicate ICS property")
            parameters = dict(part.split("=", 1) for part in parts[1:])
            current[name] = value, parameters
    if current is not None or not rows:
        raise ValueError("empty/incomplete release schedule")
    return rows


def parse_public_calendar(
    document: PublicCalendarDocument, *, impacts: frozenset[str],
    restricted_event_ids: frozenset[str] = frozenset(), ttl: timedelta = timedelta(hours=1),
    licence: str,
) -> CalendarBatch:
    """Receipt time is the earliest supported availability, never provider DTSTAMP.

    BEA JSON lacks stable occurrence IDs: IDs use title + UTC calendar day.
    Date changes create a new ID. Store complete received documents for replay.
    These adapters deliberately mark coverage incomplete.
    """
    if not timedelta(0) < ttl <= timedelta(days=1):
        raise ValueError("bounded positive calendar TTL required")
    if document.source == "bea-json":
        data = json.loads(document.payload)
        if not isinstance(data, dict) or not data:
            raise ValueError("missing BEA release series")
        rows = []
        for title, entry in data.items():
            if title == "file_last_updated":
                if not isinstance(entry, str):
                    raise ValueError("invalid BEA update metadata")
                datetime.fromisoformat(entry)  # metadata only, never causal availability
                continue
            if not isinstance(entry, dict) or set(entry) != {"release_dates"} or not isinstance(entry["release_dates"], list):
                raise ValueError("unknown BEA schedule schema")
            dates = entry["release_dates"]
            for text in sorted(set(dates)):
                release = datetime.fromisoformat(text)
                if release.utcoffset() is None:
                    raise ValueError("BEA timestamp must include UTC offset")
                release = release.astimezone(UTC)
                uid = hashlib.sha256(f"{title}:{release.date()}".encode()).hexdigest()
                rows.append((uid, release, 1, title))
    else:
        rows = _ics_events(document.payload)
    if not rows:
        raise ValueError("empty release schedule")
    received = document.received_at.astimezone(UTC)
    revisions = tuple(CalendarRevision(
        event_id=f"{document.source}:{uid}", revision=revision, release_at=release,
        known_at=received, collected_at=received, original_timezone="America/New_York", currency="USD",
        impacted_symbols=impacts, restricted=f"{document.source}:{uid}" in restricted_event_ids,
    ) for uid, release, revision, _ in rows)
    return CalendarBatch(source=document.source, source_url=document.source_url, licence=licence,
                         observed_at=received, valid_until=received+ttl, revisions=revisions,
                         coverage_complete=False, document_sha256=document.sha256)
