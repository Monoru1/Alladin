"""Corrélations entre instruments (structure + calcul de Pearson sur rendements)."""

from __future__ import annotations

import math
from collections.abc import Sequence


def log_returns(closes: Sequence[float]) -> list[float]:
    return [math.log(b / a) for a, b in zip(closes, closes[1:], strict=False) if a > 0 and b > 0]


def pearson(a: Sequence[float], b: Sequence[float]) -> float | None:
    n = min(len(a), len(b))
    if n < 10:
        return None
    a, b = a[-n:], b[-n:]
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return None
    return cov / math.sqrt(va * vb)


class CorrelationMatrix:
    """Matrice symétrique de corrélations ; absence de valeur => None (inconnu)."""

    def __init__(self) -> None:
        self._m: dict[tuple[str, str], float] = {}

    def set(self, a: str, b: str, value: float) -> None:
        self._m[tuple(sorted((a, b)))] = value  # type: ignore[index]

    def get(self, a: str, b: str) -> float | None:
        if a == b:
            return 1.0
        return self._m.get(tuple(sorted((a, b))))  # type: ignore[arg-type]

    @classmethod
    def from_closes(cls, closes: dict[str, Sequence[float]]) -> CorrelationMatrix:
        cm = cls()
        rets = {s: log_returns(c) for s, c in closes.items()}
        syms = sorted(rets)
        for i, a in enumerate(syms):
            for b in syms[i + 1 :]:
                p = pearson(rets[a], rets[b])
                if p is not None:
                    cm.set(a, b, p)
        return cm
