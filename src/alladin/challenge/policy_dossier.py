"""Persistable account/phase policy dossiers. Simulation permission only, never firm admission."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from alladin.challenge.calendar_composite import CoveragePlan
from alladin.challenge.firm_policy import FirmProfile
from alladin.core.enums import RunMode
from alladin.core.workspace import AccountBinding


class PolicyDossier(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(min_length=1)
    binding: AccountBinding
    profile: FirmProfile
    coverage_plan: CoveragePlan
    status: Literal["DRAFT", "SIMULATION_ONLY"] = "DRAFT"
    evidence_kind: Literal["SYNTHETIC", "DOCUMENT_REFERENCE"]
    source_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_reference: str = Field(min_length=1)
    reviewed_at: AwareDatetime
    available_at: AwareDatetime
    valid_until: AwareDatetime
    allowed_modes: frozenset[RunMode] = frozenset({RunMode.OBSERVE, RunMode.PAPER})

    @field_validator("reviewed_at", "available_at", "valid_until")
    @classmethod
    def utc_times(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def valid_scope(self) -> PolicyDossier:
        if (
            not self.profile.verified_at
            <= self.reviewed_at
            <= self.available_at
            <= self.valid_until
            <= self.profile.valid_until
        ):
            raise ValueError("dossier/profile chronology or expiry mismatch")
        if not self.allowed_modes or not self.allowed_modes <= {RunMode.OBSERVE, RunMode.PAPER}:
            raise ValueError("dossiers authorize simulation/observation only")
        if self.profile.restrict_news is None:
            raise ValueError("explicit phase/account news rule required")
        constraints = self.profile.constraints
        if constraints is not None and constraints.account_ref != self.binding.account_ref:
            raise ValueError("dossier constraint account mismatch")
        if any(not val.strip() or val != val.strip() for val in (self.id, self.review_reference)):
            raise ValueError("unambiguous dossier/review identities required")
        return self


class DossierRevocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    dossier_id: str = Field(min_length=1)
    available_at: AwareDatetime
    reason: str = Field(min_length=1)

    @field_validator("available_at")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)
