"""Jafar PAPER engine — simulateur crypto sur données de marché réelles Binance.

Chemin d'exécution complet :
  ActionProposal (Brain)
  → validation mode (evaluate_jafar_mode → simulated_execution_allowed)
  → PortfolioRisk guard (capital disponible, concentration, drawdown)
  → OrderLifecycleClaim (PROPOSED)
  → RiskEngine.evaluate() → RISK_APPROVED
  → OrderLifecycleClaim (SUBMITTING)
  → SimulatedFill (bid/ask réel ± slippage)
  → OrderLifecycleClaim (FILLED)
  → Portfolio update (cash, holdings, fees, PnL)
  → Journal events
  → SL/TP monitoring à chaque tick_all()

PAPER ne soumet JAMAIS d'ordre Binance réel.
Déterministe autant que possible (seed slippage par proposal_id).
Restart-safe : toutes les positions persistées via JournalRepository.
Workspace-scoped : aucune collision avec Alladin MT5.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from alladin.brain import ActionProposal
from alladin.brokers.crypto import CryptoDataProvider
from alladin.core.enums import Side
from alladin.core.workspace import WorkspaceId
from alladin.execution.order_lifecycle import (
    CanonicalOrderStatus,
    OrderLifecycleRepository,
    client_order_id,
)
from alladin.journal.models import EventType

if TYPE_CHECKING:
    from alladin.journal.repository import JournalRepository
    from alladin.journal.service import JournalService


# ---------------------------------------------------------------------------
# Constantes par défaut
# ---------------------------------------------------------------------------

DEFAULT_TAKER_FEE_BPS: float = 10.0   # 0.10% — fee taker standard Binance
DEFAULT_SLIPPAGE_BPS: float = 5.0     # 0.05% — slippage conservateur
DEFAULT_INITIAL_CAPITAL: float = 10_000.0  # USDT


# ---------------------------------------------------------------------------
# Modèles de données
# ---------------------------------------------------------------------------


@dataclass
class JafarPaperFill:
    """Résultat d'une exécution simulée."""

    proposal_id: str
    symbol: str
    side: Side
    quantity: float          # base asset (ex. BTC)
    fill_price: float        # prix fill simulé
    quote_amount: float      # = quantity * fill_price (en USDT)
    fee_bps: float
    fee_amount: float        # en quote asset
    slippage_bps: float
    slippage_amount: float   # en quote asset
    client_order_id: str
    filled_at: datetime


