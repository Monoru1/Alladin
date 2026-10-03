"""Archive immuable des barres et des fenêtres exactes vues par chaque cycle."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Column, Float, Integer, MetaData, String, Table, insert, select, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from alladin.core.enums import Timeframe
from alladin.core.models import Bar
from alladin.core.workspace import WorkspaceId

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
    Column("close_time", String),
    Column("is_closed", Integer),
    Column("available_at", String),
    Column("provenance", String),
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
    Column("fingerprint", String),
    Column("decision_at", String),
)

cycle_input_bars = Table(
    "cycle_input_bars",
    metadata,
    Column("cycle_id", String, primary_key=True),
    Column("symbol", String, primary_key=True),
    Column("timeframe", String, primary_key=True),
    Column("ts", Integer, primary_key=True),
)

for _table in metadata.tables.values():
    _table.append_column(Column("workspace", String, nullable=False, default="ALLADIN", primary_key=True))

_TRIGGERS = [
    "CREATE TRIGGER IF NOT EXISTS bars_no_update BEFORE UPDATE ON market_bars "
    "BEGIN SELECT RAISE(ABORT, 'archived bars are immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS bars_no_delete BEFORE DELETE ON market_bars "
    "BEGIN SELECT RAISE(ABORT, 'archived bars are immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS cycle_inputs_no_update BEFORE UPDATE ON cycle_inputs "
    "BEGIN SELECT RAISE(ABORT, 'archived cycle inputs are immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS cycle_inputs_no_delete BEFORE DELETE ON cycle_inputs "
    "BEGIN SELECT RAISE(ABORT, 'archived cycle inputs are immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS cycle_input_bars_no_update BEFORE UPDATE ON cycle_input_bars "
    "BEGIN SELECT RAISE(ABORT, 'archived cycle bars are immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS cycle_input_bars_no_delete BEFORE DELETE ON cycle_input_bars "
    "BEGIN SELECT RAISE(ABORT, 'archived cycle bars are immutable'); END",
]


class ArchiveConflictError(ValueError):
    """Une même identité de barre ou de fenêtre possède un contenu contradictoire."""


class ArchiveIncompleteError(ValueError):
    """Une fenêtre historique ne peut plus être reconstruite exactement."""


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime sans fuseau horaire dans l'archive")
    return value.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    return _utc(value).isoformat() if value is not None else None


def _bar_row(symbol: str, tf: str, bar: Bar) -> dict[str, Any]:
    ts = _utc(bar.time)
    if ts.microsecond:
        raise ValueError("timestamp de barre sous la seconde non pris en charge")
    return {
        "symbol": symbol, "timeframe": tf, "ts": int(ts.timestamp()),
        "open": float(bar.open), "high": float(bar.high), "low": float(bar.low), "close": float(bar.close),
        "tick_volume": float(bar.tick_volume), "spread": float(bar.spread),
        "close_time": _iso(bar.close_time),
        "is_closed": None if bar.is_closed is None else int(bar.is_closed),
        "available_at": _iso(bar.available_at), "provenance": bar.provenance,
    }


def _bar_from_row(row: Any) -> Bar:
    return Bar(
        time=datetime.fromtimestamp(row.ts, UTC), open=row.open, high=row.high,
        low=row.low, close=row.close, tick_volume=row.tick_volume, spread=row.spread,
        close_time=datetime.fromisoformat(row.close_time) if row.close_time else None,
        is_closed=bool(row.is_closed) if row.is_closed is not None else None,
        available_at=datetime.fromisoformat(row.available_at) if row.available_at else None,
        provenance=row.provenance,
    )


def _available_at(bar: Bar, timeframe: Timeframe) -> datetime:
    """Availability requires proof of observation and a closed market period."""
    close = _utc(bar.close_time) if bar.close_time else _utc(bar.time) + timedelta(minutes=timeframe.minutes)
    if bar.is_closed is False:
        raise ValueError("barre non clôturée dans une fenêtre de décision")
    if bar.available_at is None:
        raise ArchiveIncompleteError("date de disponibilité inconnue")
    return max(_utc(bar.available_at), close)


def _fingerprint(rows: Sequence[dict[str, Any]]) -> str:
    canonical = [{k: v for k, v in row.items() if k != "workspace"} for row in rows]
    body = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class MarketDataArchive:
    def __init__(self, engine: Engine, *, read_only: bool = False, workspace: WorkspaceId = WorkspaceId.ALLADIN) -> None:
        self.engine = engine
        self.workspace = WorkspaceId(workspace)
        if not read_only:
            metadata.create_all(engine)
        if not read_only and engine.dialect.name == "sqlite":
            with engine.begin() as c:
                c.exec_driver_sql("BEGIN IMMEDIATE")
                self._migrate(c)
                for table in metadata.tables.values():
                    columns = {r[1] for r in c.execute(text(f"PRAGMA table_info({table.name})"))}
                    if "workspace" in columns:
                        continue
                    legacy = f"{table.name}_legacy_workspace"
                    c.execute(text(f"ALTER TABLE {table.name} RENAME TO {legacy}"))
                    table.create(c)
                    names = list(table.c.keys())
                    expressions = [name if name in columns else "'ALLADIN'" for name in names]
                    c.execute(text(f"INSERT INTO {table.name} ({','.join(names)}) SELECT {','.join(expressions)} FROM {legacy}"))
                    c.execute(text(f"DROP TABLE {legacy}"))
                for ddl in _TRIGGERS:
                    c.execute(text(ddl))
        self._last: dict[tuple[str, str], int | None] = {}

    @staticmethod
    def _migrate(c: Connection) -> None:
        wanted = {
            "market_bars": {"close_time": "VARCHAR", "is_closed": "INTEGER", "available_at": "VARCHAR", "provenance": "VARCHAR"},
            "cycle_inputs": {"fingerprint": "VARCHAR", "decision_at": "VARCHAR"},
        }
        for table, columns in wanted.items():
            existing = {r[1] for r in c.execute(text(f"PRAGMA table_info({table})"))}
            for column, dtype in columns.items():
                if column not in existing:
                    c.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {dtype}"))

    def _last_ts(self, symbol: str, tf: str) -> int | None:
        key = (symbol, tf)
        if key not in self._last:
            with self.engine.connect() as c:
                v = c.execute(
                    select(market_bars.c.ts).where(market_bars.c.workspace == self.workspace.value)
                    .where((market_bars.c.symbol == symbol) & (market_bars.c.timeframe == tf))
                    .order_by(market_bars.c.ts.desc()).limit(1)
                ).scalar_one_or_none()
            self._last[key] = v
        return self._last[key]

    def store(
        self, symbol: str, timeframe: Timeframe, bars: Sequence[Bar], cycle_id: str | None = None,
        *, decision_at: datetime | None = None,
    ) -> int:
        """Archive atomiquement les barres et la fenêtre du cycle; renvoie les insertions réelles."""
        if cycle_id is not None and decision_at is None:
            raise ValueError("un cycle archivé exige un cutoff de décision explicite")
        if not bars:
            if cycle_id is not None:
                key = {"workspace": self.workspace.value, "cycle_id": cycle_id, "symbol": symbol, "timeframe": timeframe.value}
                window = {**key, "n_bars": 0, "first_ts": 0, "last_ts": 0,
                          "fingerprint": _fingerprint([]), "decision_at": _iso(decision_at)}
                with self.engine.begin() as c:
                    prior = c.execute(select(cycle_inputs).filter_by(**key)).first()
                    if prior is None:
                        c.execute(insert(cycle_inputs).values(**window))
                    elif dict(prior._mapping) != window:
                        raise ArchiveConflictError(f"fenêtre de cycle contradictoire : {cycle_id} {symbol} {timeframe.value}")
            return 0
        tf = timeframe.value
        by_ts: dict[int, dict[str, Any]] = {}
        for bar in bars:
            row = {**_bar_row(symbol, tf, bar), "workspace": self.workspace.value}
            ts = row["ts"]
            if ts in by_ts and row != by_ts[ts]:
                raise ArchiveConflictError(f"barre contradictoire dans le lot : {symbol} {tf} {ts}")
            by_ts[ts] = row
            if decision_at is not None:
                close = _utc(bar.close_time) if bar.close_time else _utc(bar.time) + timedelta(minutes=timeframe.minutes)
                if bar.is_closed is False or close > _utc(decision_at):
                    raise ValueError(f"barre non clôturée à la décision : {symbol} {tf} {ts}")
                if bar.available_at is not None and _available_at(bar, timeframe) > _utc(decision_at):
                    raise ValueError(f"barre indisponible à la décision : {symbol} {tf} {ts}")
        ordered = [by_ts[ts] for ts in sorted(by_ts)]
        with self.engine.begin() as c:
            existing = {
                row.ts: dict(row._mapping)
                for row in c.execute(
                    select(market_bars).where(market_bars.c.workspace == self.workspace.value).where(
                        (market_bars.c.symbol == symbol)
                        & (market_bars.c.timeframe == tf)
                        & market_bars.c.ts.in_(by_ts)
                    )
                )
            }
            new_rows: list[dict[str, Any]] = []
            for row in ordered:
                old = existing.get(row["ts"])
                if old is not None:
                    if row["available_at"] is None:
                        row["available_at"] = old["available_at"]
                    if old != row:
                        raise ArchiveConflictError(f"barre archivée contradictoire : {symbol} {tf} {row['ts']}")
                    continue
                if row["available_at"] is None and decision_at is not None:
                    row["available_at"] = _iso(decision_at)
                new_rows.append(row)
            if new_rows:
                c.execute(insert(market_bars), new_rows)
            if cycle_id:
                digest = _fingerprint(ordered)
                key = {"workspace": self.workspace.value, "cycle_id": cycle_id, "symbol": symbol, "timeframe": tf}
                window = {
                    **key, "n_bars": len(ordered), "first_ts": ordered[0]["ts"],
                    "last_ts": ordered[-1]["ts"], "fingerprint": digest,
                    "decision_at": _iso(decision_at),
                }
                prior = c.execute(select(cycle_inputs).filter_by(**key)).first()
                if prior is None:
                    c.execute(insert(cycle_inputs).values(**window))
                    c.execute(insert(cycle_input_bars), [{**key, "ts": r["ts"]} for r in ordered])
                elif dict(prior._mapping) != window:
                    raise ArchiveConflictError(f"fenêtre de cycle contradictoire : {cycle_id} {symbol} {tf}")
                else:
                    members = list(c.execute(select(cycle_input_bars.c.ts).filter_by(**key).order_by(cycle_input_bars.c.ts)).scalars())
                    if members != [r["ts"] for r in ordered]:
                        raise ArchiveIncompleteError(f"fenêtre de cycle incomplète : {cycle_id} {symbol} {tf}")
        with self.engine.connect() as c:
            self._last[(symbol, tf)] = c.execute(
                select(market_bars.c.ts).where(market_bars.c.workspace == self.workspace.value)
                .where((market_bars.c.symbol == symbol) & (market_bars.c.timeframe == tf))
                .order_by(market_bars.c.ts.desc()).limit(1)
            ).scalar_one()
        return len(new_rows)

    def load(
        self,
        symbol: str,
        timeframe: Timeframe,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int | None = None,
        *,
        available_until: datetime | None = None,
    ) -> list[Bar]:
        q = select(market_bars).where(market_bars.c.workspace == self.workspace.value).where(
            (market_bars.c.symbol == symbol) & (market_bars.c.timeframe == timeframe.value)
        )
        if since is not None:
            q = q.where(market_bars.c.ts >= int(_utc(since).timestamp()))
        if until is not None:
            q = q.where(market_bars.c.ts <= int(_utc(until).timestamp()))
        q = q.order_by(market_bars.c.ts)
        if limit is not None and available_until is None:
            q = q.limit(limit)
        with self.engine.connect() as c:
            bars = [_bar_from_row(r) for r in c.execute(q)]
        if available_until is not None:
            cutoff = _utc(available_until)
            bars = [bar for bar in bars if _available_at(bar, timeframe) <= cutoff]
        return bars[:limit] if limit is not None else bars

    def fingerprint(
        self, symbol: str, timeframe: Timeframe,
        since: datetime | None = None, until: datetime | None = None,
        *, available_until: datetime | None = None,
    ) -> str:
        bars = self.load(symbol, timeframe, since, until, available_until=available_until)
        return _fingerprint([_bar_row(symbol, timeframe.value, bar) for bar in bars])

    def load_cycle(self, cycle_id: str, *, symbol: str | None = None) -> dict[str, dict[Timeframe, list[Bar]]]:
        """Charge les identités archivées; refuse les anciennes fenêtres sans membres exacts."""
        windows = self.cycle_inputs(cycle_id)
        if symbol is not None:
            windows = [window for window in windows if window["symbol"] == symbol]
        if not windows:
            raise ArchiveIncompleteError(f"aucune fenêtre archivée pour le cycle {cycle_id}")
        result: dict[str, dict[Timeframe, list[Bar]]] = {}
        with self.engine.connect() as c:
            for window in windows:
                symbol = str(window["symbol"])
                tf = Timeframe(window["timeframe"])
                key = {"workspace": self.workspace.value, "cycle_id": cycle_id, "symbol": symbol, "timeframe": tf.value}
                try:
                    members = list(c.execute(
                        select(cycle_input_bars.c.ts).filter_by(**key).order_by(cycle_input_bars.c.ts)
                    ).scalars())
                except SQLAlchemyError as exc:
                    raise ArchiveIncompleteError(f"manifeste absent : {cycle_id} {symbol} {tf.value}") from exc
                if len(members) != window["n_bars"]:
                    raise ArchiveIncompleteError(f"membres manquants : {cycle_id} {symbol} {tf.value}")
                if not members:
                    if (window["first_ts"] != 0 or window["last_ts"] != 0
                            or window["fingerprint"] != _fingerprint([]) or window["decision_at"] is None):
                        raise ArchiveIncompleteError(f"fenêtre vide invalide : {cycle_id} {symbol} {tf.value}")
                    result.setdefault(symbol, {})[tf] = []
                    continue
                try:
                    rows = list(c.execute(
                        select(market_bars).where(market_bars.c.workspace == self.workspace.value)
                        .where((market_bars.c.symbol == symbol) & (market_bars.c.timeframe == tf.value)
                               & market_bars.c.ts.in_(members))
                        .order_by(market_bars.c.ts)
                    ))
                except SQLAlchemyError as exc:
                    raise ArchiveIncompleteError(f"barres absentes : {cycle_id} {symbol} {tf.value}") from exc
                if ([r.ts for r in rows] != members or members[0] != window["first_ts"]
                        or members[-1] != window["last_ts"]):
                    raise ArchiveIncompleteError(f"barres manquantes : {cycle_id} {symbol} {tf.value}")
                if not window["fingerprint"] or _fingerprint([dict(r._mapping) for r in rows]) != window["fingerprint"]:
                    raise ArchiveIncompleteError(f"fingerprint divergent : {cycle_id} {symbol} {tf.value}")
                bars = [_bar_from_row(r) for r in rows]
                if window["decision_at"] is None:
                    raise ArchiveIncompleteError(f"cutoff inconnu : {cycle_id} {symbol} {tf.value}")
                cutoff = datetime.fromisoformat(window["decision_at"])
                if any(_available_at(bar, tf) > cutoff for bar in bars):
                    raise ArchiveIncompleteError(f"barre future : {cycle_id} {symbol} {tf.value}")
                result.setdefault(symbol, {})[tf] = bars
        return result

    def cycle_inputs(self, cycle_id: str) -> list[dict[str, Any]]:
        try:
            with self.engine.connect() as c:
                rows = c.execute(select(cycle_inputs).where(cycle_inputs.c.workspace == self.workspace.value, cycle_inputs.c.cycle_id == cycle_id)
                                 .order_by(cycle_inputs.c.symbol, cycle_inputs.c.timeframe)).all()
        except SQLAlchemyError as exc:
            raise ArchiveIncompleteError(f"archive absente ou incompatible pour le cycle {cycle_id}") from exc
        return [dict(r._mapping) for r in rows]

    def stats(self) -> dict[str, Any]:
        with self.engine.connect() as c:
            n = c.execute(text("SELECT COUNT(*) FROM market_bars WHERE workspace=:w"), {"w": self.workspace.value}).scalar_one()
            s = c.execute(text("SELECT COUNT(DISTINCT symbol) FROM market_bars WHERE workspace=:w"), {"w": self.workspace.value}).scalar_one()
        return {"bars": int(n), "symbols": int(s)}
