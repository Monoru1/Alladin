"""RiskEngine : souverain, déterministe, sans LLM.

Reçoit un TradeIntent non fiable + un RiskContext issu du broker et du watchdog. Retourne une
RiskDecision : soit un rejet avec la LISTE COMPLÈTE des raisons, soit une approbation avec le
volume calculé par le PositionSizer ET un jeton d'approbation, seul sésame accepté par les brokers.
"""

from __future__ import annotations

from alladin.brain import Action, ActionProposal
from alladin.challenge.models import RiskRules
from alladin.core.approval import issue_open_token
from alladin.core.enums import AccountType, EntryType, RunMode, RunState, Side, SymbolTradeMode
from alladin.core.models import InstrumentSpec, Position, Tick, TradeIntent
from alladin.risk import sizing
from alladin.risk.exposure import compute_exposure, currency_legs
from alladin.risk.models import RejectCode, RiskContext, RiskDecision, RiskReason
from alladin.risk.position import PositionActionContext, evaluate_position_action
from alladin.risk.sizing import PositionSizer

_EPS = 1e-9


class RiskEngine:
    def evaluate_paper_entry(
        self,
        proposal: ActionProposal,
        *,
        equity: float,
        spec: InstrumentSpec,
        tick: Tick,
        open_positions: int,
    ) -> RiskDecision:
        """Dimensionne une entrée PAPER sans inventer un faux compte broker.

        Cette porte conserve les règles déterministes applicables au marché et au
        sizing. Les contraintes portefeuille/cash sont ensuite vérifiées par le
        moteur PAPER, qui possède l'état simulé faisant autorité.
        """
        reasons: list[RiskReason] = []

        def reject(code: RejectCode, message: str) -> None:
            reasons.append(RiskReason(code=code, message=message))

        p = proposal.parameters
        if proposal.action not in (Action.LONG, Action.SHORT):
            reject(RejectCode.MODE_SAFETY, "entrée PAPER LONG/SHORT requise")
        if proposal.symbol != spec.symbol or proposal.symbol != tick.symbol:
            reject(RejectCode.INSTRUMENT_MISMATCH, "instrument incohérent entre proposition, spec et tick")
        if p.entry_type not in self.supported_entry_types:
            reject(RejectCode.ENTRY_TYPE_UNSUPPORTED, f"type d'entrée {p.entry_type} non supporté")
        if p.stop_loss is None:
            reject(RejectCode.NO_STOP_LOSS, "stop loss obligatoire : NO SL = REJECTED")
        if open_positions >= self.rules.max_open_positions:
            reject(RejectCode.MAX_POSITIONS, "nombre maximal de positions ouvertes atteint")
        if not spec.is_tradable:
            reject(RejectCode.NOT_TRADABLE, f"instrument {spec.symbol} non négociable")

        entry = tick.ask if proposal.action is Action.LONG else tick.bid
        sl = p.stop_loss
        tp = p.take_profit
        if sl is not None:
            sl_ok = sl < entry if proposal.action is Action.LONG else sl > entry
            if not sl_ok:
                reject(RejectCode.BAD_GEOMETRY, "stop loss du mauvais côté de l'entrée")
            distance = abs(entry - sl)
            if distance <= 0:
                reject(RejectCode.BAD_GEOMETRY, "distance au stop nulle")
            elif tick.spread > self.rules.max_spread_to_sl_ratio * distance:
                reject(RejectCode.SPREAD_TOO_WIDE, "spread trop large par rapport à la distance au stop")
            if tp is not None:
                tp_ok = tp > entry if proposal.action is Action.LONG else tp < entry
                if not tp_ok:
                    reject(RejectCode.BAD_GEOMETRY, "objectif du mauvais côté de l'entrée")
                elif self.rules.min_risk_reward > 0 and abs(tp - entry) / distance < self.rules.min_risk_reward:
                    reject(RejectCode.RISK_REWARD, f"ratio gain/risque < {self.rules.min_risk_reward}")

        wc = sizing.working_capital(equity, self.rules.working_capital_pct)
        cap = sizing.max_trade_risk(wc, self.rules.max_trade_risk_pct_of_working_capital)
        requested_pct = p.requested_risk_pct_of_working_capital or 0.0
        requested = wc * requested_pct / 100
        risk_amount = min(requested, cap)
        adjustments: list[str] = []
        if requested > cap + _EPS:
            if self.rules.over_cap_policy == "reject":
                reject(RejectCode.RISK_EXCEEDS_CAP, f"risque demandé {requested:.2f} > plafond {cap:.2f}")
            else:
                adjustments.append(f"risque réduit de {requested:.2f} à {cap:.2f}")

        sized = self.sizer.size(spec, entry, sl, risk_amount) if sl is not None else None
        if sized is None or sized.volume <= 0:
            reject(RejectCode.SIZING, (sized.reason or "sizing impossible") if sized else "sizing impossible sans stop")
        return RiskDecision(
            intent_id=proposal.proposal_id,
            approved=not reasons,
            reasons=reasons,
            adjustments=adjustments,
            working_capital=wc,
            max_trade_risk=cap,
            requested_risk_amount=requested,
            risk_amount=sized.actual_risk if sized else 0.0,
            risk_pct_of_working_capital=(sized.actual_risk / wc * 100) if sized and wc > 0 else 0.0,
            risk_pct_of_equity=(sized.actual_risk / equity * 100) if sized and equity > 0 else 0.0,
            volume=sized.volume if sized else 0.0,
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            loss_per_lot=sized.loss_per_lot if sized else 0.0,
        )

    def plan_position_action(self, proposal: ActionProposal, context: PositionActionContext) -> RiskDecision:
        """Effect-free Lot F plan. The legacy runtime gate remains closed until execution is ready."""
        return evaluate_position_action(proposal, context)

    def __init__(
        self,
        rules: RiskRules,
        sizer: PositionSizer | None = None,
        supported_entry_types: frozenset[EntryType] = frozenset({EntryType.MARKET}),
    ) -> None:
        self.rules = rules
        self.sizer = sizer or PositionSizer()
        self.supported_entry_types = supported_entry_types

    def evaluate_position_action(
        self, proposal: ActionProposal, *, mode: RunMode, account_type: AccountType,
        positions: list[Position], kill_switch_active: bool, run_state: RunState,
    ) -> RiskDecision:
        """Porte déterministe conservatrice. HOLD seul est sans effet broker dans ce lot."""
        reasons: list[RiskReason] = []
        pos = next((p for p in positions if p.ticket == proposal.parameters.position_ticket), None)
        if pos is None or pos.symbol != proposal.symbol:
            reasons.append(RiskReason(code=RejectCode.POSITION_NOT_OWNED,
                                      message="position absente ou non possédée par ce run"))
        if kill_switch_active or run_state not in (RunState.RUNNING, RunState.TARGET_REACHED):
            reasons.append(RiskReason(code=RejectCode.KILL_SWITCH,
                                      message="gestion Brain bloquée par état du run ou kill switch"))
        if mode is not RunMode.DEMO or account_type is not AccountType.DEMO:
            reasons.append(RiskReason(code=RejectCode.MODE_SAFETY,
                                      message="gestion de position broker autorisée en DEMO uniquement"))
        if proposal.action is not Action.HOLD:
            reasons.append(RiskReason(code=RejectCode.POSITION_ACTION_UNSUPPORTED,
                                      message="action de gestion non activée sans capacités broker et contrat de risque"))
        return RiskDecision(intent_id=proposal.proposal_id, approved=not reasons, reasons=reasons)

    def evaluate(self, intent: TradeIntent, ctx: RiskContext) -> RiskDecision:  # noqa: C901 (liste de contrôles)
        r = self.rules
        reasons: list[RiskReason] = []
        adjustments: list[str] = []

        def reject(code: RejectCode, msg: str) -> None:
            reasons.append(RiskReason(code=code, message=msg))

        acct, spec, wd = ctx.account, ctx.spec, ctx.watchdog

        # ---- 1. garde-fous globaux ------------------------------------------------------
        if not ctx.session_allowed:
            reject(RejectCode.SESSION_CLOSED, "hors session configurée")
        if not ctx.can_open_position:
            reject(RejectCode.MODE_SAFETY, "adapter sans capacité d’ouverture")
        if ctx.trading_mode != "demo":
            reject(RejectCode.TRADING_MODE, f"trading mode '{ctx.trading_mode}' interdit : DEMO uniquement")
        if acct.account_type is AccountType.LIVE:
            reject(RejectCode.LIVE_ACCOUNT, "LIVE ACCOUNT DETECTED — EXECUTION BLOCKED")
        elif acct.account_type is not AccountType.DEMO:
            reject(RejectCode.ACCOUNT_UNKNOWN, "ACCOUNT TYPE UNKNOWN — EXECUTION BLOCKED")
        if ctx.kill_switch_active:
            reject(RejectCode.KILL_SWITCH, "kill switch actif : aucune nouvelle exécution")
        if not wd.can_open_new_positions:
            why = "; ".join(wd.blocked_reasons) or "challenge bloqué"
            reject(RejectCode.CHALLENGE_BLOCKED, f"challenge watchdog : {why}")
        if not acct.trade_allowed:
            reject(
                RejectCode.TRADE_NOT_ALLOWED,
                "trading non autorisé : bouton « Algo Trading » du terminal MT5 désactivé ou compte en lecture seule",
            )
        if intent.run_id != wd.run_id:
            reject(RejectCode.RUN_MISMATCH, f"intent du run {intent.run_id} soumis au run {wd.run_id}")

        # ---- 2. validité de l'intention ---------------------------------------------------
        if ctx.now >= intent.expires_at:
            reject(RejectCode.EXPIRED, "signal expiré")
        if intent.stop_loss is None:
            reject(RejectCode.NO_STOP_LOSS, "stop loss obligatoire : NO SL = REJECTED")
        if intent.instrument != spec.symbol or intent.instrument != ctx.tick.symbol:
            reject(RejectCode.INSTRUMENT_MISMATCH, "instrument de l'intent différent de la spec/tick fournis")
        if intent.entry_type not in self.supported_entry_types:
            reject(RejectCode.ENTRY_TYPE_UNSUPPORTED, f"type d'entrée {intent.entry_type} non supporté")
        if not spec.is_tradable or not (
            (intent.side is Side.BUY and spec.trade_mode is not SymbolTradeMode.SHORT_ONLY)
            or (intent.side is Side.SELL and spec.trade_mode is not SymbolTradeMode.LONG_ONLY)
        ):
            reject(
                RejectCode.NOT_TRADABLE,
                f"instrument {spec.symbol} non négociable dans ce sens ({spec.trade_mode})",
            )

        live = ctx.tick.ask if intent.side is Side.BUY else ctx.tick.bid
        entry = live if intent.entry_type is EntryType.MARKET else intent.entry
        sl, tp = intent.stop_loss, intent.take_profit
        sl_dist: float | None = None

        if entry is not None and sl is not None:
            sl_dist = abs(entry - sl)
            sl_ok = sl < entry if intent.side is Side.BUY else sl > entry
            if not sl_ok:
                reject(
                    RejectCode.BAD_GEOMETRY, f"SL {sl} du mauvais côté de l'entrée {entry} pour {intent.side}"
                )
            if tp is not None:
                tp_ok = tp > entry if intent.side is Side.BUY else tp < entry
                if not tp_ok:
                    reject(
                        RejectCode.BAD_GEOMETRY,
                        f"TP {tp} du mauvais côté de l'entrée {entry} pour {intent.side}",
                    )
                elif sl_ok and r.min_risk_reward > 0 and abs(tp - entry) / sl_dist < r.min_risk_reward:
                    reject(RejectCode.RISK_REWARD, f"ratio gain/risque < {r.min_risk_reward}")
            min_dist = spec.stops_level * spec.point
            if sl_dist < min_dist or (tp is not None and abs(tp - entry) < min_dist):
                reject(
                    RejectCode.STOPS_TOO_CLOSE,
                    f"SL/TP plus proches que la distance minimale broker ({min_dist:g})",
                )
            if sl_dist <= 0:
                reject(RejectCode.BAD_GEOMETRY, "distance SL nulle")
            if intent.entry_type is EntryType.MARKET and intent.entry is not None and sl_dist > 0:
                dev = abs(intent.entry - live)
                if dev > r.max_entry_deviation_to_sl_ratio * sl_dist:
                    reject(
                        RejectCode.PRICE_MOVED,
                        f"prix live {live} trop éloigné de l'entrée annoncée {intent.entry} (écart {dev:g})",
                    )

        spread = ctx.tick.spread
        if sl_dist and sl_dist > 0 and spread > r.max_spread_to_sl_ratio * sl_dist:
            reject(
                RejectCode.SPREAD_TOO_WIDE,
                f"spread {spread:g} > {r.max_spread_to_sl_ratio:.0%} de la distance SL",
            )
        if r.max_spread_points is not None and spec.point > 0 and spread / spec.point > r.max_spread_points:
            reject(
                RejectCode.SPREAD_TOO_WIDE,
                f"spread {spread / spec.point:.1f} pts > max {r.max_spread_points}",
            )

        # ---- 3. enveloppe de travail -----------------------------------------------------
        wc = sizing.working_capital(acct.equity, r.working_capital_pct)
        cap = sizing.max_trade_risk(wc, r.max_trade_risk_pct_of_working_capital)
        requested = wc * intent.requested_risk_pct_of_working_capital / 100
        risk_limit = min(requested, cap)
        limiter: tuple[RejectCode, str] | None = None
        if requested > cap + _EPS:
            if r.over_cap_policy == "reject":
                reject(
                    RejectCode.RISK_EXCEEDS_CAP,
                    f"risque demandé {requested:.2f} > plafond par trade {cap:.2f} "
                    f"({r.max_trade_risk_pct_of_working_capital:g}% du capital de travail)",
                )
            else:
                adjustments.append(f"risque réduit au plafond {cap:.2f} (demandé {requested:.2f})")

        # ---- 4. portefeuille : positions, exposition, marge de manœuvre ------------------
        exposure = compute_exposure(ctx.positions, ctx.specs)
        if len(ctx.positions) >= r.max_open_positions:
            reject(RejectCode.MAX_POSITIONS, f"nombre maximal de positions atteint ({r.max_open_positions})")
        if exposure.unprotected_tickets:
            reject(RejectCode.UNPROTECTED_POSITION, f"position(s) sans SL : {exposure.unprotected_tickets}")
        if exposure.unknown_symbols:
            reject(
                RejectCode.EXPOSURE_UNKNOWN,
                f"exposition incalculable (spec manquante) : {exposure.unknown_symbols}",
            )
        if not r.allow_hedging and any(
            p.symbol == intent.instrument and p.side is not intent.side for p in ctx.positions
        ):
            reject(
                RejectCode.HEDGING,
                f"position inverse déjà ouverte sur {intent.instrument} (hedging interdit)",
            )

        def tighten(code: RejectCode, msg: str, room: float) -> None:
            nonlocal risk_limit, limiter
            if room <= _EPS:
                reject(code, msg)
            elif room < risk_limit - _EPS:
                risk_limit = room
                limiter = (code, msg)
                adjustments.append(f"risque réduit à {room:.2f} : {msg}")

        buffer = wd.baseline_balance * r.headroom_buffer_pct_of_baseline / 100
        open_risk = exposure.total_open_risk
        tighten(
            RejectCode.DAILY_HEADROOM,
            "remaining daily loss headroom insufficient",
            wd.daily_headroom - open_risk - buffer,
        )
        tighten(
            RejectCode.TOTAL_HEADROOM,
            "remaining total loss headroom insufficient",
            wd.total_headroom - open_risk - buffer,
        )
        tighten(
            RejectCode.OPEN_RISK_CAP,
            f"open risk would exceed {r.max_total_open_risk_pct_of_wc:g}% of working capital",
            wc * r.max_total_open_risk_pct_of_wc / 100 - open_risk,
        )

        if not exposure.unknown_symbols:
            ccy_limit = wc * r.max_currency_net_risk_pct_of_wc / 100
            for ccy, leg_sign in (
                (spec.currency_base, intent.side.sign),
                (spec.currency_profit, -intent.side.sign),
            ):
                current = exposure.currency_net_risk.get(ccy, 0.0)
                # marge disponible dans le sens de la nouvelle jambe
                room = ccy_limit - current * leg_sign
                tighten(
                    RejectCode.CURRENCY_EXPOSURE,
                    f"correlated {ccy} exposure exceeds threshold "
                    f"(net {current:+.0f} vs limite {ccy_limit:.0f} ; sens {'long' if leg_sign > 0 else 'court'})",
                    room,
                )

        if ctx.correlations is not None:
            for p in ctx.positions:
                c = ctx.correlations.get(intent.instrument, p.symbol)
                if c is None or p.symbol == intent.instrument:
                    continue
                eff = c * intent.side.sign * p.side.sign  # >0 : les deux trades parient dans le même sens
                if eff > r.max_correlation:
                    reject(
                        RejectCode.CORRELATION,
                        f"correlated exposure: {intent.instrument} {intent.side} vs {p.symbol} {p.side} "
                        f"(corrélation effective {eff:.2f} > {r.max_correlation})",
                    )

        # ---- 5. dimensionnement ---------------------------------------------------------
        volume = 0.0
        actual_risk = 0.0
        lpl = 0.0
        required_margin: float | None = None
        if entry is not None and sl is not None and sl_dist and sl_dist > 0 and risk_limit > _EPS:
            res = self.sizer.size(spec, entry, sl, risk_limit)
            lpl = res.loss_per_lot
            if res.volume <= 0:
                if limiter is not None:
                    reject(limiter[0], limiter[1])
                reject(
                    RejectCode.VOLUME_BELOW_MIN,
                    f"volume minimum {spec.volume_min:g} lot risquerait {res.min_volume_risk:.2f} "
                    f"> risque autorisé {risk_limit:.2f}"
                    if res.min_volume_risk
                    else (res.reason or "sizing impossible"),
                )
            else:
                volume, actual_risk = res.volume, res.actual_risk
                if actual_risk > cap + 1e-6:  # garde-fou ultime (ne devrait jamais se produire)
                    reject(RejectCode.SIZING, "risque calculé supérieur au plafond par trade")
                if ctx.margin_per_lot is not None:
                    required_margin = ctx.margin_per_lot * volume
                    if required_margin > acct.free_margin * r.max_margin_usage_pct / 100:
                        reject(
                            RejectCode.MARGIN,
                            f"marge requise {required_margin:.2f} > {r.max_margin_usage_pct:g}% de la marge libre "
                            f"({acct.free_margin:.2f})",
                        )

        approved = not reasons and volume > 0
        decision = RiskDecision(
            intent_id=intent.intent_id,
            approved=approved,
            reasons=reasons,
            adjustments=adjustments if approved else adjustments,
            working_capital=wc,
            max_trade_risk=cap,
            requested_risk_amount=requested,
            risk_amount=actual_risk if approved else 0.0,
            risk_pct_of_working_capital=(actual_risk / wc * 100) if approved and wc else 0.0,
            risk_pct_of_equity=(actual_risk / acct.equity * 100) if approved and acct.equity else 0.0,
            volume=volume if approved else 0.0,
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            loss_per_lot=lpl,
            required_margin=required_margin,
        )
        if approved:
            decision.token = issue_open_token(intent.run_id, intent.intent_id, intent.instrument, volume)
        return decision


__all__ = ["RiskEngine", "currency_legs"]