@dataclass
class JafarPaperPosition:
    """Position paper ouverte ou fermée."""

    position_id: str         # "JPP-{hex}"
    run_id: str
    workspace: str
    symbol: str
    side: Side
    quantity: float          # base asset
    entry_price: float       # prix fill réel (avec slippage)
    sl: float
    tp: float | None
    fees_paid: float         # fees à l'ouverture (quote)
    slippage_paid: float     # slippage à l'ouverture (quote)
    quote_cost: float        # capital engagé = quantity * entry_price + fees
    opened_at: datetime
    proposal_id: str
    client_order_id: str

    # Dynamique
    unrealized_pnl: float = 0.0
    mfe_amount: float = 0.0    # max favorable excursion en quote
    mae_amount: float = 0.0    # max adverse excursion en quote (positif = distance adverse)
    excursion_samples: int = 0

    # Clôture
    exit_price: float | None = None
    exit_fees: float = 0.0
    exit_slippage: float = 0.0
    closed_at: datetime | None = None
    realized_pnl: float | None = None   # net de fees
    status: str = "OPEN"                # OPEN / CLOSED_SL / CLOSED_TP / CLOSED_MANUAL

    intent_extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_open(self) -> bool:
        return self.status == "OPEN"

    def mark(self, bid: float, ask: float) -> None:
        """Met à jour unrealized PnL et excursions avec les prix courants."""
        current = bid if self.side is Side.BUY else ask
        raw_pnl = (current - self.entry_price) * self.side.sign * self.quantity
        self.unrealized_pnl = raw_pnl
        self.mfe_amount = max(self.mfe_amount, raw_pnl)
        self.mae_amount = max(self.mae_amount, -raw_pnl)
        self.excursion_samples += 1

    def check_exit(self, bid: float, ask: float) -> str | None:
        """Retourne le statut de clôture si SL/TP atteint, sinon None."""
        if self.side is Side.BUY:
            if bid <= self.sl:
                return "CLOSED_SL"
            if self.tp is not None and bid >= self.tp:
                return "CLOSED_TP"
        else:  # SELL
            if ask >= self.sl:
                return "CLOSED_SL"
            if self.tp is not None and ask <= self.tp:
                return "CLOSED_TP"
        return None

    def to_persistence(self) -> dict[str, Any]:
        import json

        extra = {
            "quote_cost": self.quote_cost,
            "fees_paid": self.fees_paid,
            "slippage_paid": self.slippage_paid,
            "client_order_id": self.client_order_id,
            "exit_fees": self.exit_fees,
            "exit_slippage": self.exit_slippage,
            **self.intent_extra,
        }
        return {
            "paper_id": self.position_id,
            "run_id": self.run_id,
            "cycle_id": "",
            "symbol": self.symbol,
            "side": self.side.value,
            "volume": self.quantity,
            "original_volume": self.quantity,
            "realized_pnl": self.realized_pnl or 0.0,
            "initial_risk": 0.0,
            "account_currency": "USDT",
            "price_value_per_lot": 1.0,
            "mae_amount": self.mae_amount,
            "mfe_amount": self.mfe_amount,
            "excursion_samples": self.excursion_samples,
            "entry_price": self.entry_price,
            "sl": self.sl,
            "tp": self.tp,
            "opened_at": self.opened_at.isoformat(),
            "exit_price": self.exit_price,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "status": self.status,
            "close_reason": self.status if self.status != "OPEN" else None,
            "pnl_pips": self.realized_pnl or 0.0,
            "mfe_pips": self.mfe_amount,
            "mae_pips": self.mae_amount,
            "intent_json": json.dumps(extra, default=str),
            "workspace": self.workspace,
            "proposal_id": self.proposal_id,
        }

    @classmethod
    def from_persistence(cls, d: dict[str, Any]) -> JafarPaperPosition:
        import json

        extra = json.loads(d.get("intent_json") or "{}")
        opened = datetime.fromisoformat(d["opened_at"])
        closed = datetime.fromisoformat(d["closed_at"]) if d.get("closed_at") else None
        pos = cls(
            position_id=d["paper_id"],
            run_id=d["run_id"],
            workspace=d.get("workspace", WorkspaceId.JAFAR.value),
            symbol=d["symbol"],
            side=Side(d["side"]),
            quantity=float(d["volume"]),
            entry_price=float(d["entry_price"]),
            sl=float(d["sl"]),
            tp=float(d["tp"]) if d.get("tp") is not None else None,
            fees_paid=float(extra.get("fees_paid", 0.0)),
            slippage_paid=float(extra.get("slippage_paid", 0.0)),
            quote_cost=float(extra.get("quote_cost", float(d["volume"]) * float(d["entry_price"]))),
            opened_at=opened,
            proposal_id=d.get("proposal_id", ""),
            client_order_id=extra.get("client_order_id", ""),
            unrealized_pnl=0.0,
            mfe_amount=float(d.get("mfe_amount") or 0.0),
            mae_amount=float(d.get("mae_amount") or 0.0),
            excursion_samples=int(d.get("excursion_samples") or 0),
            exit_price=float(d["exit_price"]) if d.get("exit_price") is not None else None,
            exit_fees=float(extra.get("exit_fees", 0.0)),
            exit_slippage=float(extra.get("exit_slippage", 0.0)),
            closed_at=closed,
            realized_pnl=float(d["realized_pnl"]) if d.get("realized_pnl") is not None else None,
            status=d.get("status", "OPEN"),
        )
        return pos


