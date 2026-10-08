"""Versioned account-specific prop-firm gate (DECISION-033).

Pure logic only. Must be independently wired to ExecutionService after acceptance.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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

    def __post_init__(self) -> None:
        if self.verified_at.tzinfo is None or self.valid_until.tzinfo is None:
            raise ValueError("verification timestamps must be timezone-aware")
        if self.valid_until < self.verified_at:
            raise ValueError("valid_until before verified_at")
        if not all((self.firm, self.program, self.phase, self.version, self.source_url)):
            raise ValueError("identity, version and source required")
        if self.max_open_positions is not None and self.max_open_positions < 0:
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
    if now.tzinfo is None:
        return FirmDecision(FirmVerdict.BLOCK, "CLOCK_NOT_TIMEZONE_AWARE")
    if profile is None:
        return FirmDecision(FirmVerdict.BLOCK, "FIRM_PROFILE_MISSING")
    if not profile.verified_at <= now <= profile.valid_until:
        return FirmDecision(FirmVerdict.BLOCK, "FIRM_PROFILE_STALE")
    if not profile.ea_allowed:
        return FirmDecision(FirmVerdict.BLOCK, "AUTOMATION_NOT_PERMITTED")
    if symbol.upper() not in {s.upper() for s in profile.allowed_symbols}:
        return FirmDecision(FirmVerdict.BLOCK, "SYMBOL_NOT_AUTHORIZED")
    if open_positions < 0:
        return FirmDecision(FirmVerdict.BLOCK, "INVALID_POSITION_COUNT")
    if profile.max_open_positions is not None and open_positions >= profile.max_open_positions:
        return FirmDecision(FirmVerdict.BLOCK, "POSITION_LIMIT")
    return FirmDecision(FirmVerdict.ALLOW, "FIRM_RULES_CLEAR")
