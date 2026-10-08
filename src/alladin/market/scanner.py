"""MarketScanner : produit une shortlist de candidats. N'envoie JAMAIS d'ordre."""

from __future__ import annotations

import math
from datetime import datetime

from alladin.brokers.base import BrokerAdapter
from alladin.challenge.models import UniverseRules
from alladin.core.enums import MarketRegime, Side, Timeframe
from alladin.core.models import Bar
from alladin.market import indicators as ind
from alladin.market.archive import MarketDataArchive
from alladin.market.context import MarketContextProvider, NullContextProvider
from alladin.market.models import ScanCandidate, ScanReport
from alladin.market.regime import MIN_BARS, RegimeClassifier
from alladin.market.universe import MarketUniverse
from alladin.risk.sizing import loss_per_lot

DEFAULT_TIMEFRAMES = (Timeframe.M15, Timeframe.H1, Timeframe.H4, Timeframe.D1)
MAX_FUTURE_TICK_S = 5.0


def tick_quality_error(bid: float, ask: float, age_s: float, max_age_s: float | None) -> str | None:
    """Fail closed on invalid quotes or uncertain clock before analysing market data."""
    if not all(math.isfinite(v) for v in (bid, ask, age_s)):
        return "tick non fini ou horodatage invalide"
    if bid <= 0 or ask <= bid:
        return f"tick de mauvaise qualité (bid {bid}, ask {ask})"
    if age_s < -MAX_FUTURE_TICK_S:
        return f"tick dans le futur ({-age_s:.1f} s) : horloge broker incertaine"
    if max_age_s is not None and age_s > max_age_s:
        return f"tick périmé ({age_s / 60:.0f} min) : marché fermé ?"
    return None



def session_label(now: datetime) -> str:
    h = now.hour  # UTC
    tokyo, london, ny = 0 <= h < 8, 7 <= h < 16, 12 <= h < 21
    parts = [n for n, on in (("TOKYO", tokyo), ("LONDON", london), ("NEWYORK", ny)) if on]
    return "+".join(parts) or "OFF_HOURS"


def _tf_trend(bars: list[Bar]) -> int:
    closes = [b.close for b in bars]
    e20, e50 = ind.ema(closes, 20), ind.ema(closes, 50)
    if e20 is None or e50 is None:
        return 0
    if e20 > e50 and closes[-1] > e50:
        return 1
    if e20 < e50 and closes[-1] < e50:
        return -1
    return 0



# Nombre minimum de cycles entre deux rafraîchissements par timeframe
TF_CYCLE_INTERVAL: dict[str, int] = {
    "M1": 1,
    "M5": 1,
    "M15": 2,
    "M30": 3,
    "H1": 4,
    "H4": 12,
    "D1": 48,
    "W1": 240,
}


class TimeframeScheduler:
    """Limite la fréquence de fetch des barres par timeframe.

    Un timeframe rapide (M5) est rechargé à chaque cycle.
    Un timeframe lent (D1) est rechargé seulement tous les N cycles.
    Les barres en cache sont réutilisées entre les rechargements.

    Le cache est indexé par (symbol, tf) pour éviter les croisements entre symboles.
    """

    def __init__(self, timeframes: tuple[Timeframe, ...], intervals: dict[str, int] | None = None) -> None:
        self._intervals = intervals or TF_CYCLE_INTERVAL
        self._tfs = timeframes
        self._last_fetch: dict[tuple[str, str], int] = {}  # (symbol, tf.value) -> dernier cycle_number
        self._cache: dict[tuple[str, str], list[Bar]] = {}  # (symbol, tf.value) -> barres

    def due(self, symbol: str, tf: Timeframe, cycle_number: int) -> bool:
        interval = self._intervals.get(tf.value, 1)
        last = self._last_fetch.get((symbol, tf.value), -999)
        return (cycle_number - last) >= interval

    def mark_fetched(self, symbol: str, tf: Timeframe, cycle_number: int, bars: list[Bar]) -> None:
        self._last_fetch[(symbol, tf.value)] = cycle_number
        self._cache[(symbol, tf.value)] = bars

    def cached(self, symbol: str, tf: Timeframe) -> list[Bar]:
        return self._cache.get((symbol, tf.value), [])


