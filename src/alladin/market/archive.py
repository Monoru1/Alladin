"""MarketDataArchive : barres réellement utilisées par les décisions, pour replay / backtest / contrefactuel.

- Clé primaire (symbole, timeframe, ts) : aucune duplication possible ; une barre clôturée est immuable
  (triggers anti UPDATE/DELETE en SQLite).
- Écriture incrémentale : seules les barres plus récentes que la dernière archivée sont insérées (le
  coût par cycle est donc quasi nul après le premier).
- `cycle_inputs` relie chaque cycle aux fenêtres de barres qu'il a vues (pour reconstruire ses entrées).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Column, Float, Integer, MetaData, String, Table, insert, select, text
from sqlalchemy.engine import Engine

from alladin.core.enums import Timeframe
from alladin.core.models import Bar

metadata = MetaData()

market_bars = Table(
    "market_bars",
    metadata,
    Column("symbol", String, primary_key=True),
    Column("timeframe", String, primary_key=True),
    Column("ts", Integer, primary_key=True),  # epoch UTC (secondes)
    Column("open", Float, nullable=False),
    Column("high", Float, nullable=False),
    Column("low", Float, nullable=False),
    Column("close", Float, nullable=False),
    Column("tick_volume", Float, nullable=False),
    Column("spread", Float, nullable=False),
)

cycle_inputs = Table(
    "cycle_inputs",
    metadata,
    Column("cycle_id", String, primary_key=True),
    Column("symbol", String, primary_key=True),
    Column("timeframe", String, primary_key=True),
    Column("n_bars", Integer, nullable=False),
    Column("first_ts", Integer, nullable=False),
    Column("last_ts", Integer, nullable=False),
)

_TRIGGERS = [
    "CREATE TRIGGER IF NOT EXISTS bars_no_update BEFORE UPDATE ON market_bars "
    "BEGIN SELECT RAISE(ABORT, 'archived bars are immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS bars_no_delete BEFORE DELETE ON market_bars "
    "BEGIN SELECT RAISE(ABORT, 'archived bars are immutable'); END",
]


class MarketDataArchive:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        metadata.create_all(engine)
        if engine.dialect.name == "sqlite":
            with engine.begin() as c:
                for ddl in _TRIGGERS:
                    c.execute(text(ddl))
        self._last: dict[tuple[str, str], int | None] = {}

    def _last_ts(self, symbol: str, tf: str) -> int | None:
        key = (symbol, tf)
        if key not in self._last:
            with self.engine.connect() as c:
                v = c.execute(
                    select(text("MAX(ts)"))
                    .select_from(market_bars)
                    .where((market_bars.c.symbol == symbol) & (market_bars.c.timeframe == tf))
                ).scalar_one()
            self._last[key] = int(v) if v is not None else None
        return self._last[key]

    def store(
        self, symbol: str, timeframe: Timeframe, bars: Sequence[Bar], cycle_id: str | None = None
    ) -> int:
        """Archive les barres nouvelles ; retourne le nombre de lignes ajoutées."""
        if not bars:
            return 0
        tf = timeframe.value
        last = self._last_ts(symbol, tf)
        fresh = [b for b in bars if last is None or int(b.time.timestamp()) > last]
        added = 0
        with self.engine.begin() as c:
            if fresh:
                rows: list[dict[str, Any]] = [
                    {
                        "symbol": symbol,
                        "timeframe": tf,
                        "ts": int(b.time.timestamp()),
                        "open": b.open,
                        "high": b.high,
                        "low": b.low,
                        "close": b.close,
                        "tick_volume": b.tick_volume,
                        "spread": b.spread,
                    }
                    for b in fresh
                ]
                stmt = insert(market_bars)
                if self.engine.dialect.name == "sqlite":
                    stmt = stmt.prefix_with("OR IGNORE")
                c.execute(stmt, rows)
                added = len(rows)
                self._last[(symbol, tf)] = max(r["ts"] for r in rows)
            if cycle_id:
                c.execute(
                    insert(cycle_inputs).prefix_with("OR IGNORE")
                    if self.engine.dialect.name == "sqlite"
                    else insert(cycle_inputs),
                    {
                        "cycle_id": cycle_id,
                        "symbol": symbol,
                        "timeframe": tf,
                        "n_bars": len(bars),
                        "first_ts": int(bars[0].time.timestamp()),
                        "last_ts": int(bars[-1].time.timestamp()),
                    },
                )
        return added

    def load(
        self,
        symbol: str,
        timeframe: Timeframe,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int | None = None,
    ) -> list[Bar]:
        q = select(market_bars).where(
            (market_bars.c.symbol == symbol) & (market_bars.c.timeframe == timeframe.value)
        )
        if since:
            q = q.where(market_bars.c.ts >= int(since.timestamp()))
        if until:
            q = q.where(market_bars.c.ts <= int(until.timestamp()))
        q = q.order_by(market_bars.c.ts)
        if limit:
            q = q.limit(limit)
        with self.engine.connect() as c:
            rows = c.execute(q).all()
        return [
            Bar(
                time=datetime.fromtimestamp(r.ts, UTC),
                open=r.open,
                high=r.high,
                low=r.low,
                close=r.close,
                tick_volume=r.tick_volume,
                spread=r.spread,
            )
            for r in rows
        ]

    def cycle_inputs(self, cycle_id: str) -> list[dict[str, Any]]:
        with self.engine.connect() as c:
            rows = c.execute(select(cycle_inputs).where(cycle_inputs.c.cycle_id == cycle_id)).all()
        return [dict(r._mapping) for r in rows]

    def stats(self) -> dict[str, Any]:
        with self.engine.connect() as c:
            n = c.execute(text("SELECT COUNT(*) FROM market_bars")).scalar_one()
            s = c.execute(text("SELECT COUNT(DISTINCT symbol) FROM market_bars")).scalar_one()
        return {"bars": int(n), "symbols": int(s)}
