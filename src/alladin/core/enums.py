"""Énumérations partagées."""

from __future__ import annotations

from enum import StrEnum


class TradingMode(StrEnum):
    DEMO = "demo"  # seul mode existant dans cette version


class AccountType(StrEnum):
    DEMO = "DEMO"
    CONTEST = "CONTEST"
    LIVE = "LIVE"
    UNKNOWN = "UNKNOWN"


class RunState(StrEnum):
    CREATED = "CREATED"
    READY = "READY"
    RUNNING = "RUNNING"
    TARGET_REACHED = "TARGET_REACHED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    PAUSED = "PAUSED"
    KILLED = "KILLED"

    @property
    def is_terminal(self) -> bool:
        return self in TERMINAL_STATES


TERMINAL_STATES = frozenset({RunState.PASSED, RunState.FAILED, RunState.KILLED})


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def sign(self) -> int:
        return 1 if self is Side.BUY else -1

    @property
    def opposite(self) -> Side:
        return Side.SELL if self is Side.BUY else Side.BUY


class EntryType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class OrderAction(StrEnum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    MODIFY = "MODIFY"


class MarketRegime(StrEnum):
    TREND = "TREND"
    RANGE = "RANGE"
    BREAKOUT = "BREAKOUT"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    REVERSAL_CONTEXT = "REVERSAL_CONTEXT"
    NEWS_EVENT = "NEWS_EVENT"
    UNKNOWN = "UNKNOWN"


class Timeframe(StrEnum):
    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    M30 = "M30"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"

    @property
    def minutes(self) -> int:
        return {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}[self.value]


class SymbolTradeMode(StrEnum):
    DISABLED = "DISABLED"
    LONG_ONLY = "LONG_ONLY"
    SHORT_ONLY = "SHORT_ONLY"
    CLOSE_ONLY = "CLOSE_ONLY"
    FULL = "FULL"


class AssetCategory(StrEnum):
    CRYPTO_SPOT = "CRYPTO_SPOT"
    CRYPTO_PERP = "CRYPTO_PERP"
    FOREX_MAJOR = "FOREX_MAJOR"
    FOREX_MINOR = "FOREX_MINOR"  # crosses sans JPY
    FOREX_JPY = "FOREX_JPY"
    FOREX_EXOTIC = "FOREX_EXOTIC"
    METAL = "METAL"
    OTHER = "OTHER"


class RuleSource(StrEnum):
    OFFICIAL = "official"  # règle du programme FTMO
    EXTRA = "extra"  # règle expérimentale ALLADIN


class CloseReason(StrEnum):
    SL = "SL"
    TP = "TP"
    MANUAL = "MANUAL"
    EXPERT = "EXPERT"  # fermé par ALLADIN (ordre de fermeture)
    STOP_OUT = "STOP_OUT"
    UNKNOWN = "UNKNOWN"


class DealEntry(StrEnum):
    IN = "IN"
    OUT = "OUT"
    INOUT = "INOUT"
    OUT_BY = "OUT_BY"
    OTHER = "OTHER"


class DecisionKind(StrEnum):
    TRADE = "TRADE"
    NO_TRADE = "NO_TRADE"


class RunMode(StrEnum):
    """Mode d'exécution du daemon ALLADIN.

    OBSERVE : scan réel, analyse complète, RiskEngine actif, AUCUN order_send.
    PAPER   : même pipeline + simulation interne des trades (P&L calculé sans broker).
    DEMO    : order_send autorisé uniquement si account_type == DEMO et toutes sécurités passent.

    Le mode par défaut est OBSERVE.  L'utilisateur doit explicitement activer DEMO.
    """

    OBSERVE = "OBSERVE"
    PAPER = "PAPER"
    DEMO = "DEMO"
