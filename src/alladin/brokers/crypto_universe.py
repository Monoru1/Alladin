"""Pipeline d'éligibilité de l'univers crypto Binance Spot.

L'univers est découvert dynamiquement via GET /api/v3/exchangeInfo.
Aucune liste de symboles hardcodée.

Architecture :
    BinanceRestClient.exchange_info()
        → CryptoUniverseBuilder.build()
            → EligibilityFilter (status, filtres, blacklist, quote asset)
                → List[EligibleSymbol]

Une crypto non éligible au trading reste observable.
Upside non plafonné : aucun plafond de gain n'est introduit ici.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from alladin.brokers.binance import BinanceExchangeInfo, BinanceSymbolInfo

# ---------------------------------------------------------------------------
# Modèles
# ---------------------------------------------------------------------------

_DEFAULT_BLACKLIST: frozenset[str] = frozenset()
_DEFAULT_QUOTE_ASSETS: frozenset[str] = frozenset({"USDT", "USDC"})


@dataclass(frozen=True)
class EligibleSymbol:
    """Symbole qualifié pour l'observation et le trading Jafar."""

    symbol: str
    base_asset: str
    quote_asset: str
    is_trading: bool                   # True si status == TRADING
    has_required_filters: bool         # True si filtres minimaux présents
    trade_eligible: bool               # True si éligible trading (tout passe)
    observe_eligible: bool             # True si éligible observation (trading non requis)
    ineligibility_reasons: tuple[str, ...]
    lot_size_min_qty: float | None = None
    lot_size_step: float | None = None
    min_notional: float | None = None
    order_types: tuple[str, ...] = ()

    @property
    def supports_market_order(self) -> bool:
        return "MARKET" in self.order_types

    @property
    def supports_limit_order(self) -> bool:
        return "LIMIT" in self.order_types


@dataclass
class UniverseReport:
    """Rapport complet de la découverte de l'univers crypto."""

    total_discovered: int
    trade_eligible: list[EligibleSymbol]
    observe_only: list[EligibleSymbol]  # inéligible trading mais observable
    ineligible: list[EligibleSymbol]    # inéligible même pour l'observation
    by_quote_asset: dict[str, int] = field(default_factory=dict)

    @property
    def n_trade_eligible(self) -> int:
        return len(self.trade_eligible)

    @property
    def n_observable(self) -> int:
        return len(self.trade_eligible) + len(self.observe_only)


# ---------------------------------------------------------------------------
# Filtres d'éligibilité
# ---------------------------------------------------------------------------


def _extract_lot_size(symbol_info: BinanceSymbolInfo) -> tuple[float | None, float | None]:
    """Extrait min_qty et step_size du filtre LOT_SIZE."""
    f = symbol_info.get_filter("LOT_SIZE")
    if f is None:
        return None, None
    raw = f.model_extra or {}
    try:
        return float(raw.get("minQty", 0)), float(raw.get("stepSize", 0))
    except (TypeError, ValueError):
        return None, None


def _extract_min_notional(symbol_info: BinanceSymbolInfo) -> float | None:
    """Extrait la valeur minimale de notional (MIN_NOTIONAL ou NOTIONAL)."""
    for filter_type in ("MIN_NOTIONAL", "NOTIONAL"):
        f = symbol_info.get_filter(filter_type)
        if f is None:
            continue
        raw = f.model_extra or {}
        key = "minNotional" if filter_type == "MIN_NOTIONAL" else "minNotional"
        val = raw.get(key) or raw.get("notional")
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return None


