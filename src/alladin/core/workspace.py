"""Workspace identity is independent of a broker or its credentials."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from alladin.core.enums import AccountType


class WorkspaceId(StrEnum):
    ALLADIN = "ALLADIN"
    JAFAR = "JAFAR"


MAGIC_RANGES = {WorkspaceId.ALLADIN: (26_000_000, 27_000_000), WorkspaceId.JAFAR: (27_000_000, 28_000_000)}


class AccountBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace: WorkspaceId = WorkspaceId.ALLADIN
    broker: str = Field(min_length=1)
    account_ref: str = Field(min_length=1)  # masked public reference, never credentials
    server: str = Field(min_length=1)
    account_type: AccountType
    account_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


def magic_for(workspace: WorkspaceId, seq: int, alladin_base: int = 26_000_000) -> int:
    lower, upper = MAGIC_RANGES[workspace]
    base = alladin_base if workspace is WorkspaceId.ALLADIN else lower
    magic = base + seq
    if seq <= 0 or not lower <= magic < upper:
        raise ValueError("magic number hors plage réservée du workspace")
    return magic
