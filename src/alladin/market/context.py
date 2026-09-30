"""Abstraction du contexte macro / news. Aucune source concrète n'est scrapée dans cette version.

Sources prévues (à brancher derrière cette interface) : calendrier économique (Forex Factory,
Trading Economics), banques centrales, CME FedWatch, CFTC COT, flux de news financières.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta

from pydantic import BaseModel


class MacroEvent(BaseModel):
    time: datetime
    currency: str
    title: str
    impact: str = "high"  # low | medium | high


class MarketContext(BaseModel):
    events: list[MacroEvent] = []
    notes: list[str] = []

    @property
    def news_blackout(self) -> bool:
        return any(e.impact == "high" for e in self.events)


class MarketContextProvider(ABC):
    @abstractmethod
    def get_context(self, currencies: tuple[str, ...], now: datetime) -> MarketContext:
        """Événements macro proches (fenêtre ±30 min) concernant les devises données."""


MacroProvider = MarketContextProvider


class NullContextProvider(MarketContextProvider):
    def get_context(self, currencies: tuple[str, ...], now: datetime) -> MarketContext:
        return MarketContext(notes=["aucun fournisseur macro configuré"])


class StaticContextProvider(MarketContextProvider):
    """Calendrier fixe (tests, démos)."""

    def __init__(self, events: list[MacroEvent], window: timedelta = timedelta(minutes=30)) -> None:
        self.events = events
        self.window = window

    def get_context(self, currencies: tuple[str, ...], now: datetime) -> MarketContext:
        near = [e for e in self.events if e.currency in currencies and abs(e.time - now) <= self.window]
        return MarketContext(events=near)
