"""Versioned account-specific prop-firm gate (DECISION-033).

Pure logic only. Must be independently wired to ExecutionService after acceptance.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class FirmVerdict(StrEnum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class FirmProfile:
    firm: str
    program: str
    phase: str
    account_type: str
    version: str
    source_url: str
    verified_at: datetime
    valid_until: datetime
    allowed_symbols: frozenset[str]
    ea_allowed: bool
    max_open_positions: int | None = None
    restrict_news: bool | None = None

    def __post_init__(self) -> None:
        if self.verified_at.utcoffset() is None or self.valid_until.utcoffset() is None:
            raise ValueError("verification timestamps must be timezone-aware")
        object.__setattr__(self, "verified_at", self.verified_at.astimezone(UTC))
        object.__setattr__(self, "valid_until", self.valid_until.astimezone(UTC))
        if self.valid_until < self.verified_at:
            raise ValueError("valid_until before verified_at")
        if not all(s.strip() for s in (self.firm, self.program, self.phase, self.account_type, self.version, self.source_url)):
            raise ValueError("identity, version and source required")
        if self.restrict_news is not None and type(self.restrict_news) is not bool:
            raise ValueError("restrict_news must be boolean or unknown")
        if type(self.ea_allowed) is not bool:
            raise ValueError("ea_allowed must be boolean")
        if any(not s.strip() or s != s.strip() for s in self.allowed_symbols):
            raise ValueError("unambiguous allowed symbols required")
        if self.max_open_positions is not None and (type(self.max_open_positions) is not int or self.max_open_positions < 0):
            raise ValueError("negative position limit")


@dataclass(frozen=True)
class FirmDecision:
    verdict: FirmVerdict
    reason: str


def check_new_entry(
    profile: FirmProfile | None,
    *,
    now: datetime,
    symbol: str,
    open_positions: int,
) -> FirmDecision:
    """Missing/expired profiles block entry; no account inferred from symbol."""
    if now.utcoffset() is None:
        return FirmDecision(FirmVerdict.BLOCK, "CLOCK_NOT_TIMEZONE_AWARE")
    now = now.astimezone(UTC)
    if profile is None:
        return FirmDecision(FirmVerdict.BLOCK, "FIRM_PROFILE_MISSING")
    if not profile.verified_at <= now <= profile.valid_until:
        return FirmDecision(FirmVerdict.BLOCK, "FIRM_PROFILE_STALE")
    if not profile.ea_allowed:
        return FirmDecision(FirmVerdict.BLOCK, "AUTOMATION_NOT_PERMITTED")
    if symbol.upper() not in {s.upper() for s in profile.allowed_symbols}:
        return FirmDecision(FirmVerdict.BLOCK, "SYMBOL_NOT_AUTHORIZED")
    if type(open_positions) is not int or open_positions < 0:
        return FirmDecision(FirmVerdict.BLOCK, "INVALID_POSITION_COUNT")
    if profile.max_open_positions is not None and open_positions >= profile.max_open_positions:
        return FirmDecision(FirmVerdict.BLOCK, "POSITION_LIMIT")
    return FirmDecision(FirmVerdict.ALLOW, "FIRM_RULES_CLEAR")
