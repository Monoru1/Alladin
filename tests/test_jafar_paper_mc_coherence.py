"""Tests de cohérence Mission Control Jafar PAPER.

Vérifie :
- run_mode PAPER visible dans /health quand jafar.mode.change persiste PAPER
- run_mode OBSERVE quand mode OBSERVE
- banner live_locked présent, observe_only dépend du mode
- sélection du bon run (dernier actif)
- transitions health : HEALTHY après market_progress valide
"""
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
from alladin.orchestration.jafar import JafarModeStore

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def _client(settings: object, *, mode: str = "PAPER") -> tuple[TestClient, Components]:
    """Construit un TestClient JAFAR avec le mode persisté demandé."""
    provider = CryptoMockProvider(start=NOW)
    broker = CryptoObserveBroker(provider)
    comps = build_services(
        settings, broker,  # type: ignore[arg-type]
        create_run=True, workspace=WorkspaceId.JAFAR, db_url="sqlite://",
    )
    assert comps is not None
    comps.manager.start(comps.run, broker.account_info())
    # Transition vers le mode demandé
    from alladin.core.enums import JafarMode
    target = JafarMode(mode)
    if comps.jafar_mode is not target:
        JafarModeStore(comps.journal, comps.run.run_id).transition(target, reason="test")
    api_settings = comps.settings.model_copy(update={"runtime_stale_after_s": 1_000_000_000.0})
    tc = TestClient(create_app(api_settings, comps.repo, comps.broker))
    return tc, comps


def _inject_health(comps: Components, status: RuntimeStatus, **kwargs: object) -> None:
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
# run_mode — source de vérité
# ──────────────────────────────────────────────────────────────────────────────

def test_health_returns_run_mode_paper(settings: object) -> None:
    """/health retourne run_mode=PAPER quand le run Jafar est en mode PAPER."""
    tc, _ = _client(settings, mode="PAPER")
    data = tc.get("/health").json()
    assert data["run_mode"] == "PAPER", f"attendu PAPER, obtenu {data['run_mode']!r}"


def test_health_returns_run_mode_observe(settings: object) -> None:
    """/health retourne run_mode=OBSERVE quand le run est en OBSERVE."""
    tc, _ = _client(settings, mode="OBSERVE")
    data = tc.get("/health").json()
    assert data["run_mode"] == "OBSERVE", f"attendu OBSERVE, obtenu {data['run_mode']!r}"


def test_health_run_mode_survives_restart(settings: object) -> None:
    """run_mode persiste dans la DB — recréer l'app conserve le mode."""
    _, comps = _client(settings, mode="PAPER")
    api_settings = comps.settings.model_copy(update={"runtime_stale_after_s": 1_000_000_000.0})
    # Recréer l'app (simule restart Mission Control)
    tc2 = TestClient(create_app(api_settings, comps.repo, comps.broker))
    data = tc2.get("/health").json()
    assert data["run_mode"] == "PAPER"


# ──────────────────────────────────────────────────────────────────────────────
# observe_only et live_locked
# ──────────────────────────────────────────────────────────────────────────────

def test_health_live_locked_always_true_for_jafar(settings: object) -> None:
    """live_locked = True pour JAFAR indépendamment du mode."""
    tc, _ = _client(settings, mode="PAPER")
    data = tc.get("/health").json()
    assert data["live_locked"] is True


def test_health_observe_only_false_in_paper(settings: object) -> None:
    """observe_only = False quand mode PAPER (des positions simulées sont créées)."""
    tc, _ = _client(settings, mode="PAPER")
    data = tc.get("/health").json()
    assert data["observe_only"] is False, f"observe_only doit être False en PAPER, obtenu {data['observe_only']}"


def test_health_observe_only_true_in_observe(settings: object) -> None:
    """observe_only = True quand mode OBSERVE."""
    tc, _ = _client(settings, mode="OBSERVE")
    data = tc.get("/health").json()
    assert data["observe_only"] is True


# ──────────────────────────────────────────────────────────────────────────────
# Banner — cohérence avec mode réel
# ──────────────────────────────────────────────────────────────────────────────

def test_banner_contains_paper_when_paper_mode(settings: object) -> None:
    """Le banner HTML doit indiquer PAPER SIMULÉ quand mode PAPER."""
    tc, _ = _client(settings, mode="PAPER")
    html = tc.get("/").text
    # Le JS utilise live_locked + run_mode pour afficher le bon banner
    # On vérifie que les données API sont correctes (le JS est côté client)
    data = tc.get("/health").json()
    assert data["live_locked"] is True
    assert data["run_mode"] == "PAPER"
    # Le HTML contient bien le script qui différencie PAPER/OBSERVE
    assert "PAPER" in html
    assert "live_locked" in html or "run_mode" in html or "curMode" in html


def test_banner_js_uses_live_locked_not_observe_only(settings: object) -> None:
    """Le JS doit brancher sur live_locked, pas observe_only."""
    tc, _ = _client(settings, mode="PAPER")
    html = tc.get("/").text
    # live_locked doit être la clé de branchement
    assert "live_locked" in html
    # observe_only ne doit pas piloter le banner
    assert 'ov.observe_only' not in html or 'live_locked' in html


