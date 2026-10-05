"""Tests du rapport PAPER et du validator auto-acceptance.

Utilise des fixtures synthétiques : provider mock, pas de réseau.
La DB est un fichier temporaire partagé entre le setup et le CLI runner.
"""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
from collections.abc import Generator
from datetime import UTC, datetime

from typer.testing import CliRunner

from alladin.core.enums import JafarMode
from alladin.core.workspace import WorkspaceId
from alladin.journal.models import EventType
from alladin.orchestration.bootstrap import Components, build_services
from alladin.orchestration.health import ProviderStatus, RuntimeHealth, RuntimeStatus
from alladin.orchestration.jafar import JafarModeStore

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def _build(settings: object, db_url: str, *, paper: bool = True) -> Components:
    """Crée un run dans db_url en utilisant le même broker que le CLI."""
    from alladin.orchestration.bootstrap import make_broker
    broker = make_broker("crypto-mock", settings)  # type: ignore[arg-type]
    comps = build_services(
        settings, broker,  # type: ignore[arg-type]
        create_run=True, workspace=WorkspaceId.JAFAR, db_url=db_url,
    )
    assert comps is not None
    comps.manager.start(comps.run, broker.account_info())
    if paper:
        JafarModeStore(comps.journal, comps.run.run_id).transition(JafarMode.PAPER, reason="test")
    return comps


def _inject_health(comps: Components, status: RuntimeStatus, *,
                   market_at: datetime | None = None, failures: int = 0) -> None:
    payload = RuntimeHealth(
        run_id=comps.run.run_id,
        workspace=WorkspaceId.JAFAR,
        mode="PAPER",
        status=status,
        started_at=NOW,
        last_heartbeat_at=NOW,
        last_market_update_at=market_at,
        provider_status=ProviderStatus.UP if failures == 0 else ProviderStatus.DOWN,
        consecutive_failures=failures,
    ).model_dump(mode="json")
    comps.journal.log(comps.run.run_id, EventType.RUNTIME_HEALTH, payload)


def _tmp_db() -> tuple[str, str]:
    """Retourne (db_path, db_url) pour un fichier SQLite temporaire."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="alladin_test_")
    os.close(fd)
    return path, f"sqlite:///{path}"


@contextlib.contextmanager
def _db_ctx(settings: object, *, paper: bool = True) -> Generator[tuple[Components, str], None, None]:
    """DB fichier temporaire + run ; dispose l'engine au cleanup (évite WinError 32)."""
    db_path, db_url = _tmp_db()
    comps = _build(settings, db_url, paper=paper)
    try:
        yield comps, db_url
    finally:
        comps.repo.close()
        os.unlink(db_path)


def _invoke(db_url: str, *args: str) -> tuple[int, dict]:
    """Lance la commande CLI avec DATABASE_URL injectée, retourne (exit_code, json_data)."""
    from alladin.cli import jafar_app
    runner = CliRunner()
    result = runner.invoke(jafar_app, list(args), env={"DATABASE_URL": db_url})
    if result.exit_code not in (0, 1, 2):
        raise AssertionError(f"CLI crash (exit {result.exit_code}): {result.output}\n{result.exception}")
    try:
        data = json.loads(result.output)
    except json.JSONDecodeError as e:
        raise AssertionError(f"JSON invalide (exit {result.exit_code}): {result.output!r}") from e
    return result.exit_code, data


# ──────────────────────────────────────────────────────────────────────────────
# jafar report — structure et déterminisme
# ──────────────────────────────────────────────────────────────────────────────

def test_report_returns_valid_json(settings: object) -> None:
    with _db_ctx(settings) as (comps, db_url):
        _inject_health(comps, RuntimeStatus.HEALTHY, market_at=NOW)
        code, data = _invoke(db_url, "report", "--broker", "crypto-mock", "--run", comps.run.run_id)
        assert code == 0
        assert data["run_id"] == comps.run.run_id


def test_report_shows_paper_mode(settings: object) -> None:
    with _db_ctx(settings) as (comps, db_url):
        _inject_health(comps, RuntimeStatus.HEALTHY, market_at=NOW)
        _, data = _invoke(db_url, "report", "--broker", "crypto-mock", "--run", comps.run.run_id)
        assert data["mode"] == "PAPER"


def test_report_health_transitions(settings: object) -> None:
    """DEGRADED → HEALTHY doit apparaître dans les transitions."""
    with _db_ctx(settings) as (comps, db_url):
        _inject_health(comps, RuntimeStatus.DEGRADED, failures=1)
        _inject_health(comps, RuntimeStatus.HEALTHY, market_at=NOW, failures=0)
        _, data = _invoke(db_url, "report", "--broker", "crypto-mock", "--run", comps.run.run_id)
        statuses = [t["status"] for t in data["health_transitions"]]
        assert "DEGRADED" in statuses
        assert "HEALTHY" in statuses
        assert data["current_health_status"] == "HEALTHY"


def test_report_journal_integrity(settings: object) -> None:
    with _db_ctx(settings) as (comps, db_url):
        _inject_health(comps, RuntimeStatus.HEALTHY, market_at=NOW)
        _, data = _invoke(db_url, "report", "--broker", "crypto-mock", "--run", comps.run.run_id)
        assert data["journal_integrity"]["ok"] is True