@dataclass
class JafarPaperPortfolioSnapshot:
    """Vue instantanée du portefeuille simulé."""

    observed_at: datetime
    initial_capital: float
    cash: float              # USDT libre
    invested: float          # USDT engagé dans positions ouvertes
    unrealized_pnl: float
    realized_pnl: float
    total_fees: float
    total_value: float       # cash + invested + unrealized
    peak_value: float
    drawdown_pct: float
    open_positions: int
    closed_trades: int
    win_rate: float | None


# ---------------------------------------------------------------------------
# Portfolio simulé
# ---------------------------------------------------------------------------


class JafarSimulatedPortfolio:
    """Gère le capital simulé : solde, holdings, PnL, fees, drawdown."""

    def __init__(self, initial_capital: float, workspace: str) -> None:
        if not math.isfinite(initial_capital) or initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        self.initial_capital = initial_capital
        self.workspace = workspace
        self.cash = initial_capital
        self.realized_pnl: float = 0.0
        self.total_fees: float = 0.0
        self.peak_value: float = initial_capital
        self._open: dict[str, JafarPaperPosition] = {}   # position_id → position
        self._closed: list[JafarPaperPosition] = []

    def can_afford(self, quote_amount: float, fee: float) -> bool:
        """Vérifie que le cash disponible couvre l'achat + fee."""
        total = quote_amount + fee
        return math.isfinite(total) and total > 0 and self.cash >= total

    def debit(self, pos: JafarPaperPosition) -> None:
        """Débite le cash à l'ouverture."""
        self.cash -= pos.quote_cost
        self.total_fees += pos.fees_paid
        self._open[pos.position_id] = pos

    def credit(self, pos: JafarPaperPosition, proceeds: float, fees: float) -> None:
        """Crédite le cash à la clôture."""
        self.cash += proceeds - fees
        self.total_fees += fees
        pnl = (proceeds - fees) - pos.quote_cost
        pos.realized_pnl = pnl
        self.realized_pnl += pnl
        self._open.pop(pos.position_id, None)
        self._closed.append(pos)

    def unrealized_pnl(self) -> float:
        return sum(p.unrealized_pnl for p in self._open.values())

    def invested(self) -> float:
        return sum(p.quote_cost for p in self._open.values())

    def total_value(self) -> float:
        return self.cash + self.unrealized_pnl()

    def update_peak(self) -> None:
        tv = self.total_value()
        if tv > self.peak_value:
            self.peak_value = tv

    def drawdown_pct(self) -> float:
        tv = self.total_value()
        if self.peak_value <= 0:
            return 0.0
        dd = (self.peak_value - tv) / self.peak_value * 100
        return max(0.0, dd)

    def snapshot(self, now: datetime) -> JafarPaperPortfolioSnapshot:
        self.update_peak()
        closed = self._closed
        wins = [p for p in closed if (p.realized_pnl or 0.0) > 0]
        win_rate = len(wins) / len(closed) if closed else None
        return JafarPaperPortfolioSnapshot(
            observed_at=now,
            initial_capital=self.initial_capital,
            cash=self.cash,
            invested=self.invested(),
            unrealized_pnl=self.unrealized_pnl(),
            realized_pnl=self.realized_pnl,
            total_fees=self.total_fees,
            total_value=self.total_value(),
            peak_value=self.peak_value,
            drawdown_pct=self.drawdown_pct(),
            open_positions=len(self._open),
            closed_trades=len(closed),
            win_rate=win_rate,
        )


# ---------------------------------------------------------------------------
# Portfolio risk guard
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PortfolioRiskLimits:
    max_invested_pct: float = 80.0          # max capital engagé
    max_position_pct: float = 20.0          # max par position
    max_drawdown_pct: float = 20.0          # dd max depuis pic
    max_open_positions: int = 10            # nb max de positions ouvertes


@dataclass(frozen=True)
class PortfolioRiskResult:
    approved: bool
    reasons: tuple[str, ...]


