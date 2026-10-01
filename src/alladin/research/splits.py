"""Dataset splits chronologiques pour backtesting : TRAIN / VALIDATION / OOS / DEMO_FORWARD.

Proprietes :
- Splits strictement chronologiques (JAMAIS de random shuffle).
- Purge zone entre TRAIN et VALIDATION pour eviter le label leakage.
- Embargo optionnel apres chaque split boundary.
- OOS ne participe JAMAIS a l'optimisation ou au choix de parametres.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from alladin.core.models import Bar

SplitName = Literal["TRAIN", "VALIDATION", "OUT_OF_SAMPLE", "DEMO"]


@dataclass(frozen=True)
class SplitRange:
    """Un segment temporel nomme."""

    name: SplitName
    start: datetime
    end: datetime
    bars_count: int

    @property
    def duration(self) -> timedelta:
        return self.end - self.start


@dataclass(frozen=True)
class DatasetSplitConfig:
    """Configuration des proportions et purge/embargo."""

    train_pct: float = 0.50
    validation_pct: float = 0.20
    oos_pct: float = 0.20
    demo_pct: float = 0.10
    purge_bars: int = 10  # barres supprimees entre segments
    embargo_bars: int = 5  # barres ignorees au debut de chaque segment post-purge
    label_horizon_bars: int = 0  # horizon maximal d'un label/trade pour anti-leakage
    expected_interval: timedelta | None = None
    minimum_split_bars: int = 5

    def __post_init__(self) -> None:
        total = self.train_pct + self.validation_pct + self.oos_pct + self.demo_pct
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"split percentages must sum to 1.0, got {total:.2f}")
        if any(p <= 0 for p in (self.train_pct, self.validation_pct, self.oos_pct, self.demo_pct)):
            raise ValueError("every split percentage must be positive")
        if self.purge_bars < 0 or self.embargo_bars < 0:
            raise ValueError("purge and embargo must be non-negative")
        if self.purge_bars < self.label_horizon_bars:
            raise ValueError("purge_bars must cover label_horizon_bars")
        if self.minimum_split_bars < 1:
            raise ValueError("minimum_split_bars must be positive")


def split_bars(
    bars: list[Bar],
    config: DatasetSplitConfig | None = None,
) -> dict[SplitName, list[Bar]]:
    """Decoupe une serie de barres en segments chronologiques avec purge/embargo.

    Retourne un dict {split_name: bars_for_split}.
    Les barres dans la purge/embargo zone sont exclues de tous les segments.
    """
    cfg = config or DatasetSplitConfig()
    n = len(bars)
    if n < 50:
        raise ValueError(f"need at least 50 bars for splitting, got {n}")
    if any(a.time >= b.time for a, b in zip(bars[:-1], bars[1:], strict=True)):
        raise ValueError("bars must be strictly chronological without duplicates")
    if cfg.expected_interval is not None and any(
        b.time - a.time != cfg.expected_interval
        for a, b in zip(bars[:-1], bars[1:], strict=True)
    ):
        raise ValueError("bar gap does not match expected_interval")

    # Calcul des boundaries : on reserve d'abord le total purge/embargo
    n_gaps = 3  # between TRAIN/VAL, VAL/OOS, OOS/DEMO
    gap_size = cfg.purge_bars + cfg.embargo_bars
    usable = n - n_gaps * gap_size
    if usable < 20:
        raise ValueError(f"not enough bars ({n}) after purge/embargo gaps")

    splits: list[tuple[SplitName, float]] = [
        ("TRAIN", cfg.train_pct),
        ("VALIDATION", cfg.validation_pct),
        ("OUT_OF_SAMPLE", cfg.oos_pct),
        ("DEMO", cfg.demo_pct),
    ]

    boundaries: list[tuple[SplitName, int, int]] = []
    cursor = 0
    for i, (name, pct) in enumerate(splits):
        raw_count = max(cfg.minimum_split_bars, int(usable * pct))
        start = cursor
        end = min(start + raw_count, n)
        boundaries.append((name, start, end))
        # Gap after this segment (purge + embargo) except last
        cursor = end + gap_size if i < len(splits) - 1 else end

    result: dict[SplitName, list[Bar]] = {}
    for name, start, end in boundaries:
        start = min(start, n)
        end = min(end, n)
        result[name] = bars[start:end]
        if len(result[name]) < cfg.minimum_split_bars:
            raise ValueError(f"split {name} too short")

    return result


def split_ranges(
    bars: list[Bar],
    config: DatasetSplitConfig | None = None,
) -> list[SplitRange]:
    """Retourne les SplitRange avec timestamps pour chaque segment."""
    segments = split_bars(bars, config)
    ranges: list[SplitRange] = []
    ordered: list[SplitName] = ["TRAIN", "VALIDATION", "OUT_OF_SAMPLE", "DEMO"]
    for split_name in ordered:
        segment = segments.get(split_name, [])
        if segment:
            ranges.append(SplitRange(
                name=split_name,
                start=segment[0].time,
                end=segment[-1].time,
                bars_count=len(segment),
            ))
    return ranges
