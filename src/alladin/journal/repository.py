"""Persistance SQLAlchemy (SQLite au MVP, migrable PostgreSQL).

Garanties d'intégrité côté base (triggers SQLite) :
  - journal_events : ni UPDATE ni DELETE (append-only) ; chaîne de hachage vérifiable ;
  - runs : jamais supprimés ; un run PASSED/FAILED/KILLED ne peut plus être modifié ;
  - trades : jamais supprimés ; un trade CLOSED ne peut plus être modifié.
Pour PostgreSQL, porter ces triggers dans la migration (voir docs/ARCHITECTURE.md).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Column, Float, Integer, MetaData, String, Table, Text, create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from alladin.journal.models import JournalEvent, RunRecord, TradeRecord

metadata = MetaData()

runs = Table(
    "runs",
    metadata,
    Column("run_id", String, primary_key=True),
    Column("seq", Integer, unique=True, nullable=False),
    Column("profile_id", String, nullable=False),
    Column("state", String, nullable=False),
    Column("phase", Integer, nullable=False, default=1),
    Column("initial_balance", Float, nullable=False),
    Column("broker", String, nullable=False),
    Column("account", String, nullable=False, default=""),
    Column("magic", Integer, nullable=False),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
    Column("watchdog_state", Text, nullable=False, default="{}"),
    Column("kind", String, nullable=False, default="RUN"),  # RUN | SYSTEM-TEST
)

journal_events = Table(
    "journal_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", String, nullable=False, index=True),
    Column("seq", Integer, nullable=False),
    Column("ts", String, nullable=False),
    Column("type", String, nullable=False, index=True),
    Column("payload", Text, nullable=False),
    Column("cycle_id", String, nullable=True, index=True),
    Column("prev_hash", String, nullable=False),
    Column("hash", String, nullable=False),
)

_TRADE_COLS = [
    ("trade_id", String), ("proposal_id", String), ("opportunity_id", String),
    ("run_id", String), ("symbol", String), ("side", String),
    ("strategy_id", String), ("strategy_version", String), ("regime", String), ("agent", String),
    ("status", String), ("ticket", Integer), ("volume", Float), ("entry_requested", Float),
    ("entry_executed", Float), ("stop_loss", Float), ("take_profit", Float), ("risk_amount", Float),
    ("risk_pct_of_wc", Float), ("spread_at_entry", Float), ("slippage", Float), ("opened_at", String),
    ("closed_at", String), ("close_price", Float), ("close_reason", String), ("pnl_gross", Float),
    ("commission", Float), ("swap", Float), ("net_pnl", Float), ("r_multiple", Float),
    ("mae", Float), ("mfe", Float), ("equity_after", Float), ("adopted", Integer), ("cycle_id", String),
]  # fmt: skip
trades = Table(
    "trades",
    metadata,
    *[Column(n, t, primary_key=(n == "trade_id")) for n, t in _TRADE_COLS],
)

paper_positions = Table(
    "paper_positions",
    metadata,
    Column("paper_id", String, primary_key=True),
    Column("run_id", String, nullable=False, index=True),
    Column("cycle_id", String),
    Column("symbol", String, nullable=False),
    Column("side", String, nullable=False),
    Column("volume", Float, nullable=False),
    Column("entry_price", Float, nullable=False),
    Column("sl", Float),
    Column("tp", Float),
    Column("opened_at", String, nullable=False),
    Column("exit_price", Float),
    Column("closed_at", String),
    Column("status", String, nullable=False, default="OPEN"),
    Column("close_reason", String),
    Column("pnl_pips", Float, default=0.0),
    Column("mfe_pips", Float, default=0.0),
    Column("mae_pips", Float, default=0.0),
    Column("intent_json", Text),
)

_TRIGGERS = [
    "CREATE TRIGGER IF NOT EXISTS journal_no_update BEFORE UPDATE ON journal_events "
    "BEGIN SELECT RAISE(ABORT, 'journal is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS journal_no_delete BEFORE DELETE ON journal_events "
    "BEGIN SELECT RAISE(ABORT, 'journal is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS runs_no_delete BEFORE DELETE ON runs "
    "BEGIN SELECT RAISE(ABORT, 'runs are never deleted'); END",
    "CREATE TRIGGER IF NOT EXISTS runs_terminal_immutable BEFORE UPDATE ON runs "
    "WHEN OLD.state IN ('PASSED','FAILED','KILLED') "
    "BEGIN SELECT RAISE(ABORT, 'run in terminal state is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS trades_no_delete BEFORE DELETE ON trades "
    "BEGIN SELECT RAISE(ABORT, 'trades are never deleted'); END",
    "CREATE TRIGGER IF NOT EXISTS trades_closed_immutable BEFORE UPDATE ON trades "
    "WHEN OLD.status = 'CLOSED' BEGIN SELECT RAISE(ABORT, 'closed trade is immutable'); END",
]

GENESIS = "0" * 64


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def _parse(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _canon(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)


def _hash(prev: str, run_id: str, seq: int, ts: str, type_: str, body: str, cycle_id: str | None) -> str:
    base = f"{prev}|{run_id}|{seq}|{ts}|{type_}|{body}"
    if cycle_id:  # le cycle_id est couvert par la chaîne (compatible avec les événements sans cycle)
        base += f"|{cycle_id}"
    return hashlib.sha256(base.encode()).hexdigest()


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite") and (":memory:" in url or url in ("sqlite://", "sqlite:///")):
        return create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    return create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})


class JournalRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        if engine.dialect.name == "sqlite":

            @event.listens_for(engine, "connect")
            def _pragmas(dbapi_conn: Any, _rec: Any) -> None:
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA synchronous=FULL")
                cur.close()

        metadata.create_all(engine)
        self._migrate()
        if engine.dialect.name == "sqlite":
            with engine.begin() as c:
                for ddl in _TRIGGERS:
                    c.execute(text(ddl))

    def _migrate(self) -> None:
        """Migration légère : ajoute les colonnes apparues après la création d'une base existante."""
        wanted = {"runs": ["kind"], "journal_events": ["cycle_id"],
                  "trades": ["cycle_id", "proposal_id", "opportunity_id"]}
        with self.engine.begin() as c:
            for table, columns in wanted.items():
                cols = ({r[1] for r in c.execute(text(f"PRAGMA table_info({table})"))}
                        if self.engine.dialect.name == "sqlite" else set(columns))
                for col in columns:
                    if col not in cols:
                        default = " DEFAULT 'RUN' NOT NULL" if col == "kind" else ""
                        c.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} VARCHAR{default}"))

    @classmethod
    def from_url(cls, url: str) -> JournalRepository:
        return cls(make_engine(url))

    # ------------------------------------------------------------------ runs

    def next_run_seq(self) -> int:
        with self.engine.connect() as c:
            v = c.execute(text("SELECT COALESCE(MAX(seq), 0) FROM runs")).scalar_one()
        return int(v) + 1

    def next_label_no(self, kind: str) -> int:
        with self.engine.connect() as c:
            v = c.execute(text("SELECT COUNT(*) FROM runs WHERE kind=:k"), {"k": kind}).scalar_one()
        return int(v) + 1

    def create_run(self, rec: RunRecord) -> None:
        with self.engine.begin() as c:
            c.execute(
                runs.insert().values(
                    run_id=rec.run_id,
                    seq=rec.seq,
                    profile_id=rec.profile_id,
                    state=rec.state,
                    phase=rec.phase,
                    initial_balance=rec.initial_balance,
                    broker=rec.broker,
                    account=rec.account,
                    magic=rec.magic,
                    kind=rec.kind,
                    created_at=_iso(rec.created_at),
                    updated_at=_iso(rec.updated_at),
                    watchdog_state=_canon(rec.watchdog_state),
                )
            )

    def update_run(
        self, run_id: str, state: str, phase: int, watchdog_state: dict[str, Any], now: datetime
    ) -> None:
        with self.engine.begin() as c:
            c.execute(
                runs.update()
                .where(runs.c.run_id == run_id)
                .values(state=state, phase=phase, watchdog_state=_canon(watchdog_state), updated_at=_iso(now))
            )

    @staticmethod
    def _run(row: Any) -> RunRecord:
        return RunRecord(
            run_id=row.run_id,
            seq=row.seq,
            profile_id=row.profile_id,
            state=row.state,
            phase=row.phase,
            initial_balance=row.initial_balance,
            broker=row.broker,
            account=row.account,
            magic=row.magic,
            kind=row.kind or "RUN",
            created_at=_parse(row.created_at),
            updated_at=_parse(row.updated_at),
            watchdog_state=json.loads(row.watchdog_state),
        )

    def get_run(self, run_id: str) -> RunRecord | None:
        with self.engine.connect() as c:
            row = c.execute(runs.select().where(runs.c.run_id == run_id)).first()
        return self._run(row) if row else None

    def list_runs(self) -> list[RunRecord]:
        with self.engine.connect() as c:
            rows = c.execute(runs.select().order_by(runs.c.seq)).all()
        return [self._run(r) for r in rows]

    # ------------------------------------------------------------------ événements (append-only)

    def append(
        self,
        run_id: str,
        type_: str,
        payload: dict[str, Any],
        ts: datetime | None = None,
        cycle_id: str | None = None,
    ) -> JournalEvent:
        ts = ts or datetime.now(UTC)
        body = _canon(payload)
        with self.engine.begin() as c:
            last = c.execute(
                text("SELECT seq, hash FROM journal_events WHERE run_id=:r ORDER BY seq DESC LIMIT 1"),
                {"r": run_id},
            ).first()
            seq, prev = (last.seq + 1, last.hash) if last else (1, GENESIS)
            h = _hash(prev, run_id, seq, _iso(ts), type_, body, cycle_id)
            res = c.execute(
                journal_events.insert().values(
                    run_id=run_id,
                    seq=seq,
                    ts=_iso(ts),
                    type=type_,
                    payload=body,
                    cycle_id=cycle_id,
                    prev_hash=prev,
                    hash=h,
                )
            )
            eid = int(res.inserted_primary_key[0])  # type: ignore[index]
        return JournalEvent(
            id=eid,
            run_id=run_id,
            seq=seq,
            ts=ts,
            type=type_,
            cycle_id=cycle_id,
            payload=json.loads(body),
            hash=h,
        )

    def events(
        self,
        run_id: str,
        types: list[str] | None = None,
        limit: int | None = None,
        desc: bool = False,
        cycle_id: str | None = None,
    ) -> list[JournalEvent]:
        q = journal_events.select().where(journal_events.c.run_id == run_id)
        if cycle_id:
            q = q.where(journal_events.c.cycle_id == cycle_id)
        if types:
            q = q.where(journal_events.c.type.in_(types))
        q = q.order_by(journal_events.c.seq.desc() if desc else journal_events.c.seq)
        if limit:
            q = q.limit(limit)
        with self.engine.connect() as c:
            rows = c.execute(q).all()
        return [
            JournalEvent(
                id=r.id,
                run_id=r.run_id,
                seq=r.seq,
                ts=_parse(r.ts),
                type=r.type,
                cycle_id=r.cycle_id,
                payload=json.loads(r.payload),
                hash=r.hash,
            )
            for r in rows
        ]

    def verify_chain(self, run_id: str) -> tuple[bool, str]:
        """Recalcule la chaîne de hachage ; (False, raison) si une ligne a été altérée/supprimée."""
        with self.engine.connect() as c:
            rows = c.execute(
                journal_events.select()
                .where(journal_events.c.run_id == run_id)
                .order_by(journal_events.c.seq)
            ).all()
        prev = GENESIS
        for i, r in enumerate(rows, start=1):
            if r.seq != i:
                return False, f"séquence rompue à {i} (trouvé {r.seq})"
            expect = _hash(prev, r.run_id, r.seq, r.ts, r.type, r.payload, r.cycle_id)
            if r.prev_hash != prev or r.hash != expect:
                return False, f"hash invalide à seq={r.seq}"
            prev = r.hash
        return True, f"{len(rows)} événements vérifiés"

    def cycles(self, run_id: str) -> list[dict[str, Any]]:
        """Liste des cycles d'un run (du plus récent au plus ancien)."""
        with self.engine.connect() as c:
            rows = c.execute(
                text(
                    "SELECT cycle_id, MIN(ts) AS started, MAX(ts) AS ended, COUNT(*) AS n FROM journal_events "
                    "WHERE run_id=:r AND cycle_id IS NOT NULL GROUP BY cycle_id ORDER BY MIN(id) DESC"
                ),
                {"r": run_id},
            ).all()
        return [{"cycle_id": r.cycle_id, "started": r.started, "ended": r.ended, "events": r.n} for r in rows]

    # ------------------------------------------------------------------ trades

    @staticmethod
    def _trade(row: Any) -> TradeRecord:
        d = dict(row._mapping)
        for k in ("opened_at", "closed_at"):
            d[k] = _parse(d[k]) if d[k] else None
        d["adopted"] = bool(d["adopted"])
        d["mae"], d["mfe"] = d["mae"] or 0.0, d["mfe"] or 0.0
        return TradeRecord.model_validate(d)

    def insert_trade(self, t: TradeRecord) -> None:
        d = t.model_dump()
        d["opened_at"] = _iso(t.opened_at)
        d["closed_at"] = _iso(t.closed_at) if t.closed_at else None
        d["adopted"] = int(t.adopted)
        with self.engine.begin() as c:
            c.execute(trades.insert().values(**d))

    def update_trade(self, trade_id: str, **fields: Any) -> None:
        for k in ("closed_at", "opened_at"):
            if isinstance(fields.get(k), datetime):
                fields[k] = _iso(fields[k])
        with self.engine.begin() as c:
            c.execute(trades.update().where(trades.c.trade_id == trade_id).values(**fields))

    def get_trade(self, trade_id: str) -> TradeRecord | None:
        with self.engine.connect() as c:
            row = c.execute(trades.select().where(trades.c.trade_id == trade_id)).first()
        return self._trade(row) if row else None

    def trades_for_run(self, run_id: str, status: str | None = None) -> list[TradeRecord]:
        q = trades.select().where(trades.c.run_id == run_id).order_by(trades.c.opened_at)
        if status:
            q = q.where(trades.c.status == status)
        with self.engine.connect() as c:
            rows = c.execute(q).all()
        return [self._trade(r) for r in rows]

    def all_closed_trades(self) -> list[TradeRecord]:
        with self.engine.connect() as c:
            rows = c.execute(trades.select().where(trades.c.status == "CLOSED")).all()
        return [self._trade(r) for r in rows]

    # ------------------------------------------------------------------ paper positions

    def insert_paper_position(self, d: dict[str, Any]) -> None:
        with self.engine.begin() as c:
            c.execute(paper_positions.insert().values(**d))

    def update_paper_position(self, paper_id: str, **fields: Any) -> None:
        with self.engine.begin() as c:
            c.execute(
                paper_positions.update().where(paper_positions.c.paper_id == paper_id).values(**fields)
            )

    def get_paper_position(self, paper_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as c:
            row = c.execute(
                paper_positions.select().where(paper_positions.c.paper_id == paper_id)
            ).first()
        return dict(row._mapping) if row else None

    def list_paper_positions(self, run_id: str, status: str | None = None) -> list[dict[str, Any]]:
        q = paper_positions.select().where(paper_positions.c.run_id == run_id)
        if status:
            q = q.where(paper_positions.c.status == status)
        q = q.order_by(paper_positions.c.opened_at)
        with self.engine.connect() as c:
            rows = c.execute(q).all()
        return [dict(r._mapping) for r in rows]
