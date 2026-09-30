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