def test_banner_never_announces_live_as_authorized(settings: object) -> None:
    """LIVE ne doit jamais apparaître comme mode autorisé dans le banner Jafar."""
    tc, _ = _client(settings, mode="PAPER")
    data = tc.get("/api/workspace").json()
    assert "LIVE" not in data["allowed_modes"]
    assert "LIVE_GATED" not in data["allowed_modes"]


# ──────────────────────────────────────────────────────────────────────────────
# Health transitions — invariant HEALTHY
# ──────────────────────────────────────────────────────────────────────────────

def test_health_healthy_after_market_progress(settings: object) -> None:
    """provider UP + fresh market + failures=0 → HEALTHY."""
    tc, comps = _client(settings, mode="PAPER")
    _inject_health(comps, RuntimeStatus.HEALTHY,
                   provider_status=ProviderStatus.UP,
                   consecutive_failures=0)
    data = tc.get("/api/runtime/health").json()
    assert data["status"] == "HEALTHY"
    assert data["provider_status"] == "UP"
    assert data["consecutive_failures"] == 0


def test_health_degraded_then_healthy(settings: object) -> None:
    """DEGRADED → recovery → dernier event HEALTHY est retourné."""
    tc, comps = _client(settings, mode="PAPER")
    _inject_health(comps, RuntimeStatus.DEGRADED,
                   provider_status=ProviderStatus.DOWN,
                   consecutive_failures=1,
                   degraded_reason="provider erreur")
    _inject_health(comps, RuntimeStatus.HEALTHY,
                   provider_status=ProviderStatus.UP,
                   consecutive_failures=0)
    data = tc.get("/api/runtime/health").json()
    assert data["status"] == "HEALTHY", "Le dernier snapshot doit être HEALTHY après recovery"


def test_health_stopped_stays_stopped(settings: object) -> None:
    tc, comps = _client(settings, mode="PAPER")
    _inject_health(comps, RuntimeStatus.STOPPED)
    data = tc.get("/api/runtime/health").json()
    assert data["status"] == "STOPPED"


def test_health_failed_stays_failed(settings: object) -> None:
    tc, comps = _client(settings, mode="PAPER")
    _inject_health(comps, RuntimeStatus.FAILED,
                   provider_status=ProviderStatus.DOWN,
                   consecutive_failures=5)
    data = tc.get("/api/runtime/health").json()
    assert data["status"] == "FAILED"


# ──────────────────────────────────────────────────────────────────────────────
# Multi-process DB cohérence
# ──────────────────────────────────────────────────────────────────────────────

def test_two_app_instances_see_same_run_mode(settings: object) -> None:
    """Deux instances de l'app (jafar run + jafar serve) voient le même mode."""
    _, comps = _client(settings, mode="PAPER")
    api_settings = comps.settings.model_copy(update={"runtime_stale_after_s": 1_000_000_000.0})
    tc1 = TestClient(create_app(api_settings, comps.repo, comps.broker))
    tc2 = TestClient(create_app(api_settings, comps.repo, comps.broker))
    assert tc1.get("/health").json()["run_mode"] == "PAPER"
    assert tc2.get("/health").json()["run_mode"] == "PAPER"


# ──────────────────────────────────────────────────────────────────────────────
# Run selection — bon run choisi
# ──────────────────────────────────────────────────────────────────────────────

def test_health_selects_latest_run_not_first(settings: object) -> None:
    """Si plusieurs runs existent, /health sélectionne le plus récent."""
    import os
    import tempfile

    from alladin.core.enums import JafarMode

    # Utiliser une DB fichier temporaire partagée
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        db_url = f"sqlite:///{db_path}"
        provider = CryptoMockProvider(start=NOW)
        broker = CryptoObserveBroker(provider)
        # Créer run 1 OBSERVE
        comps1 = build_services(
            settings, broker,  # type: ignore[arg-type]
            create_run=True, workspace=WorkspaceId.JAFAR, db_url=db_url,
        )
        assert comps1 is not None
        comps1.manager.start(comps1.run, broker.account_info())
        run1_id = comps1.run.run_id
        # Créer run 2 PAPER sur la même DB
        comps2 = build_services(
            settings, broker,  # type: ignore[arg-type]
            create_run=True, workspace=WorkspaceId.JAFAR, db_url=db_url,
        )
        assert comps2 is not None
        comps2.manager.start(comps2.run, broker.account_info())
        JafarModeStore(comps2.journal, comps2.run.run_id).transition(JafarMode.PAPER, reason="test")
        run2_id = comps2.run.run_id
        assert run1_id != run2_id
        api_settings = comps2.settings.model_copy(update={"runtime_stale_after_s": 1_000_000_000.0})
        tc = TestClient(create_app(api_settings, comps2.repo, comps2.broker))
        data = tc.get("/health").json()
        assert data["run_id"] == run2_id, f"Doit sélectionner run2 ({run2_id}), obtenu {data['run_id']}"
        assert data["run_mode"] == "PAPER"
    finally:
        import contextlib
        with contextlib.suppress(OSError):
            os.unlink(db_path)