def assess_symbol(
    symbol_info: BinanceSymbolInfo,
    *,
    quote_assets: frozenset[str] = _DEFAULT_QUOTE_ASSETS,
    blacklist: frozenset[str] = _DEFAULT_BLACKLIST,
    require_market_order: bool = False,
) -> EligibleSymbol:
    """Évalue l'éligibilité d'un symbole. Retourne toujours un EligibleSymbol."""
    reasons: list[str] = []

    # Filtre quote asset
    if symbol_info.quote_asset.upper() not in {qa.upper() for qa in quote_assets}:
        reasons.append(f"QUOTE_ASSET_NOT_ACCEPTED:{symbol_info.quote_asset}")

    # Blacklist
    if symbol_info.symbol.upper() in {s.upper() for s in blacklist}:
        reasons.append("BLACKLISTED")

    # Spot trading autorisé
    if not symbol_info.is_spot_trading_allowed:
        reasons.append("SPOT_NOT_ALLOWED")

    # Status TRADING
    if not symbol_info.is_trading:
        reasons.append(f"STATUS_NOT_TRADING:{symbol_info.status}")

    # Filtres minimaux
    lot_min, lot_step = _extract_lot_size(symbol_info)
    min_notional = _extract_min_notional(symbol_info)

    has_lot_size = lot_min is not None and lot_step is not None
    has_notional = min_notional is not None
    has_required_filters = has_lot_size and has_notional

    if not has_required_filters:
        missing = []
        if not has_lot_size:
            missing.append("LOT_SIZE")
        if not has_notional:
            missing.append("MIN_NOTIONAL")
        reasons.append(f"MISSING_FILTERS:{','.join(missing)}")

    # MARKET order si requis
    if require_market_order and "MARKET" not in symbol_info.order_types:
        reasons.append("MARKET_ORDER_NOT_SUPPORTED")

    trade_eligible = len(reasons) == 0
    # Observable si uniquement problème de status ou filtres non critiques
    # (les symboles blacklistés ou sans spot ne sont pas observables)
    hard_reasons = {r for r in reasons if r.startswith(("BLACKLISTED", "SPOT_NOT_ALLOWED", "QUOTE_ASSET"))}
    observe_eligible = len(hard_reasons) == 0

    return EligibleSymbol(
        symbol=symbol_info.symbol,
        base_asset=symbol_info.base_asset,
        quote_asset=symbol_info.quote_asset,
        is_trading=symbol_info.is_trading,
        has_required_filters=has_required_filters,
        trade_eligible=trade_eligible,
        observe_eligible=observe_eligible,
        ineligibility_reasons=tuple(reasons),
        lot_size_min_qty=lot_min,
        lot_size_step=lot_step,
        min_notional=min_notional,
        order_types=symbol_info.order_types,
    )


# ---------------------------------------------------------------------------
# Builder principal
# ---------------------------------------------------------------------------


class CryptoUniverseBuilder:
    """
    Construit l'univers crypto dynamique à partir de l'exchange info Binance.

    Aucune liste de symboles hardcodée.
    Les symboles inéligibles au trading peuvent rester observables.
    """

    def __init__(
        self,
        quote_assets: frozenset[str] | None = None,
        blacklist: frozenset[str] | None = None,
        require_market_order: bool = False,
    ) -> None:
        self.quote_assets = quote_assets or _DEFAULT_QUOTE_ASSETS
        self.blacklist = blacklist or _DEFAULT_BLACKLIST
        self.require_market_order = require_market_order

    def build(self, exchange_info: BinanceExchangeInfo) -> UniverseReport:
        """Construit le rapport d'univers à partir d'un BinanceExchangeInfo."""
        trade_eligible: list[EligibleSymbol] = []
        observe_only: list[EligibleSymbol] = []
        ineligible: list[EligibleSymbol] = []
        by_quote: dict[str, int] = {}

        for sym in exchange_info.symbols:
            assessed = assess_symbol(
                sym,
                quote_assets=self.quote_assets,
                blacklist=self.blacklist,
                require_market_order=self.require_market_order,
            )
            # Compte par quote asset accepté uniquement
            if sym.quote_asset.upper() in {qa.upper() for qa in self.quote_assets}:
                by_quote[sym.quote_asset.upper()] = by_quote.get(sym.quote_asset.upper(), 0) + 1

            if assessed.trade_eligible:
                trade_eligible.append(assessed)
            elif assessed.observe_eligible:
                observe_only.append(assessed)
            else:
                ineligible.append(assessed)

        return UniverseReport(
            total_discovered=len(exchange_info.symbols),
            trade_eligible=trade_eligible,
            observe_only=observe_only,
            ineligible=ineligible,
            by_quote_asset=by_quote,
        )
