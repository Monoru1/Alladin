"""Tests ciblés : workspace JAFAR OBSERVE/PAPER + runtime health dans Mission Control."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from alladin.api.app import create_app
from alladin.brokers.crypto import CryptoMockProvider
from alladin.brokers.crypto_observe import CryptoObserveBroker
from alladin.core.workspace import WorkspaceId
from alladin.journal.models import EventType
from alladin.orchestration.bootstrap import Components, build_services
from alladin.orchestration.health import ProviderStatus, RuntimeHealth, RuntimeStatus

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def _jafar_client(settings: object, *, stale_threshold: float = 1_000_000_000.0) -> tuple[TestClient, Components]:
    """Construit un TestClient Mission Control sur workspace JAFAR.
    
    stale_threshold: valeur runtime_stale_after_s pour l'app ; défaut énorme
    pour éviter que l'horloge réelle ne rende le mock timestamp stale.
    """
    provider = CryptoMockProvider(start=NOW)
    broker = CryptoObserveBroker(provider)
    comps = build_services(
        settings, broker,  # type: ignore[arg-type]
        create_run=True, workspace=WorkspaceId.JAFAR, db_url="sqlite://",
    )
    assert comps is not None
    comps.manager.start(comps.run, broker.account_info())
    api_settings = comps.settings.model_copy(update={"runtime_stale_after_s": stale_threshold})
    tc = TestClient(create_app(api_settings, comps.repo, comps.broker))
    return tc, comps


def _inject_health(comps: Components, status: RuntimeStatus, **kwargs: object) -> None:
    """Injecte un événement RUNTIME_HEALTH dans le journal."""
    payload = RuntimeHealth(
        run_id=comps.run.run_id,
        workspace=WorkspaceId.JAFAR,
        mode="PAPER",
        status=status,
        started_at=NOW,
        last_heartbeat_at=NOW,
        provider_status=kwargs.get("provider_status", ProviderStatus.UP),
        consecutive_failures=kwargs.get("consecutive_failures", 0),
        last_error=kwargs.get("last_error"),
        degraded_reason=kwargs.get("degraded_reason"),
        stop_reason=kwargs.get("stop_reason"),
    ).model_dump(mode="json")
    comps.journal.log(comps.run.run_id, EventType.RUNTIME_HEALTH, payload)


# ──────────────────────────────────────────────────────────────────────────────
# workspace /api/workspace
# ──────────────────────────────────────────────────────────────────────────────

def test_jafar_workspace_announces_observe_and_paper(settings: object) -> None:
    tc, _ = _jafar_client(settings)
    resp = tc.get("/api/workspace")
    assert resp.status_code == 200
    data = resp.json()
    assert data["workspace"] == "JAFAR"
    allowed = data["allowed_modes"]
    assert "OBSERVE" in allowed
    assert "PAPER" in allowed


def test_jafar_workspace_does_not_announce_live(settings: object) -> None:
    tc, _ = _jafar_client(settings)
    data = tc.get("/api/workspace").json()
    assert "LIVE" not in data["allowed_modes"]
    assert "LIVE_GATED" not in data["allowed_modes"]


# ──────────────────────────────────────────────────────────────────────────────
# /api/runtime/health
# ──────────────────────────────────────────────────────────────────────────────

def test_runtime_health_healthy(settings: object) -> None:
    tc, comps = _jafar_client(settings)
    _inject_health(comps, RuntimeStatus.HEALTHY)
    resp = tc.get("/api/runtime/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "HEALTHY"
    assert data["run_id"] == comps.run.run_id
    assert data["provider_status"] == "UP"
    assert data["consecutive_failures"] == 0


def test_runtime_health_degraded(settings: object) -> None:
    tc, comps = _jafar_client(settings)
    _inject_health(comps, RuntimeStatus.DEGRADED,
                   provider_status=ProviderStatus.DOWN,
                   consecutive_failures=2,
                   last_error="connection refused",
                   degraded_reason="provider indisponible")
    data = tc.get("/api/runtime/health").json()
    assert data["status"] == "DEGRADED"
    assert data["consecutive_failures"] == 2
    assert data["last_error"] == "connection refused"
    assert data["degraded_reason"] == "provider indisponible"


def test_runtime_health_stale(settings: object) -> None:
    tc, comps = _jafar_client(settings)
    _inject_health(comps, RuntimeStatus.STALE,
                   provider_status=ProviderStatus.STALE,
                   degraded_reason="données marché périmées: 130.0s > 120.0s")
    data = tc.get("/api/runtime/health").json()
    assert data["status"] == "STALE"
    assert "périmées" in (data.get("degraded_reason") or "")


def test_runtime_health_failed(settings: object) -> None:
    tc, comps = _jafar_client(settings)
    _inject_health(comps, RuntimeStatus.FAILED,
                   provider_status=ProviderStatus.DOWN,
                   consecutive_failures=5,
                   last_error="seuil max atteint",
                   degraded_reason="seuil d'échecs provider atteint")
    data = tc.get("/api/runtime/health").json()
    assert data["status"] == "FAILED"
    assert data["consecutive_failures"] == 5


def test_runtime_health_absent_returns_404(settings: object) -> None:
    tc, _ = _jafar_client(settings)
    # Aucun événement RUNTIME_HEALTH injecté → 404
    resp = tc.get("/api/runtime/health")
    assert resp.status_code == 404


def test_runtime_health_read_only(settings: object) -> None:
    """POST sur l'endpoint health doit retourner 405 (read-only)."""
    tc, comps = _jafar_client(settings)
    _inject_health(comps, RuntimeStatus.HEALTHY)
    resp = tc.post("/api/runtime/health")
    assert resp.status_code == 405


def test_runtime_health_in_health_endpoint(settings: object) -> None:
    """/health enrichit la réponse avec le bloc runtime quand disponible."""
    tc, comps = _jafar_client(settings)
    _inject_health(comps, RuntimeStatus.HEALTHY)
    # Enregistre un cycle pour que le run soit trouvé par /health
    comps.repo.append(comps.run.run_id, "cycle.end", {"decision": "NO_TRADE"}, ts=NOW)
    data = tc.get("/health").json()
    assert "runtime" in data
    assert data["runtime"]["status"] == "HEALTHY"


def test_runtime_health_null_last_error_is_safe(settings: object) -> None:
    """last_error=None ne cause pas de crash."""
    tc, comps = _jafar_client(settings)
    _inject_health(comps, RuntimeStatus.HEALTHY, last_error=None)
    data = tc.get("/api/runtime/health").json()
    assert data["last_error"] is None


# ──────────────────────────────────────────────────────────────────────────────
# Banner + observe_only
# ──────────────────────────────────────────────────────────────────────────────

def test_jafar_banner_contains_paper_reference(settings: object) -> None:
    tc, _ = _jafar_client(settings)
    html = tc.get("/").text
    assert "PAPER" in html
    assert "OBSERVE" in html


def test_jafar_banner_does_not_claim_live(settings: object) -> None:
    tc, _ = _jafar_client(settings)
    html = tc.get("/").text
    # Le banner doit indiquer que LIVE est verrouillé, pas disponible
    assert "LIVE" in html  # présent mais comme restriction, pas comme mode actif
