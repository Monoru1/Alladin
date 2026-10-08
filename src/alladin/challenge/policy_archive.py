"""Append-only SQLite policy evidence archive, independent of the trading journal.

Availability includes local archival latency. Hashes detect accidental edits,
not adversarial rewriting or authenticity. No account/network/order capabilities.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from alladin.challenge.economic_calendar import CalendarBatch
from alladin.challenge.policy_dossier import DossierRevocation, PolicyDossier
from alladin.challenge.policy_serialization import canonical_json, evidence_sha256
from alladin.challenge.public_calendar import MAX_BYTES, URLS, PublicCalendarDocument
from alladin.core.enums import RunMode
from alladin.core.workspace import AccountBinding

Kind = Literal["calendar", "document", "dossier", "revocation"]


class DocumentReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source: str = Field(min_length=1)
    source_url: str
    received_at: AwareDatetime
    media_type: Literal["text/calendar", "application/json", "text/plain"]
    payload: str = Field(min_length=1, max_length=MAX_BYTES)

    @model_validator(mode="after")
    def valid_receipt(self) -> DocumentReceipt:
        url = urlsplit(self.source_url)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.fragment:
            raise ValueError("public HTTPS source without credentials required")
        if (
            self.source != self.source.strip()
            or not self.source.strip()
            or len(self.payload.encode()) > MAX_BYTES
        ):
            raise ValueError("invalid source or oversized document")
        if self.source in URLS and self.source_url != URLS[self.source]:
            raise ValueError("public source URL mismatch")
        return self

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.payload.encode()).hexdigest()


class PolicyArchive:
    def __init__(self, path: Path, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.path = path
        self.clock = clock
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS policy_evidence (
                kind TEXT NOT NULL, identity TEXT NOT NULL, subject TEXT NOT NULL,
                available REAL NOT NULL, payload TEXT NOT NULL, sha256 TEXT NOT NULL,
                PRIMARY KEY (kind, identity))""")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS policy_available ON policy_evidence(kind,subject,available)"
            )

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.path, timeout=5.)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _put(self, kind: Kind, identity: str, subject: str, value: object, known_at: datetime) -> str:
        stored = self.clock()
        if stored.utcoffset() is None or known_at.utcoffset() is None or known_at > stored:
            raise ValueError("cannot archive future/naive evidence")
        payload = canonical_json(value)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            prior = conn.execute(
                "SELECT payload,sha256 FROM policy_evidence WHERE kind=? AND identity=?", (kind, identity)
            ).fetchone()
            if prior is not None:
                if prior["sha256"] != digest or prior["payload"] != payload:
                    raise ValueError("immutable evidence identity conflict")
                return digest
            conn.execute(
                "INSERT INTO policy_evidence VALUES (?,?,?,?,?,?)",
                (kind, identity, subject, stored.timestamp(), payload, digest),
            )
        return digest

    def add_document(self, document: PublicCalendarDocument | DocumentReceipt) -> str:
        if isinstance(document, PublicCalendarDocument):
            document = DocumentReceipt(
                **document.model_dump(mode="python"),
                media_type="application/json" if document.source == "bea-json" else "text/calendar",
            )
        identity = canonical_json([document.source, document.received_at])
        return self._put("document", identity, document.source, document, document.received_at)

    def add_calendar(self, batch: CalendarBatch) -> str:
        batch = CalendarBatch.model_validate_json(canonical_json(batch))
        if batch.document_sha256 is None:
            raise ValueError("calendar document provenance required")
        matching = [
            doc
            for doc in self.documents(now=self.clock())
            if doc.source == batch.source
            and doc.source_url == batch.source_url
            and doc.received_at == batch.observed_at
            and doc.sha256 == batch.document_sha256
        ]
        if not matching:
            raise ValueError("matching received source document must be archived first")
        if batch.source_url in URLS.values() and batch.coverage_complete is not False:
            raise ValueError("public BLS/BEA schedules cannot certify full coverage")
        # Only canonical content is stored. Source/receipt is immutable even if a
        # later import attempts to alter expiry or coverage under the same receipt.
        identity = canonical_json([batch.source, batch.observed_at])
        return self._put("calendar", identity, batch.source, batch, batch.observed_at)

    def add_dossier(self, dossier: PolicyDossier) -> str:
        dossier = PolicyDossier.model_validate_json(canonical_json(dossier))
        return self._put(
            "dossier", dossier.id, evidence_sha256(dossier.binding), dossier, dossier.available_at
        )

    def revoke(self, revocation: DossierRevocation) -> str:
        # Revocation must refer to an existing dossier; no destructive deletion.
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM policy_evidence WHERE kind='dossier' AND identity=?",
                (revocation.dossier_id,),
            ).fetchone()
        if row is None:
            raise ValueError("unknown dossier")
        dossier = PolicyDossier.model_validate_json(row["payload"])
        if revocation.available_at < dossier.available_at:
            raise ValueError("revocation precedes dossier availability")
        return self._put(
            "revocation", revocation.dossier_id, revocation.dossier_id, revocation, revocation.available_at
        )

    def _read(self, kind: Kind, now: datetime, subject: str | None = None) -> list[str]:
        if now.utcoffset() is None:
            raise ValueError("aware archive query required")
        query = "SELECT payload,sha256 FROM policy_evidence WHERE kind=? AND available<=?"
        args: list[object] = [kind, now.timestamp()]
        if subject is not None:
            query += " AND subject=?"
            args.append(subject)
        query += " ORDER BY available,identity"
        with self._connect() as conn:
            rows = conn.execute(query, args).fetchall()
        for row in rows:
            if hashlib.sha256(row["payload"].encode()).hexdigest() != row["sha256"]:
                raise ValueError("policy archive integrity failure")
        return [row["payload"] for row in rows]

    def calendars(self, *, now: datetime) -> tuple[CalendarBatch, ...]:
        return tuple(CalendarBatch.model_validate_json(p) for p in self._read("calendar", now))

    def documents(self, *, now: datetime) -> tuple[DocumentReceipt, ...]:
        return tuple(DocumentReceipt.model_validate_json(p) for p in self._read("document", now))

    def resolve_dossier(
        self, *, binding: AccountBinding, program: str, phase: str, mode: RunMode, now: datetime
    ) -> PolicyDossier:
        if mode not in {RunMode.OBSERVE, RunMode.PAPER}:
            raise ValueError("only OBSERVE/PAPER dossiers can be resolved")
        candidates = [
            PolicyDossier.model_validate_json(p) for p in self._read("dossier", now, evidence_sha256(binding))
        ]
        scoped = [
            d
            for d in candidates
            if d.binding == binding
            and d.profile.program == program
            and d.profile.phase == phase
            and d.available_at <= now
        ]
        if not scoped:
            raise ValueError("policy dossier unavailable")
        newest = max(d.available_at for d in scoped)
        selected = [d for d in scoped if d.available_at == newest]
        if len(selected) != 1:
            raise ValueError("ambiguous policy dossier activation")
        dossier = selected[0]
        revoked = [
            DossierRevocation.model_validate_json(p) for p in self._read("revocation", now, dossier.id)
        ]
        if (
            dossier.status != "SIMULATION_ONLY"
            or mode not in dossier.allowed_modes
            or now > dossier.valid_until
            or revoked
        ):
            raise ValueError("policy dossier draft, expired, revoked or mode unavailable")
        return dossier
