"""API FastAPI en LECTURE SEULE : runs, état, journal, statistiques. Volontairement sans endpoint de trading."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException

from alladin.core.config import Settings, get_settings
from alladin.journal.repository import JournalRepository
from alladin.journal.service import JournalService


def create_app(settings: Settings | None = None, repo: JournalRepository | None = None) -> FastAPI:
    settings = settings or get_settings()
    repo = repo or JournalRepository.from_url(settings.db_url)
    journal = JournalService(repo)
    app = FastAPI(title="ALLADIN", description="Lecture seule — aucun ordre ne transite par l'API.")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "trading_mode": settings.trading_mode}

    @app.get("/runs")
    def runs() -> list[dict[str, Any]]:
        return [r.model_dump(mode="json", exclude={"watchdog_state"}) for r in repo.list_runs()]

    @app.get("/runs/{run_id}")
    def run(run_id: str) -> dict[str, Any]:
        rec = repo.get_run(run_id)
        if rec is None:
            raise HTTPException(404, "run inconnu")
        return rec.model_dump(mode="json")

    @app.get("/runs/{run_id}/journal")
    def events(run_id: str, type: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        return [
            e.model_dump(mode="json")
            for e in repo.events(run_id, [type] if type else None, limit=min(limit, 1000), desc=True)
        ]

    @app.get("/runs/{run_id}/trades")
    def trades(run_id: str) -> list[dict[str, Any]]:
        return [t.model_dump(mode="json") for t in repo.trades_for_run(run_id)]

    @app.get("/runs/{run_id}/verify")
    def verify(run_id: str) -> dict[str, Any]:
        ok, msg = repo.verify_chain(run_id)
        return {"ok": ok, "detail": msg}

    @app.get("/stats/{dimension}")
    def stats(dimension: str, run_id: str | None = None) -> list[dict[str, Any]]:
        if dimension not in ("strategy", "symbol", "regime", "session", "agent"):
            raise HTTPException(400, "dimension invalide")
        return [s.model_dump() for s in journal.stats(dimension, run_id)]

    return app
