"""BrokerAdapter : abstraction broker. `send_order` est un template method non surchargeable en pratique.

Toute implémentation passe obligatoirement par :
  1. vérification du jeton d'approbation du RiskEngine ;
  2. vérification FRAÎCHE que le compte est DEMO (fail closed) ;
  3. seulement ensuite `_send()`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from alladin.core.approval import ApprovalToken, verify_token
from alladin.core.enums import AccountType, AssetCategory, Timeframe
from alladin.core.errors import ExecutionBlockedError
from alladin.core.models import (
    AccountSnapshot,
    Bar,
    Deal,
    InstrumentSpec,
    OrderCheck,
    OrderRequest,
    OrderResult,
    PendingOrder,
    Position,
    Tick,
)

RETCODE_DONE = 10009
RETCODE_DONE_PARTIAL = 10010
RETCODE_PLACED = 10008
RETCODE_REJECT = 10006
RETCODE_INVALID = 10013
RETCODE_INVALID_VOLUME = 10014
RETCODE_INVALID_STOPS = 10016
RETCODE_NO_MONEY = 10019
RETCODE_MARKET_CLOSED = 10018
RETCODE_TRADE_DISABLED = 10017
RETCODE_BLOCKED = -1  # blocage ALLADIN avant envoi (pas un retcode MT5)


@dataclass(frozen=True)
class BrokerCapabilities:
    """Manifeste de ce que le broker peut fournir comme données."""

    name: str  # ex: "mt5:ICMarkets", "binance:public"
    has_tick: bool = True
    has_bars: bool = True
    has_spread: bool = True  # spread réel dans les barres (False pour Binance public)
    has_close_time: bool = False  # close_time explicite par barre
    has_tick_volume: bool = True
    has_real_volume: bool = False
    supported_timeframes: frozenset[Timeframe] = field(
        default_factory=lambda: frozenset(Timeframe)
    )
    max_bars: int = 10000
    provenance_tag: str = ""  # tag pour traçabilité dans l'archive
    can_close_position: bool = False
    can_partial_close: bool = False
    can_modify_stop: bool = False
    can_modify_target: bool = False
    reliable_position_reconciliation: bool = False
    is_24_7: bool = False
    has_funding_rate: bool = False
    has_maker_taker_fees: bool = False
    supported_asset_categories: frozenset[AssetCategory] = field(default_factory=frozenset)
    can_open_position: bool = True  # legacy trading adapters; data-only adapters must override


def block_message(account_type: AccountType) -> str:
    if account_type is AccountType.LIVE:
        return "LIVE ACCOUNT DETECTED — EXECUTION BLOCKED"
    return "ACCOUNT TYPE UNKNOWN — EXECUTION BLOCKED"


class BrokerAdapter(ABC):
    name: str = "BROKER"

    def capabilities(self) -> BrokerCapabilities:
        """Manifeste des capacités de données du broker. Surcharger pour chaque implémentation."""
        return BrokerCapabilities(name=self.name)

    # ------------------------------------------------------------------ connexion / compte

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def account_info(self) -> AccountSnapshot: ...

    def assert_demo(self) -> AccountSnapshot:
        """Lit le compte MAINTENANT et refuse tout sauf un compte DEMO identifié avec certitude."""
        try:
            acct = self.account_info()
        except Exception as exc:  # fail closed : impossible de lire le compte => impossible d'exécuter
            raise ExecutionBlockedError(f"ACCOUNT TYPE UNKNOWN — EXECUTION BLOCKED ({exc})") from exc
        if acct.account_type is not AccountType.DEMO:
            raise ExecutionBlockedError(block_message(acct.account_type))
        return acct

    # ------------------------------------------------------------------ marché

    @abstractmethod
    def list_symbols(self) -> list[InstrumentSpec]: ...

    @abstractmethod
    def symbol_spec(self, symbol: str) -> InstrumentSpec | None: ...

    @abstractmethod
    def select_symbol(self, symbol: str) -> bool: ...

    @abstractmethod
    def tick(self, symbol: str) -> Tick | None: ...

    @abstractmethod
    def bars(self, symbol: str, timeframe: Timeframe, count: int) -> list[Bar]: ...

    @abstractmethod
    def now(self) -> datetime:
        """Heure UTC de référence (horloge simulée pour le mock)."""

    # ------------------------------------------------------------------ positions / historique

    @abstractmethod
    def positions(self) -> list[Position]:
        """TOUTES les positions du compte (le filtrage ALLADIN se fait par magic/comment)."""

    @abstractmethod
    def orders(self) -> list[PendingOrder]: ...

    @abstractmethod
    def history_deals(self, since: datetime, until: datetime) -> list[Deal]: ...

    @abstractmethod
    def calc_margin(self, symbol: str, side_buy: bool, volume: float, price: float) -> float | None: ...

    # ------------------------------------------------------------------ exécution

    @abstractmethod
    def check_order(self, request: OrderRequest) -> OrderCheck:
        """Pré-validation broker (ne trade pas)."""

    @abstractmethod
    def _send(self, request: OrderRequest) -> OrderResult:
        """Envoi effectif. Jamais appelé directement : passer par send_order()."""

    def send_order(self, request: OrderRequest, approval: ApprovalToken | None) -> OrderResult:
        verify_token(request, approval)
        self.assert_demo()
        return self._send(request)
