"""MarketScanner : produit une shortlist de candidats. N'envoie JAMAIS d'ordre."""

from __future__ import annotations

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

    def scan(
        self, *, limit: int | None = None, cycle_id: str | None = None, max_trade_risk: float | None = None
    ) -> ScanReport:
        now = self.broker.now()
        uni = self.universe.discover()
        rejected: dict[str, list[str]] = {s: [r] for s, r in uni.excluded.items()}
        notes: list[str] = []
        candidates: list[ScanCandidate] = []
        analysed = 0
        archived = 0
        clock_suspect = 0

        for member in uni.members:
            sym = member.symbol
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
                if tick.bid <= 0 or tick.ask <= tick.bid:
                    rejected[sym] = [f"tick de mauvaise qualité (bid {tick.bid}, ask {tick.ask})"]
                    continue
                if spec.point <= 0 or spec.loss_tick_value <= 0 or spec.trade_tick_size <= 0:
                    rejected[sym] = [
                        "spécifications broker inexploitables (tick value/size indisponible) : sizing impossible"
                    ]
                    continue
                age = (now - tick.time).total_seconds()
                if age < -600:
                    clock_suspect += 1
                elif self.max_tick_age_s is not None and age > self.max_tick_age_s:
                    rejected[sym] = [f"tick périmé ({age / 60:.0f} min) : marché fermé ?"]
                    continue
                bars = {tf: self.broker.bars(sym, tf, self.bars_count) for tf in self.timeframes}
                if self.archive is not None:
                    archived += sum(self.archive.store(sym, tf, b, cycle_id) for tf, b in bars.items())
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
                    session=session_label(now),
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
        if clock_suspect:
            notes.append(
                f"{clock_suspect} tick(s) datés dans le futur : vérifier MT5_SERVER_UTC_OFFSET_HOURS (fraîcheur non contrôlée)"
            )
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