class MarketScanner:
    def __init__(
        self,
        broker: BrokerAdapter,
        universe: MarketUniverse,
        rules: UniverseRules,
        *,
        classifier: RegimeClassifier | None = None,
        context: MarketContextProvider | None = None,
        primary: Timeframe = Timeframe.H1,
        timeframes: tuple[Timeframe, ...] = DEFAULT_TIMEFRAMES,
        bars_count: int = 300,
        max_tick_age_s: float | None = 1800,
        archive: MarketDataArchive | None = None,
    ) -> None:
        self.broker = broker
        self.universe = universe
        self.rules = rules
        self.classifier = classifier or RegimeClassifier()
        self.context = context or NullContextProvider()
        self.primary = primary
        self.timeframes = tuple(dict.fromkeys((primary, *timeframes)))
        self.bars_count = bars_count
        self.max_tick_age_s = max_tick_age_s
        self.archive = archive
        self._scheduler = TimeframeScheduler(self.timeframes)
        self._cycle_number = 0

    def scan(
        self, *, limit: int | None = None, cycle_id: str | None = None, max_trade_risk: float | None = None
    ) -> ScanReport:
        self._cycle_number += 1
        now = self.broker.now()
        uni = self.universe.discover()
        rejected: dict[str, list[str]] = {s: [r] for s, r in uni.excluded.items()}
        notes: list[str] = []
        candidates: list[ScanCandidate] = []
        analysed = 0
        archived = 0
        last_market_update_at: datetime | None = None

        for member in uni.members:
            sym = member.symbol
            if not self.rules.sessions.allows(now, is_24_7=self.broker.capabilities().is_24_7):
                rejected[sym] = ["hors session configurée ou capacité 24/7 absente"]
                continue
            try:
                if not self.broker.select_symbol(sym):
                    rejected[sym] = ["symbole non sélectionnable"]
                    continue
                spec = self.broker.symbol_spec(sym) or member
                spec.category = member.category
                tick = self.broker.tick(sym)
                if tick is None:
                    rejected[sym] = ["aucun tick"]
                    continue
                if last_market_update_at is None or tick.time > last_market_update_at:
                    last_market_update_at = tick.time
                if spec.point <= 0 or spec.loss_tick_value <= 0 or spec.trade_tick_size <= 0:
                    rejected[sym] = [
                        "spécifications broker inexploitables (tick value/size indisponible) : sizing impossible"
                    ]
                    continue
                age = (now - tick.time).total_seconds()
                quality_error = tick_quality_error(tick.bid, tick.ask, age, self.max_tick_age_s)
                if quality_error:
                    rejected[sym] = [quality_error]
                    continue
                bars = {}
                for tf in self.timeframes:
                    if self._scheduler.due(sym, tf, self._cycle_number):
                        fetched = self.broker.bars(sym, tf, self.bars_count)
                        self._scheduler.mark_fetched(sym, tf, self._cycle_number, fetched)
                        bars[tf] = fetched
                    else:
                        cached = self._scheduler.cached(sym, tf)
                        bars[tf] = cached if cached else self.broker.bars(sym, tf, self.bars_count)
                if self.archive is not None:
                    observed_at = self.broker.now()
                    provenance = self.broker.capabilities().provenance_tag or self.broker.capabilities().name
                    for tf, series in bars.items():
                        bars[tf] = [
                            bar if bar.provenance else bar.model_copy(update={"provenance": provenance})
                            for bar in series
                        ]
                        archived += self.archive.store(sym, tf, bars[tf], cycle_id, decision_at=observed_at)
                    if cycle_id and any(bars.values()):
                        bars.update(self.archive.load_cycle(cycle_id, symbol=sym)[sym])
                prim = bars[self.primary]
                if len(prim) < MIN_BARS:
                    rejected[sym] = [f"historique insuffisant ({len(prim)} barres {self.primary.value})"]
                    continue
                analysed += 1
                macro = self.context.get_context((spec.currency_base, spec.currency_profit), now)
                assess = self.classifier.classify(prim, macro)
                atr = assess.metrics.get("atr") or ind.atr(prim, 14) or 0.0
                spread_price = tick.spread
                ratio = spread_price / atr if atr > 0 else 9.9
                reasons: list[str] = []
                if ratio > self.rules.max_spread_atr_ratio:
                    reasons.append(f"spread/ATR {ratio:.2f} > {self.rules.max_spread_atr_ratio}")
                if max_trade_risk is not None and atr > 0:
                    # contrainte de sizing : le plus petit lot doit tenir dans le plafond pour un SL de 1,5 ATR
                    min_risk = loss_per_lot(spec, tick.ask, tick.ask - 1.5 * atr) * spec.volume_min
                    if min_risk > max_trade_risk:
                        reasons.append(
                            f"sizing : volume minimum {spec.volume_min:g} risquerait {min_risk:.2f} > plafond {max_trade_risk:.2f} (SL 1,5 ATR)"
                        )
                if assess.regime in (MarketRegime.UNKNOWN, MarketRegime.NEWS_EVENT):
                    reasons.append(f"régime {assess.regime.value} : pas de setup exploitable")
                if reasons:
                    rejected[sym] = reasons
                    continue
                tf_trend = {tf.value: _tf_trend(b) for tf, b in bars.items()}
                cand = ScanCandidate(
                    symbol=sym,
                    category=member.category,
                    regime=assess.regime,
                    regime_confidence=assess.confidence,
                    regime_reasons=assess.reasons,
                    score=0.0,
                    session="24_7" if self.broker.capabilities().is_24_7 else session_label(now),
                    spread_points=tick.spread / spec.point if spec.point else 0.0,
                    spread_atr_ratio=ratio,
                    metrics=assess.metrics,
                    tf_trend=tf_trend,
                    spec=spec,
                    tick=tick,
                    bars=bars,
                )
                cand.bias = self._bias(cand)
                cand.score = self._score(cand)
                candidates.append(cand)
            except Exception as exc:  # un symbole défaillant ne doit pas faire tomber le scan
                rejected[sym] = [f"erreur d'analyse : {exc}"]

        candidates.sort(key=lambda c: c.score, reverse=True)
        size = limit or self.rules.shortlist_size
        regimes: dict[str, int] = {}
        for c in candidates:
            regimes[c.regime.value] = regimes.get(c.regime.value, 0) + 1
        return ScanReport(
            scanned_at=now,
            universe_size=len(uni.members),
            analysed=analysed,
            candidates=candidates[:size],
            rejected=rejected,
            regime_counts=regimes,
            notes=notes,
            cycle_id=cycle_id,
            archived_bars=archived,
            last_market_update_at=last_market_update_at,
        )

    @staticmethod
    def _bias(c: ScanCandidate) -> Side | None:
        m = c.metrics
        if not m:
            return None
        if c.regime in (MarketRegime.TREND, MarketRegime.BREAKOUT):
            if m["momentum_atr"] > 0.3:
                return Side.BUY
            if m["momentum_atr"] < -0.3:
                return Side.SELL
        elif c.regime is MarketRegime.REVERSAL_CONTEXT:
            return Side.SELL if m["dist_ema50_atr"] > 0 else Side.BUY
        elif c.regime is MarketRegime.RANGE:
            width = m["donchian_high"] - m["donchian_low"]
            pos = (m["close"] - m["donchian_low"]) / width if width > 0 else 0.5
            if pos > 0.8:
                return Side.SELL
            if pos < 0.2:
                return Side.BUY
        return None

    def _score(self, c: ScanCandidate) -> float:
        m = c.metrics
        clarity = {
            MarketRegime.TREND: m["er20"],
            MarketRegime.BREAKOUT: min(1.0, m["tr_last_atr"] / 2.5),
            MarketRegime.RANGE: 1 - m["er20"],
            MarketRegime.REVERSAL_CONTEXT: min(1.0, abs(m["dist_ema50_atr"]) / 3),
        }.get(c.regime, 0.1)
        momentum = min(1.0, abs(m["momentum_atr"]) / 3)
        votes = [v for v in c.tf_trend.values() if v != 0]
        agreement = abs(sum(votes)) / len(c.tf_trend) if c.tf_trend else 0.0
        cost = max(0.0, 1 - c.spread_atr_ratio / max(self.rules.max_spread_atr_ratio, 1e-9))
        return round(0.35 * clarity + 0.25 * momentum + 0.20 * agreement + 0.20 * cost, 4)
