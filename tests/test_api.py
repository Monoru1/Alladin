"""Mission Control : données réelles, sérialisation et surface HTTP read-only."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from alladin.api.app import create_app
from alladin.brokers.mock import MockBroker
from alladin.core.enums import AccountType
from alladin.orchestration.bootstrap import Components
from tests.conftest import make_intent


def client(svc: Components) -> TestClient:
    return TestClient(create_app(svc.settings, svc.repo, svc.broker))


def test_mission_control_overview_position_cycles_and_journal(svc: Components) -> None:
    result = svc.execution.submit(make_intent(svc))
    assert result.executed
    api = client(svc)
    assert "MISSION CONTROL" in api.get("/").text
    overview = api.get("/api/overview").json()
    assert overview["account"]["account_type"] == "DEMO"
    assert overview["risk"]["working_capital"] == pytest.approx(10_000, rel=0.001)
    assert overview["journal"]["ok"]
    (position,) = api.get("/api/positions").json()
    assert position["ticket"] == result.position_ticket and position["trade"]["strategy_id"] == "TREND-01"
    assert api.get("/api/journal").json()
    assert api.get("/api/strategies").status_code == 200
    research = api.get("/api/research").json()
    assert research["pipeline"][0] == "DISCOVERED" and research["experiments"] == []


def test_api_has_no_mutating_or_trading_route(svc: Components) -> None:
    app = create_app(svc.settings, svc.repo, svc.broker)
    methods = {method for route in app.routes for method in getattr(route, "methods", set())}
    assert methods <= {"GET", "HEAD"}
    paths = {route.path.lower() for route in app.routes}
    assert not any(any(word in path for word in ("/trade", "/order", "/execute", "/close")) for path in paths)


def test_live_or_unknown_account_is_visibly_blocked(svc: Components) -> None:
    broker = MockBroker(account_type=AccountType.UNKNOWN)
    broker.connect()
    data = TestClient(create_app(svc.settings, svc.repo, broker)).get("/api/overview").json()
    assert data["execution_blocked"] is True


def test_credentials_are_never_serialized(svc: Components) -> None:
    blob = client(svc).get("/api/overview").text.lower()
    assert "password" not in blob and "mt5_login" not in blob and "12345678" not in blob


# ---------------------------------------------------------------------------
# Phase 15-16: Observability & Robustness Tests
# ---------------------------------------------------------------------------

def test_btc_experiments_endpoint_returns_valid_structure(svc: Components) -> None:
    """GET /api/btc/experiments must return a valid structure even with no data."""
    api = client(svc)
    resp = api.get("/api/btc/experiments")
    assert resp.status_code == 200
    data = resp.json()
    assert "experiments" in data
    assert "active" in data
    assert "total" in data
    assert isinstance(data["experiments"], list)
    assert data["total"] >= 0


def test_health_endpoint_structure(svc: Components) -> None:
    """GET /health returns all expected fields."""
    api = client(svc)
    resp = api.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "broker_connected" in data
    assert "demo" in data
    assert "last_cycle_at" in data


def test_all_get_endpoints_respond_without_crash(svc: Components) -> None:
    """Every registered GET endpoint must respond without 500."""
    result = svc.execution.submit(make_intent(svc))
    assert result.executed
    api = client(svc)
    endpoints = ["/", "/health", "/api/overview", "/api/runs", "/api/positions",
                 "/api/market", "/api/journal", "/api/strategies", "/api/research",
                 "/api/opportunities", "/api/btc/experiments"]
    for ep in endpoints:
        resp = api.get(ep)
        assert resp.status_code < 500, f"{ep} returned {resp.status_code}"


def test_no_endpoint_allows_post_put_delete(svc: Components) -> None:
    """Verify the API surface is strictly read-only: no POST, PUT, DELETE, PATCH."""
    app = create_app(svc.settings, svc.repo, svc.broker)
    for route in app.routes:
        methods = getattr(route, "methods", set())
        forbidden = methods & {"POST", "PUT", "DELETE", "PATCH"}
        assert not forbidden, f"{getattr(route, 'path', '?')} allows {forbidden}"


def test_missing_data_returns_empty_not_500() -> None:
    """API with no broker and empty DB must still respond, not crash."""
    from alladin.core.config import Settings
    from alladin.journal.repository import JournalRepository
    settings = Settings(ALLADIN_DATA_DIR="/tmp/alladin_test_empty", _env_file=None)  # type: ignore[call-arg]
    repo = JournalRepository.from_url("sqlite://")
    app = create_app(settings, repo, broker=None)
    api = TestClient(app)
    # Health must work even without broker
    resp = api.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["broker_connected"] is False
    # BTC experiments must work with no data
    resp = api.get("/api/btc/experiments")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0
