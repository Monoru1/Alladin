"""Indicateurs techniques purs (listes de floats, sans dépendance externe)."""

from __future__ import annotations

from collections.abc import Sequence

from alladin.core.models import Bar


def sma(values: Sequence[float], n: int) -> float | None:
    if len(values) < n or n <= 0:
        return None
    return sum(values[-n:]) / n


def ema_series(values: Sequence[float], n: int) -> list[float]:
    if not values:
        return []
    k = 2 / (n + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def ema(values: Sequence[float], n: int) -> float | None:
    return ema_series(values, n)[-1] if len(values) >= n else None


def true_ranges(bars: Sequence[Bar]) -> list[float]:
    trs: list[float] = []
    for i, b in enumerate(bars):
        if i == 0:
            trs.append(b.high - b.low)
        else:
            pc = bars[i - 1].close
            trs.append(max(b.high - b.low, abs(b.high - pc), abs(b.low - pc)))
    return trs


def atr_series(bars: Sequence[Bar], n: int = 14) -> list[float]:
    """ATR de Wilder ; les n-1 premières valeurs sont des moyennes partielles."""
    trs = true_ranges(bars)
    if len(trs) < n:
        return []
    out: list[float] = []
    cur = sum(trs[:n]) / n
    out.append(cur)
    for tr in trs[n:]:
        cur = (cur * (n - 1) + tr) / n
        out.append(cur)
    return out


def atr(bars: Sequence[Bar], n: int = 14) -> float | None:
    s = atr_series(bars, n)
    return s[-1] if s else None


def rsi(closes: Sequence[float], n: int = 14) -> float | None:
    if len(closes) < n + 1:
        return None
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    avg_g, avg_l = gains / n, losses / n
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        avg_g = (avg_g * (n - 1) + max(d, 0)) / n
        avg_l = (avg_l * (n - 1) + max(-d, 0)) / n
    if avg_l == 0:
        return 100.0
    return 100 - 100 / (1 + avg_g / avg_l)


def efficiency_ratio(closes: Sequence[float], n: int = 20) -> float | None:
    """Kaufman : |déplacement net| / somme des déplacements. 1 = tendance pure, 0 = bruit/range."""
    if len(closes) < n + 1:
        return None
    window = closes[-(n + 1) :]
    net = abs(window[-1] - window[0])
    path = sum(abs(b - a) for a, b in zip(window, window[1:], strict=False))
    return net / path if path > 0 else 0.0


def donchian(bars: Sequence[Bar], n: int) -> tuple[float, float] | None:
    if len(bars) < n:
        return None
    w = bars[-n:]
    return max(b.high for b in w), min(b.low for b in w)


def percentile_rank(series: Sequence[float], value: float) -> float:
    if not series:
        return 0.5
    return sum(1 for v in series if v <= value) / len(series)


def stdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = sum(values) / len(values)
    return float((sum((v - m) ** 2 for v in values) / (len(values) - 1)) ** 0.5)
