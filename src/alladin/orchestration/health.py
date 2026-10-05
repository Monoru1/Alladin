"""État de santé runtime reconstructible depuis le journal append-only."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from alladin.core.workspace import WorkspaceId
from alladin.journal.models import EventType
from alladin.journal.service import JournalService


class RuntimeStatus(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


class ProviderStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    UP = "UP"
    DOWN = "DOWN"
    STALE = "STALE"


class RuntimeHealth(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    workspace: WorkspaceId
    mode: str
    status: RuntimeStatus
    started_at: datetime
    last_heartbeat_at: datetime
    last_cycle_at: datetime | None = None
    last_market_update_at: datetime | None = None
    provider_status: ProviderStatus = ProviderStatus.UNKNOWN
    broker_status: str | None = None
    consecutive_failures: int = Field(default=0, ge=0)
    last_error: str | None = None
    degraded_reason: str | None = None
    stop_reason: str | None = None


class StaleMarketDataError(RuntimeError):
    pass


class RuntimeHealthTracker:
    """Machine d'état minimale ; chaque mutation devient un heartbeat journalisé."""

    def __init__(
        self,
        journal: JournalService,
        run_id: str,
        workspace: WorkspaceId,
        mode: str,
        *,
        stale_after_s: float,
        max_failures: int,
        backoff_base_s: float,
        backoff_cap_s: float,
        clock: Callable[[], datetime] | None = None,
        restore: bool = True,
    ) -> None:
        if stale_after_s <= 0 or max_failures < 1 or backoff_base_s <= 0 or backoff_cap_s <= 0:
            raise ValueError("configuration runtime health invalide")
        self.journal = journal
        self.run_id = run_id
        self.workspace = workspace
        self.mode = mode
        self.stale_after_s = stale_after_s
        self.max_failures = max_failures
        self.backoff_base_s = backoff_base_s
        self.backoff_cap_s = backoff_cap_s
        self.clock = clock or (lambda: datetime.now(UTC))
        now = self._now()
        previous = self.load_latest(journal, run_id) if restore else None
        self.health = RuntimeHealth(
            run_id=run_id,
            workspace=workspace,
            mode=mode,
            status=previous.status if previous and previous.status in (
                RuntimeStatus.DEGRADED, RuntimeStatus.STALE, RuntimeStatus.FAILED
            ) else RuntimeStatus.DEGRADED,
            started_at=now,
            last_heartbeat_at=now,
            last_cycle_at=previous.last_cycle_at if previous else None,
            last_market_update_at=previous.last_market_update_at if previous else None,
            provider_status=previous.provider_status if previous else ProviderStatus.UNKNOWN,
            broker_status=previous.broker_status if previous else None,
            consecutive_failures=previous.consecutive_failures if previous else 0,
            last_error=previous.last_error if previous else None,
            degraded_reason="runtime démarré, marché non encore validé",
        )
        self._persist()

    @staticmethod
    def load_latest(journal: JournalService, run_id: str) -> RuntimeHealth | None:
        events = journal.repo.events(run_id, [EventType.RUNTIME_HEALTH.value], limit=1, desc=True)
        return RuntimeHealth.model_validate(events[0].payload) if events else None

    def heartbeat(self) -> RuntimeHealth:
        self.health = self.health.model_copy(update={"last_heartbeat_at": self._now()})
        return self._persist()

    def market_progress(self, observed_at: datetime) -> RuntimeHealth:
        now = self._now()
        age = (now - observed_at.astimezone(UTC)).total_seconds()
        if age > self.stale_after_s:
            self.health = self.health.model_copy(update={
                "status": RuntimeStatus.STALE,
                "provider_status": ProviderStatus.STALE,
                "last_heartbeat_at": now,
                "last_market_update_at": observed_at,
                "degraded_reason": f"données marché périmées: {age:.1f}s > {self.stale_after_s:.1f}s",
            })
            self._persist()
            raise StaleMarketDataError(self.health.degraded_reason)
        self.health = self.health.model_copy(update={
            "status": RuntimeStatus.HEALTHY,
            "provider_status": ProviderStatus.UP,
            "last_heartbeat_at": now,
            "last_market_update_at": observed_at,
            "consecutive_failures": 0,
            "last_error": None,
            "degraded_reason": None,
        })
        return self._persist()

    def cycle_completed(self, completed_at: datetime | None = None) -> RuntimeHealth:
        now = completed_at or self._now()
        self.health = self.health.model_copy(update={
            "last_heartbeat_at": now,
            "last_cycle_at": now,
        })
        return self._persist()

    def provider_failure(self, error: BaseException | str) -> RuntimeHealth:
        now = self._now()
        failures = self.health.consecutive_failures + 1
        failed = failures >= self.max_failures
        message = str(error) or type(error).__name__
        self.health = self.health.model_copy(update={
            "status": RuntimeStatus.FAILED if failed else RuntimeStatus.DEGRADED,
            "provider_status": ProviderStatus.DOWN,
            "last_heartbeat_at": now,
            "consecutive_failures": failures,
            "last_error": message,
            "degraded_reason": "seuil d'échecs provider atteint" if failed else "provider indisponible",
        })
        return self._persist()

    def backoff_seconds(self) -> float:
        exponent = max(0, self.health.consecutive_failures - 1)
        return float(min(self.backoff_base_s * (2**exponent), self.backoff_cap_s))

    def stopping(self, reason: str) -> RuntimeHealth:
        self.health = self.health.model_copy(update={
            "status": RuntimeStatus.STOPPING,
            "last_heartbeat_at": self._now(),
            "stop_reason": reason,
        })
        return self._persist()

    def stopped(self, reason: str | None = None) -> RuntimeHealth:
        self.health = self.health.model_copy(update={
            "status": RuntimeStatus.STOPPED,
            "last_heartbeat_at": self._now(),
            "stop_reason": reason or self.health.stop_reason or "arrêt normal",
        })
        return self._persist()

    def _now(self) -> datetime:
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("clock runtime doit être timezone-aware")
        return now.astimezone(UTC)

    def _persist(self) -> RuntimeHealth:
        if not math.isfinite(self.backoff_seconds()):
            raise ValueError("backoff runtime non fini")
        self.journal.log(
            self.run_id,
            EventType.RUNTIME_HEALTH,
            self.health.model_dump(mode="json"),
        )
        return self.health