def check_portfolio_risk(
    portfolio: JafarSimulatedPortfolio,
    quote_amount: float,
    fee: float,
    limits: PortfolioRiskLimits,
) -> PortfolioRiskResult:
    reasons: list[str] = []
    total = portfolio.total_value()
    if total <= 0:
        reasons.append("PORTFOLIO_BANKRUPT")
        return PortfolioRiskResult(approved=False, reasons=tuple(reasons))
    if portfolio.drawdown_pct() >= limits.max_drawdown_pct:
        reasons.append(f"DRAWDOWN_LIMIT_EXCEEDED:{portfolio.drawdown_pct():.1f}%>={limits.max_drawdown_pct}%")
    if not portfolio.can_afford(quote_amount, fee):
        reasons.append("INSUFFICIENT_CASH")
    invested_after = portfolio.invested() + quote_amount + fee
    if total > 0 and invested_after / total * 100 > limits.max_invested_pct:
        reasons.append(f"MAX_INVESTED_EXCEEDED:{invested_after/total*100:.1f}%>{limits.max_invested_pct}%")
    pos_pct = (quote_amount + fee) / total * 100 if total > 0 else 100.0
    if pos_pct > limits.max_position_pct:
        reasons.append(f"POSITION_TOO_LARGE:{pos_pct:.1f}%>{limits.max_position_pct}%")
    if len(portfolio._open) >= limits.max_open_positions:
        reasons.append(f"MAX_POSITIONS_EXCEEDED:{len(portfolio._open)}>={limits.max_open_positions}")
    return PortfolioRiskResult(approved=not reasons, reasons=tuple(reasons))


# ---------------------------------------------------------------------------
# Simulateur de fill
# ---------------------------------------------------------------------------


def _deterministic_slippage(proposal_id: str, slippage_bps: float) -> float:
    """Slippage déterministe basé sur le hash du proposal_id (reproductible)."""
    h = int(hashlib.sha256(proposal_id.encode()).hexdigest(), 16)
    # Varie entre 0 et slippage_bps
    return (h % 10000) / 10000 * slippage_bps


def simulate_fill(
    proposal: ActionProposal,
    bid: float,
    ask: float,
    quantity: float,
    *,
    taker_fee_bps: float,
    slippage_bps: float,
    now: datetime,
    workspace: WorkspaceId,
) -> JafarPaperFill:
    """Simule un fill au prix bid/ask courant avec slippage et fee."""
    if quantity <= 0 or not math.isfinite(quantity):
        raise ValueError("quantity must be positive")
    if bid <= 0 or ask <= 0 or ask <= bid:
        raise ValueError("invalid bid/ask")

    # Slippage déterministe par proposal
    actual_slippage_bps = _deterministic_slippage(proposal.proposal_id, slippage_bps)
    slip_factor = actual_slippage_bps / 10_000

    if proposal.action.value == "LONG":  # BUY — on paie l'ask + slippage
        fill_price = ask * (1 + slip_factor)
        side = Side.BUY
    else:  # SHORT / SELL — on vend au bid - slippage
        fill_price = bid * (1 - slip_factor)
        side = Side.SELL

    if not math.isfinite(fill_price) or fill_price <= 0:
        raise ValueError("fill_price computation overflow")

    quote_amount = fill_price * quantity
    fee_amount = quote_amount * taker_fee_bps / 10_000
    slippage_amount = abs(fill_price - (ask if side is Side.BUY else bid)) * quantity

    coid = client_order_id(workspace, proposal.run_id, proposal.proposal_id)

    return JafarPaperFill(
        proposal_id=proposal.proposal_id,
        symbol=proposal.symbol or "",
        side=side,
        quantity=quantity,
        fill_price=fill_price,
        quote_amount=quote_amount,
        fee_bps=taker_fee_bps,
        fee_amount=fee_amount,
        slippage_bps=actual_slippage_bps,
        slippage_amount=slippage_amount,
        client_order_id=coid,
        filled_at=now,
    )


# ---------------------------------------------------------------------------
# Moteur principal
# ---------------------------------------------------------------------------


class JafarPaperOpenError(ValueError):
    pass


