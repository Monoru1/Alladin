"""MarketUniverse : découverte DYNAMIQUE des instruments via le broker (aucune liste statique)."""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel

from alladin.brokers.base import BrokerAdapter
from alladin.challenge.models import UniverseRules
from alladin.core.enums import AssetCategory
from alladin.core.models import InstrumentSpec

_G8 = {"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD"}
_ISO_OTHER = {
    "TRY", "ZAR", "MXN", "PLN", "HUF", "CZK", "SEK", "NOK", "DKK", "SGD", "HKD", "CNH", "CNY",
    "THB", "ILS", "RUB", "BRL", "INR", "KRW", "TWD", "CLP", "COP", "RON", "ARS", "AED", "SAR",
}  # fmt: skip
_METALS = {"XAU", "XAG", "XPT", "XPD"}
_MAJORS_QUOTE = "USD"


def classify_symbol(spec: InstrumentSpec) -> AssetCategory:
    """Classe un instrument d'après ses devises broker (et non d'après son nom) : robuste aux suffixes."""
    if spec.category in (AssetCategory.CRYPTO_SPOT, AssetCategory.CRYPTO_PERP):
        return spec.category  # explicit adapter metadata, never infer spot/perp from a name
    base, quote = spec.currency_base.upper(), spec.currency_profit.upper()
    if base in _METALS:
        return AssetCategory.METAL
    # Actions/indices/futures CFD ont souvent base == profit == USD : ce ne sont pas des paires de devises.
    if base == quote or spec.is_forex_like is False:
        return AssetCategory.OTHER
    known = _G8 | _ISO_OTHER
    if base not in known or quote not in known:
        return AssetCategory.OTHER
    if base not in _G8 or quote not in _G8:
        return AssetCategory.FOREX_EXOTIC
    if "USD" in (base, quote):
        return AssetCategory.FOREX_MAJOR
    if "JPY" in (base, quote):
        return AssetCategory.FOREX_JPY
    return AssetCategory.FOREX_MINOR


class UniverseReport(BaseModel):
    members: list[InstrumentSpec]
    excluded: dict[str, str]
    total_discovered: int
    by_category: dict[str, int]


class MarketUniverse:
    def __init__(self, broker: BrokerAdapter, rules: UniverseRules) -> None:
        self.broker = broker
        self.rules = rules

    def discover(self) -> UniverseReport:
        specs = self.broker.list_symbols()
        members: list[InstrumentSpec] = []
        excluded: dict[str, str] = {}
        forced = set(self.rules.include_symbols)
        for spec in specs:
            spec.category = classify_symbol(spec)
            reason = self._exclusion_reason(spec, forced)
            if reason:
                excluded[spec.symbol] = reason
            else:
                members.append(spec)
        counts = Counter(m.category.value for m in members)
        return UniverseReport(
            members=members,
            excluded=excluded,
            total_discovered=len(specs),
            by_category=dict(sorted(counts.items())),
        )

    def _exclusion_reason(self, spec: InstrumentSpec, forced: set[str]) -> str | None:
        if (spec.category in (AssetCategory.CRYPTO_SPOT, AssetCategory.CRYPTO_PERP)
                and spec.category not in self.broker.capabilities().supported_asset_categories):
            return "catégorie crypto non déclarée par les capacités broker"
        if spec.symbol in self.rules.exclude_symbols:
            return "exclu par le profil"
        if not spec.is_tradable:
            return f"non négociable ({spec.trade_mode})"
        if (
            spec.trade_contract_size <= 0
            or spec.volume_step <= 0
            or spec.trade_tick_size <= 0
            or spec.volume_min <= 0
        ):
            return "spécification broker incomplète"
        if spec.symbol not in forced and spec.category not in self.rules.allowed_categories:
            return f"catégorie {spec.category.value} non autorisée par le profil"
        return None