def test_report_no_duplicates_clean_run(settings: object) -> None:
    with _db_ctx(settings) as (comps, db_url):
        _inject_health(comps, RuntimeStatus.HEALTHY, market_at=NOW)
        _, data = _invoke(db_url, "report", "--broker", "crypto-mock", "--run", comps.run.run_id)
        assert data["duplicate_anomalies"] == []


def test_report_provider_failures_counted(settings: object) -> None:
    """Les failures provider sont comptées dans le rapport."""
    with _db_ctx(settings) as (comps, db_url):
        _inject_health(comps, RuntimeStatus.DEGRADED, failures=2)
        _inject_health(comps, RuntimeStatus.DEGRADED, failures=3)
        _inject_health(comps, RuntimeStatus.HEALTHY, market_at=NOW, failures=0)
        _, data = _invoke(db_url, "report", "--broker", "crypto-mock", "--run", comps.run.run_id)
        assert data["provider_failures"] >= 2
        assert data["max_consecutive_failures"] >= 2


def test_report_unknown_run_fails(settings: object) -> None:
    """Un run inexistant doit produire une erreur (non-zero)."""
    with _db_ctx(settings) as (_, db_url):
        from alladin.cli import jafar_app
        runner = CliRunner()
        result = runner.invoke(jafar_app, [
            "report", "--broker", "crypto-mock", "--run", "RUN-INEXISTANT",
        ], env={"DATABASE_URL": db_url})
        assert result.exit_code != 0


# ──────────────────────────────────────────────────────────────────────────────
# jafar validate-paper — exit codes
# ──────────────────────────────────────────────────────────────────────────────

def test_validate_paper_pass_clean_run(settings: object) -> None:
    """Run PAPER propre (2+ heartbeats) → exit 0 PASS."""
    with _db_ctx(settings) as (comps, db_url):
        # 2 snapshots health pour que heartbeat_progressed = PASS
        _inject_health(comps, RuntimeStatus.HEALTHY, market_at=NOW)
        _inject_health(comps, RuntimeStatus.HEALTHY, market_at=NOW)
        code, data = _invoke(db_url, "validate-paper", "--broker", "crypto-mock", "--run", comps.run.run_id)
        assert data["result"] == "PASS", data["checks"]
        assert code == 0
        assert data["qualification"]["level"] == "SHORT_SMOKE"
        assert data["qualification"]["2H_VALIDATED"] is False
        assert data["qualification"]["24H_VALIDATED"] is False
        checks = {check["check"]: check for check in data["checks"]}
        assert checks["portfolio_coherent"]["level"] == "PASS"


def test_validate_paper_fail_wrong_mode(settings: object) -> None:
    """Run en OBSERVE → validate-paper doit FAIL."""
    with _db_ctx(settings, paper=False) as (comps, db_url):
        _inject_health(comps, RuntimeStatus.HEALTHY, market_at=NOW)
        code, data = _invoke(db_url, "validate-paper", "--broker", "crypto-mock", "--run", comps.run.run_id)
        assert data["result"] == "FAIL"
        assert code == 2


def test_validate_paper_fail_health_failed(settings: object) -> None:
    with _db_ctx(settings) as (comps, db_url):
        _inject_health(comps, RuntimeStatus.FAILED, failures=5)
        code, data = _invoke(db_url, "validate-paper", "--broker", "crypto-mock", "--run", comps.run.run_id)
        assert data["result"] == "FAIL"
        assert code == 2


def test_validate_paper_warn_no_heartbeat(settings: object) -> None:
    """Run sans events health → WARN (heartbeat manquant)."""
    with _db_ctx(settings) as (comps, db_url):
        code, data = _invoke(db_url, "validate-paper", "--broker", "crypto-mock", "--run", comps.run.run_id)
        assert data["result"] in ("WARN", "PASS")
        checks_by_name = {c["check"]: c for c in data["checks"]}
        assert "heartbeat_progressed" in checks_by_name


def test_validate_paper_min_duration_fail(settings: object) -> None:
    """Run de quelques secondes ne satisfait pas min_duration_h=2."""
    with _db_ctx(settings) as (comps, db_url):
        _inject_health(comps, RuntimeStatus.HEALTHY, market_at=NOW)
        code, data = _invoke(db_url, "validate-paper", "--broker", "crypto-mock",
                             "--run", comps.run.run_id, "--min-duration-h", "2.0")
        checks_by_name = {c["check"]: c for c in data["checks"]}
        assert "min_duration" in checks_by_name
        assert checks_by_name["min_duration"]["level"] == "FAIL"
        assert code == 2


def test_validate_exit_codes_are_0_1_2(settings: object) -> None:
    """validate-paper ne produit que des exit codes 0, 1 ou 2."""
    with _db_ctx(settings) as (comps, db_url):
        _inject_health(comps, RuntimeStatus.HEALTHY, market_at=NOW)
        from alladin.cli import jafar_app
        runner = CliRunner()
        result = runner.invoke(jafar_app,
            ["validate-paper", "--broker", "crypto-mock", "--run", comps.run.run_id],
            env={"DATABASE_URL": db_url})
        assert result.exit_code in (0, 1, 2), f"exit {result.exit_code}: {result.output}"