class JafarPaperEngine:
    """Moteur PAPER Jafar — données réelles Binance, exécution 100% simulée.

    Usage typique (boucle FAST) :
        closed = engine.tick_all()          # met à jour toutes les positions
        proposal = brain.decide(ctx)        # Brain décide
        fill = engine.open_position(proposal, qty, sl, tp)   # simule l'ouverture
    """

    def __init__(
        self,
        provider: CryptoDataProvider,
        run_id: str,
        workspace: WorkspaceId,
        *,
        initial_capital: float = DEFAULT_INITIAL_CAPITAL,
        taker_fee_bps: float = DEFAULT_TAKER_FEE_BPS,
        slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
        risk_limits: PortfolioRiskLimits | None = None,
        repo: JournalRepository | None = None,
        lifecycle: OrderLifecycleRepository | None = None,
        journal: JournalService | None = None,
    ) -> None:
        self.provider = provider
        self.run_id = run_id
        self.workspace = workspace
        self.taker_fee_bps = taker_fee_bps
        self.slippage_bps = slippage_bps
        self.risk_limits = risk_limits or PortfolioRiskLimits()
        self._repo = repo
        self._lifecycle = lifecycle
        self._journal = journal

        self.portfolio = JafarSimulatedPortfolio(initial_capital, workspace.value)
        self._open: dict[str, JafarPaperPosition] = {}   # position_id → pos
        self._closed: list[JafarPaperPosition] = []

    # ------------------------------------------------------------------ restore

    def restore(self) -> int:
        """Restaure les positions ouvertes depuis la persistance. Retourne le nb restauré."""
        if self._repo is None:
            return 0
        self._open.clear()
        self._closed.clear()
        rows = self._repo.list_paper_positions(self.run_id, status="OPEN")
        for row in rows:
            pos = JafarPaperPosition.from_persistence(row)
            self._open[pos.position_id] = pos
            self.portfolio.cash -= pos.quote_cost
            self.portfolio.total_fees += pos.fees_paid
            self.portfolio._open[pos.position_id] = pos
        closed_rows = self._repo.list_paper_positions(self.run_id, status=None)
        for row in closed_rows:
            if row.get("status") != "OPEN":
                pos = JafarPaperPosition.from_persistence(row)
                self._closed.append(pos)
                self.portfolio._closed.append(pos)
                self.portfolio.realized_pnl += pos.realized_pnl or 0.0
                self.portfolio.total_fees += pos.fees_paid + pos.exit_fees
        if self._journal:
            self._journal.log(
                self.run_id,
                EventType.INFO,
                {"paper_restore": len(rows), "closed_trades": len(self._closed)},
            )
        return len(rows)

    # ------------------------------------------------------------------ open

    def open_position(
        self,
        proposal: ActionProposal,
        quantity: float,
        sl: float,
        tp: float | None,
    ) -> JafarPaperPosition:
        """Ouvre une position simulée à partir d'un ActionProposal LONG ou SHORT.

        Raises JafarPaperOpenError si le tick est indisponible ou le portfolio refuse.
        """
        symbol = proposal.symbol
        if not symbol:
            raise JafarPaperOpenError("ActionProposal.symbol manquant")
        if proposal.action.value not in ("LONG", "SHORT"):
            raise JafarPaperOpenError(f"action non tradable : {proposal.action}")
        if quantity <= 0 or not math.isfinite(quantity):
            raise JafarPaperOpenError("quantity invalide")

        tick = self.provider.ticker(symbol)
        if tick is None or tick.bid <= 0 or tick.ask <= 0 or tick.ask <= tick.bid:
            raise JafarPaperOpenError(f"tick invalide pour {symbol}")

        now = self.provider.now()

        fill = simulate_fill(
            proposal,
            tick.bid,
            tick.ask,
            quantity,
            taker_fee_bps=self.taker_fee_bps,
            slippage_bps=self.slippage_bps,
            now=now,
            workspace=self.workspace,
        )

        # Portfolio risk guard
        risk = check_portfolio_risk(
            self.portfolio,
            fill.quote_amount,
            fill.fee_amount,
            self.risk_limits,
        )
        if not risk.approved:
            if self._journal:
                self._journal.log(
                    self.run_id,
                    EventType.EXECUTION_BLOCKED,
                    {
                        "proposal_id": proposal.proposal_id,
                        "symbol": symbol,
                        "reasons": list(risk.reasons),
                    },
                )
            raise JafarPaperOpenError(f"portfolio risk refusé: {'; '.join(risk.reasons)}")

        # OrderLifecycle trail (PROPOSED → SUBMITTING → FILLED)
        if self._lifecycle is not None:
            payload = {
                "symbol": symbol,
                "action": proposal.action.value,
                "quantity": quantity,
                "sl": sl,
                "tp": tp,
                "mode": "PAPER",
            }
            claim = self._lifecycle.claim(
                self.run_id,
                proposal.proposal_id,
                symbol,
                payload,
                now=now,
            )
            self._lifecycle.transition(claim.client_order_id, CanonicalOrderStatus.RISK_APPROVED, now=now)
            self._lifecycle.transition(claim.client_order_id, CanonicalOrderStatus.SUBMITTING, now=now)

        # Build position
        import uuid
        pos_id = f"JPP-{uuid.uuid4().hex[:12]}"
        pos = JafarPaperPosition(
            position_id=pos_id,
            run_id=self.run_id,
            workspace=self.workspace.value,
            symbol=symbol,
            side=fill.side,
            quantity=fill.quantity,
            entry_price=fill.fill_price,
            sl=sl,
            tp=tp,
            fees_paid=fill.fee_amount,
            slippage_paid=fill.slippage_amount,
            quote_cost=fill.quote_amount + fill.fee_amount,
            opened_at=fill.filled_at,
            proposal_id=proposal.proposal_id,
            client_order_id=fill.client_order_id,
            intent_extra={
                "opportunity_id": proposal.opportunity_id,
                "cycle_id": proposal.cycle_id,
            },
        )

        # Update portfolio
        self.portfolio.debit(pos)
        self._open[pos_id] = pos

        # Mark lifecycle FILLED
        if self._lifecycle is not None:
            self._lifecycle.transition(
                fill.client_order_id,
                CanonicalOrderStatus.FILLED,
                now=now,
            )

        # Persist
        self._persist_open(pos)

        # Journal
        if self._journal:
            self._journal.log(
                self.run_id,
                EventType.POSITION_OPENED,
                {
                    "paper": True,
                    "position_id": pos_id,
                    "symbol": symbol,
                    "side": fill.side.value,
                    "quantity": fill.quantity,
                    "fill_price": fill.fill_price,
                    "sl": sl,
                    "tp": tp,
                    "fee_amount": fill.fee_amount,
                    "slippage_bps": fill.slippage_bps,
                    "client_order_id": fill.client_order_id,
                    "proposal_id": proposal.proposal_id,
                },
            )

        return pos

    # ------------------------------------------------------------------ tick_all

    def tick_all(self) -> list[JafarPaperPosition]:
        """Met à jour toutes les positions ouvertes, ferme celles en SL/TP.

        Retourne la liste des positions fermées lors de cet appel.
        """
        now = self.provider.now()
        newly_closed: list[JafarPaperPosition] = []

        for pos_id, pos in list(self._open.items()):
            tick = self.provider.ticker(pos.symbol)
            if tick is None or tick.bid <= 0 or tick.ask <= 0:
                continue

            pos.mark(tick.bid, tick.ask)
            exit_status = pos.check_exit(tick.bid, tick.ask)

            if exit_status:
                # Prix de clôture au bid/ask sans slippage supplémentaire (SL/TP = ordre limit)
                exit_price = tick.bid if pos.side is Side.BUY else tick.ask
                exit_fee = exit_price * pos.quantity * self.taker_fee_bps / 10_000
                proceeds = exit_price * pos.quantity

                pos.exit_price = exit_price
                pos.exit_fees = exit_fee
                pos.closed_at = now
                pos.status = exit_status

                self.portfolio.credit(pos, proceeds, exit_fee)

                del self._open[pos_id]
                self._closed.append(pos)
                newly_closed.append(pos)

                self._persist_close(pos)

                if self._journal:
                    self._journal.log(
                        self.run_id,
                        EventType.POSITION_CLOSED,
                        {
                            "paper": True,
                            "position_id": pos_id,
                            "symbol": pos.symbol,
                            "side": pos.side.value,
                            "exit_price": exit_price,
                            "realized_pnl": pos.realized_pnl,
                            "exit_fees": exit_fee,
                            "close_reason": exit_status,
                            "mfe_amount": pos.mfe_amount,
                            "mae_amount": pos.mae_amount,
                        },
                    )
            else:
                self._persist_excursion(pos)

        self.portfolio.update_peak()
        return newly_closed

    # ------------------------------------------------------------------ close manual

    def close_position(self, position_id: str, reason: str = "CLOSED_MANUAL") -> JafarPaperPosition | None:
        """Fermeture explicite d'une position paper."""
        pos = self._open.get(position_id)
        if pos is None:
            return None
        tick = self.provider.ticker(pos.symbol)
        now = self.provider.now()
        if tick is None or tick.bid <= 0 or tick.ask <= 0:
            return None
        exit_price = tick.bid if pos.side is Side.BUY else tick.ask
        exit_fee = exit_price * pos.quantity * self.taker_fee_bps / 10_000
        proceeds = exit_price * pos.quantity

        pos.exit_price = exit_price
        pos.exit_fees = exit_fee
        pos.closed_at = now
        pos.status = reason

        pos.mark(tick.bid, tick.ask)
        self.portfolio.credit(pos, proceeds, exit_fee)

        del self._open[position_id]
        self._closed.append(pos)
        self._persist_close(pos)

        if self._journal:
            self._journal.log(
                self.run_id,
                EventType.POSITION_CLOSED,
                {
                    "paper": True,
                    "position_id": position_id,
                    "symbol": pos.symbol,
                    "realized_pnl": pos.realized_pnl,
                    "close_reason": reason,
                },
            )
        return pos

    # ------------------------------------------------------------------ queries

    def open_positions(self) -> list[JafarPaperPosition]:
        return list(self._open.values())

    def closed_positions(self) -> list[JafarPaperPosition]:
        return list(self._closed)

    def portfolio_snapshot(self) -> JafarPaperPortfolioSnapshot:
        return self.portfolio.snapshot(self.provider.now())

    def stats(self) -> dict[str, Any]:
        snap = self.portfolio_snapshot()
        return {
            "initial_capital": snap.initial_capital,
            "total_value": round(snap.total_value, 2),
            "cash": round(snap.cash, 2),
            "invested": round(snap.invested, 2),
            "unrealized_pnl": round(snap.unrealized_pnl, 2),
            "realized_pnl": round(snap.realized_pnl, 2),
            "total_fees": round(snap.total_fees, 2),
            "drawdown_pct": round(snap.drawdown_pct, 2),
            "open_positions": snap.open_positions,
            "closed_trades": snap.closed_trades,
            "win_rate": snap.win_rate,
        }

    # ------------------------------------------------------------------ persistence

    def _persist_open(self, pos: JafarPaperPosition) -> None:
        if self._repo is None:
            return
        self._repo.insert_paper_position(pos.to_persistence())

    def _persist_close(self, pos: JafarPaperPosition) -> None:
        if self._repo is None:
            return
        self._repo.update_paper_position(
            pos.position_id,
            exit_price=pos.exit_price,
            closed_at=pos.closed_at.isoformat() if pos.closed_at else None,
            status=pos.status,
            close_reason=pos.status,
            pnl_pips=pos.realized_pnl or 0.0,
            mfe_pips=pos.mfe_amount,
            mae_pips=pos.mae_amount,
            realized_pnl=pos.realized_pnl or 0.0,
            mae_amount=pos.mae_amount,
            mfe_amount=pos.mfe_amount,
            excursion_samples=pos.excursion_samples,
        )

    def _persist_excursion(self, pos: JafarPaperPosition) -> None:
        if self._repo is None:
            return
        self._repo.update_paper_position(
            pos.position_id,
            mfe_pips=pos.mfe_amount,
            mae_pips=pos.mae_amount,
            mae_amount=pos.mae_amount,
            mfe_amount=pos.mfe_amount,
            excursion_samples=pos.excursion_samples,
        )
