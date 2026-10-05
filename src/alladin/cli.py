"""CLI ALLADIN : `python -m alladin <commande>`. Aucune commande ne trade sans confirmation explicite."""

from __future__ import annotations

import contextlib
import sys
from datetime import timedelta
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from alladin.brokers.base import BrokerAdapter, block_message
from alladin.brokers.mt5 import MT5Broker
from alladin.challenge.profiles import list_profiles, load_profile
from alladin.core.config import Settings, get_settings
from alladin.core.enums import AccountType, EntryType, JafarMode, MarketRegime, RunMode, RunState, Side
from alladin.core.errors import AlladinError, BrokerConnectionError
from alladin.core.logging import setup_logging
from alladin.core.models import TradeIntent
from alladin.core.workspace import WorkspaceId
from alladin.market.scanner import MarketScanner
from alladin.market.universe import MarketUniverse
from alladin.orchestration.bootstrap import Components, build_services, make_agent, make_broker
from alladin.report import money, status_block
from alladin.risk import sizing
from alladin.risk.exposure import compute_exposure

for _stream in (sys.stdout, sys.stderr):  # Windows : évite les UnicodeEncodeError (pipes cp1252)
    with contextlib.suppress(AttributeError, ValueError, OSError):
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="ALLADIN — laboratoire de trading Forex (MT5 DEMO uniquement).",
)
mt5_app = typer.Typer(no_args_is_help=True, help="Diagnostic et tests MetaTrader 5.")
market_app = typer.Typer(no_args_is_help=True, help="Marché : univers et scanner.")
challenge_app = typer.Typer(no_args_is_help=True, help="Challenge : état du run.")
runs_app = typer.Typer(no_args_is_help=True, help="Gestion des runs (RUN-001, RUN-002...).")
positions_app = typer.Typer(no_args_is_help=True, help="Positions ALLADIN.")
replay_app = typer.Typer(no_args_is_help=True, help="Replay read-only des décisions.")
archive_app = typer.Typer(no_args_is_help=True, help="Archive de barres OHLCV.")
app.add_typer(mt5_app, name="mt5")
app.add_typer(market_app, name="market")
app.add_typer(challenge_app, name="challenge")
app.add_typer(runs_app, name="runs")
app.add_typer(positions_app, name="positions")
app.add_typer(replay_app, name="replay")
app.add_typer(archive_app, name="archive")
jafar_app = typer.Typer(no_args_is_help=True, help="Jafar — crypto OBSERVE / PAPER / TESTNET (jamais d'ordre production direct).")
app.add_typer(jafar_app, name="jafar")
outcomes_app = typer.Typer(no_args_is_help=True, help="Résultats et rewards hors exécution, aucun ordre.")
app.add_typer(outcomes_app, name="outcomes")

console = Console(markup=False, highlight=False)
BrokerOpt = Annotated[str, typer.Option("--broker", help="mt5 | mock")]
RunOpt = Annotated[str | None, typer.Option("--run", help="ex. RUN-001 (défaut : dernier run actif)")]


def out(msg: str = "") -> None:
    console.print(msg, soft_wrap=True)


def die(msg: str, code: int = 1) -> typer.Exit:
    out(msg)
    return typer.Exit(code)


MT5_HELP = """
CE QUI MANQUE : le terminal MetaTrader 5 est ouvert mais n'est connecté à AUCUN compte de trading.
ACTION À EFFECTUER :
  1. Dans MetaTrader 5 : Fichier > Se connecter au compte de trading, puis choisir votre compte DEMO
     (ou Fichier > Ouvrir un compte > serveur du broker > « compte démo »). Attendre que la barre
     d'état en bas à droite affiche des ko/s (connecté).
  2. (Option) À la place : renseigner MT5_LOGIN, MT5_PASSWORD, MT5_SERVER d'un compte DEMO dans .env.
  3. Vérifier que « Trading algo / Algo Trading » est activé (bouton en haut de MT5).
COMMANDE À RELANCER : python -m alladin mt5 status"""


def _connect(broker: BrokerAdapter) -> None:
    try:
        broker.connect()
    except BrokerConnectionError as exc:
        out("Terminal: NOT CONNECTED")
        out(f"Raison: {exc}")
        if broker.name == "MT5":
            out(MT5_HELP)
        raise typer.Exit(1) from exc


def _components(
    settings: Settings,
    kind: str,
    *,
    run_id: str | None = None,
    create: bool = False,
    profile: str | None = None,
    db_url: str | None = None,
) -> Components:
    broker = make_broker(kind, settings)
    _connect(broker)
    try:
        comps = build_services(
            settings, broker, run_id=run_id, create_run=create, profile_id=profile, db_url=db_url
        )
    except AlladinError as exc:
        raise die(f"Erreur: {exc}") from exc
    if comps is None:
        raise die("Aucun run actif. Créer un run :  python -m alladin runs new --broker " + kind, 2)
    return comps


# ---------------------------------------------------------------------------- demo


@app.command()
def demo(
    scenario: Annotated[str, typer.Option(help="basic | fail | pass")] = "basic",
    db: Annotated[
        str | None,
        typer.Option(help="Fichier SQLite pour conserver le journal de la démo (défaut : mémoire)"),
    ] = None,
) -> None:
    """Banc d'essai simulé (MockBroker + MockAgent) : Risk Engine, watchdog, FAILED, PASSED."""
    from alladin.demo import run_demo

    if scenario not in ("basic", "fail", "pass"):
        raise die("scénario : basic | fail | pass", 2)
    run_demo(scenario, out=out, db_url=f"sqlite:///{db}" if db else "sqlite://")


# ---------------------------------------------------------------------------- mt5


@mt5_app.command("status")
def mt5_status() -> None:
    """Connexion MT5 : terminal, compte DEMO/LIVE, solde, symboles découverts."""
    settings = get_settings()
    broker = make_broker("mt5", settings)
    out("ALLADIN — MT5 CONNECTION\n")
    _connect(broker)
    assert isinstance(broker, MT5Broker)
    try:
        term = broker.terminal_status()
        acct = broker.account_info()
        specs = broker.list_symbols()
        positions = broker.positions()
    except AlladinError as exc:
        raise die(f"Erreur pendant la lecture du compte : {exc}") from exc
    finally:
        pass
    profile = load_profile(settings.default_profile, settings.profiles_dir)
    uni = MarketUniverse(broker, profile.universe).discover()
    alladin_pos = [p for p in positions if p.comment.startswith("ALD-")]
    mode = acct.account_type.value
    out("Terminal: CONNECTED")
    out(f"Terminal build: {term['build']}  ({term['company']})")
    out(
        f"Algo Trading (terminal): {'ACTIVÉ' if term['trade_allowed'] else 'DÉSACTIVÉ — les ordres seront refusés'}"
    )
    out(f"Trading autorisé (compte): {'OUI' if acct.trade_allowed else 'NON'}")
    out(f"Décalage horloge serveur/UTC: {broker.server_utc_offset_hours:+g} h ({broker.offset_source})")
    out(f"Account: {acct.login_masked}")
    out(f"Mode: {mode}")
    out(f"Server: {acct.server}")
    out(f"Currency: {acct.currency}")
    out(f"Leverage: 1:{acct.leverage}")
    out("")
    out(f"Balance: {money(acct.balance, acct.currency)}")
    out(f"Equity: {money(acct.equity, acct.currency)}")
    out(f"Margin (utilisée): {money(acct.margin, acct.currency)}")
    out(f"Free Margin: {money(acct.free_margin, acct.currency)}")
    out(f"Floating P&L: {money(acct.floating_pnl, acct.currency)}")
    out("")
    out(f"Symbols discovered: {len(specs)}  (dans l'univers ALLADIN : {len(uni.members)})")
    for cat, n in uni.by_category.items():
        out(f"    {cat}: {n}")
    out(
        f"Open positions: {len(positions)}  (ALLADIN: {len(alladin_pos)}, autres: {len(positions) - len(alladin_pos)})"
    )
    out("")
    if acct.account_type is AccountType.DEMO:
        out(
            "ALLADIN STATUS: READY"
            + ("" if term["trade_allowed"] else " (lecture seule : Algo Trading désactivé)")
        )
        if not term["trade_allowed"]:
            out(ALGO_MSG)
    else:
        out(block_message(acct.account_type))
        out("ALLADIN STATUS: EXECUTION BLOCKED (lecture seule)")
        raise typer.Exit(3)
    broker.disconnect()


ALGO_MSG = "Activez Algo Trading dans MetaTrader 5 puis relancez cette commande."


def _require_algo_trading(broker: MT5Broker, account_trade_allowed: bool) -> None:
    """ARRÊT avant tout order_send si Algo Trading est désactivé. Aucun contournement."""
    term = broker.terminal_status()
    if not term["trade_allowed"] or term["tradeapi_disabled"] or not account_trade_allowed:
        out("\nALGO TRADING DÉSACTIVÉ — aucun ordre ne sera envoyé.")
        if term["tradeapi_disabled"]:
            out(
                "(L'API de trading est désactivée dans les options du terminal : Outils > Options > Expert Advisors.)"
            )
        out(ALGO_MSG)
        raise typer.Exit(6)


@mt5_app.command("test-order")
def mt5_test_order(
    symbol: Annotated[str, typer.Option(help="Instrument de test (explicite)")] = "EURUSD",
    side: Annotated[str, typer.Option(help="BUY | SELL")] = "BUY",
    sl_pips: Annotated[float, typer.Option(help="Distance du stop loss en pips")] = 20.0,
    rr: Annotated[float, typer.Option(help="Ratio gain/risque du TP")] = 2.0,
    risk_pct: Annotated[
        float | None,
        typer.Option(help="% du capital de travail (défaut : le plus petit possible ≈ volume minimum)"),
    ] = None,
    run: RunOpt = None,
) -> None:
    """Ordre DEMO de TEST D'INTÉGRATION (run SYSTEM-TEST-nnn, jamais un RUN officiel), via tout le pipeline."""
    settings = get_settings()
    broker = make_broker("mt5", settings)
    out("ALLADIN — MT5 TEST ORDER (test d'intégration, pas une expérience)\n")
    _connect(broker)
    assert isinstance(broker, MT5Broker)
    acct = broker.account_info()
    out(f"Account: {acct.login_masked} | {acct.server} | {acct.currency} | Mode: {acct.account_type.value}")
    out(
        f"Balance {money(acct.balance, acct.currency)} | Equity {money(acct.equity, acct.currency)} | Free margin {money(acct.free_margin, acct.currency)}"
    )
    if acct.account_type is not AccountType.DEMO:
        out("\n" + block_message(acct.account_type))
        raise typer.Exit(3)
    _require_algo_trading(broker, acct.trade_allowed)
    try:
        side_e = Side(side.upper())
    except ValueError as exc:
        raise die("--side : BUY ou SELL", 2) from exc

    # run : SYSTEM-TEST (jamais RUN-00x officiel) ; le dernier ouvert, sinon création avec confirmation
    comps = build_services(settings, broker, run_id=run, run_kind="SYSTEM-TEST")
    if comps is None:
        if not typer.confirm(
            "\nAucun run SYSTEM-TEST actif. En créer un (n'affecte pas les RUN officiels) ?", default=False
        ):
            raise die("Annulé : aucun run.", 2)
        comps = build_services(settings, broker, create_run=True, run_kind="SYSTEM-TEST")
        assert comps is not None
    if comps.run.watchdog.run_state in (RunState.CREATED, RunState.READY):
        comps.manager.start(comps.run, acct)
    out(f"Run: {comps.run.run_id} ({comps.run.watchdog.run_state.value})")

    # instrument de test : nom exact, sinon variantes à suffixe du broker (ex. EURUSD.m)
    spec = broker.symbol_spec(symbol)
    if spec is None:
        alt = [s.symbol for s in broker.list_symbols() if s.symbol.upper().startswith(symbol.upper())]
        raise die(
            f"Instrument '{symbol}' introuvable chez ce broker."
            + (f" Variantes : {', '.join(alt[:8])}" if alt else ""),
            2,
        )
    symbol = spec.symbol

    def build_intent() -> TradeIntent:
        tick = broker.tick(symbol)
        if tick is None:
            raise die(f"Aucun tick pour {symbol} (marché fermé ?)", 2)
        d = side_e.sign
        pip = spec.point * 10
        px = tick.ask if side_e is Side.BUY else tick.bid
        sl = round(px - d * sl_pips * pip, spec.digits)
        tp = round(px + d * sl_pips * rr * pip, spec.digits)
        wc = sizing.working_capital(acct.equity, comps.profile.risk.working_capital_pct)
        if risk_pct is not None:
            pct = risk_pct
        else:  # juste assez de risque pour le volume minimum du broker
            lpl = sizing.loss_per_lot(spec, px, sl)
            pct = max(0.01, round(lpl * spec.volume_min * 1.05 / wc * 100, 4)) if wc > 0 else 0.01
        now = broker.now()
        return TradeIntent(
            run_id=comps.run.run_id,
            agent="manual-test",
            instrument=symbol,
            side=side_e,
            strategy_id="TEST-00",
            strategy_version="0.0.0",
            market_regime=MarketRegime.UNKNOWN,
            entry_type=EntryType.MARKET,
            entry=px,
            stop_loss=sl,
            take_profit=tp,
            requested_risk_pct_of_working_capital=pct,
            confidence=0.5,
            reason="test-order manuel (intégration)",
            created_at=now,
            expires_at=now + timedelta(minutes=5),
            sources=["cli:mt5 test-order"],
        )

    # 1. pré-évaluation réelle (DEMO, watchdog, RiskEngine, sizing, marge broker), sans rien envoyer
    pre = comps.execution.submit(build_intent(), dry_run=True)
    it = pre.intent
    tick = broker.tick(symbol)
    assert tick is not None
    out("\n--- RÉCAPITULATIF (rien n'est encore envoyé) ---")
    out(
        f"instrument: {it.instrument} | side: {it.side.value} | bid: {tick.bid} | ask: {tick.ask} | spread: {tick.spread:.{spec.digits}f} ({tick.spread / spec.point:.1f} pts)"
    )
    if not pre.decision or not pre.decision.approved:
        out(f"entry(ref): {it.entry} | SL: {it.stop_loss} | TP: {it.take_profit}")
        out(f"RISK ENGINE: {pre.status.value}")
        for m in pre.messages:
            out(f"  - {m}")
        raise typer.Exit(4)
    d = pre.decision
    assert d.entry_price is not None and d.stop_loss is not None and d.take_profit is not None
    sl_dist = abs(d.entry_price - d.stop_loss)
    wd_rep = comps.run.watchdog.report(broker.account_info(), broker.now())
    mine = comps.execution.my_positions()
    specs = {p.symbol: s for p in mine if (s := broker.symbol_spec(p.symbol))}
    expo = compute_exposure(mine, specs)
    ccy = acct.currency
    out(f"entry: {d.entry_price} | SL: {d.stop_loss} | TP: {d.take_profit}")
    out(
        f"distance SL: {sl_dist:.{spec.digits}f} ({sl_dist / (spec.point * 10):.1f} pips) | RR: {abs(d.take_profit - d.entry_price) / sl_dist:.2f}"
    )
    out(
        f"risk requested: {it.requested_risk_pct_of_working_capital:g}% du capital de travail = {money(d.requested_risk_amount, ccy)}"
    )
    out(
        f"risk amount (approuvé): {money(d.risk_amount, ccy)} = {d.risk_pct_of_equity:.3f}% equity = {d.risk_pct_of_working_capital:.2f}% du capital de travail"
    )
    out(f"working capital: {money(d.working_capital, ccy)} | max trade risk: {money(d.max_trade_risk, ccy)}")
    out(f"volume calculé: {d.volume:g} lot(s) (PositionSizer ; perte/lot au SL {money(d.loss_per_lot, ccy)})")
    if d.required_margin is not None:
        out(f"margin estimated: {money(d.required_margin, ccy)} (marge libre {money(acct.free_margin, ccy)})")
    out(
        f"FTMO headroom: journalier {money(wd_rep.daily_headroom, ccy)} | total {money(wd_rep.total_headroom, ccy)}"
    )
    nets = {k: round(v) for k, v in expo.currency_net_risk.items()} or "aucune"
    out(
        f"current exposure: {len(mine)} position(s) ALLADIN, risque ouvert {money(expo.total_open_risk, ccy)}, devises {nets}"
    )
    out("RISK ENGINE: APPROVED")
    for a in d.adjustments:
        out(f"  ajustement: {a}")
    out("\nCet ordre sera envoyé sur le compte DEMO ci-dessus.")

    # 2. confirmation explicite : il faut TAPER le mot EXECUTE
    answer = typer.prompt(
        "Tapez EXECUTE pour envoyer l'ordre (autre chose = annuler)", default="", show_default=False
    )
    if answer.strip() != "EXECUTE":
        out("Annulé : aucun ordre envoyé.")
        raise typer.Exit(0)

    # 3. pipeline complet refait avec des prix frais (le marché a pu bouger)
    _require_algo_trading(broker, broker.account_info().trade_allowed)
    res = comps.execution.submit(build_intent())
    out("")
    if res.precheck:
        out(
            f"MT5 order_check: ok={res.precheck.ok} retcode={res.precheck.retcode} marge={res.precheck.margin}"
        )
    if res.executed and res.order and res.decision:
        o, dd = res.order, res.decision
        # vérification INDÉPENDANTE chez MT5 : positions_get
        live = next((p for p in broker.positions() if p.ticket == res.position_ticket), None)
        if live is None:
            out(
                "ATTENTION : MT5 a accepté l'ordre mais positions_get ne retrouve pas la position. NON CONFIRMÉ."
            )
            raise typer.Exit(5)
        out("ORDER ACCEPTED — position CONFIRMÉE par MT5 (positions_get)")
        out(
            f"retcode: {o.retcode} ({o.retcode_name}) | order: {o.order} | deal: {o.deal} | ticket/position: {live.ticket}"
        )
        out(f"symbol: {live.symbol} | side: {live.side.value} | volume: {live.volume:g}")
        out(
            f"entry demandé: {o.requested_price} | prix exécuté: {o.executed_price} (position: {live.price_open}) | slippage: {o.slippage}"
        )
        out(f"SL: {live.sl} | TP: {live.tp} | magic: {live.magic} | comment: {live.comment}")
        out(f"risk amount: {money(dd.risk_amount, ccy)} | risk %: {dd.risk_pct_of_equity:.3f}% equity")
        out(f"journalisé: trade {res.trade_id} dans {comps.run.run_id}")
        out(f"Suite : python -m alladin challenge status --run {comps.run.run_id}")
    else:
        out("ORDER REJECTED")
        out(f"status: {res.status.value}")
        for m in res.messages:
            out(f"  - {m}")
        if res.order:
            out(f"retcode: {res.order.retcode} ({res.order.retcode_name})")
        raise typer.Exit(5)


@market_app.command("scan")
def market_scan(
    broker_kind: BrokerOpt = "mt5",
    limit: Annotated[int | None, typer.Option(help="Taille de la shortlist")] = None,
) -> None:
    """Scanne les instruments réellement disponibles chez le broker (aucun ordre)."""
    settings = get_settings()
    broker = make_broker(broker_kind, settings)
    _connect(broker)
    profile = load_profile(settings.default_profile, settings.profiles_dir)
    universe = MarketUniverse(broker, profile.universe)
    uni = universe.discover()
    out(
        f"Univers: {len(uni.members)} instruments retenus sur {uni.total_discovered} découverts chez {broker.name}"
    )
    for cat, n in uni.by_category.items():
        out(f"  {cat}: {n}")
    rep = MarketScanner(broker, universe, profile.universe).scan(limit=limit)
    out(f"Analysés: {rep.analysed} | Rejetés: {len(rep.rejected)} | Régimes: {rep.regime_counts}")
    table = Table(title="Shortlist (aucun ordre n'est envoyé)")
    for col in ("#", "Symbole", "Catégorie", "Régime", "Score", "Biais", "Spread/ATR", "Sessions"):
        table.add_column(col)
    for i, c in enumerate(rep.candidates, 1):
        table.add_row(
            str(i),
            c.symbol,
            c.category.value,
            c.regime.value,
            f"{c.score:.3f}",
            c.bias.value if c.bias else "-",
            f"{c.spread_atr_ratio:.3f}",
            c.session,
        )
    console.print(table)
    for note in rep.notes:
        out(f"Note: {note}")
    reasons: dict[str, int] = {}
    for rs in rep.rejected.values():
        key = rs[0].split("(")[0].split(":")[0][:60]
        reasons[key] = reasons.get(key, 0) + 1
    if reasons:
        out("Rejets (raisons):")
        for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])[:8]:
            out(f"  {v:>4} × {k}")


# ---------------------------------------------------------------------------- challenge & runs


def _print_run_positions_and_journal(comps: Components) -> None:
    rid = comps.run.run_id
    mine = comps.execution.my_positions()
    trades = comps.repo.trades_for_run(rid)
    out("")
    out(f"Positions ALLADIN ouvertes chez MT5 ({rid}): {len(mine)}")
    by_ticket = {t.ticket: t for t in trades}
    for p in mine:
        t = by_ticket.get(p.ticket)
        known = (
            f"journal: trade {t.trade_id} [{t.strategy_id}@{t.strategy_version}]"
            if t
            else "JOURNAL: INCONNUE (lancer `sync`)"
        )
        out(
            f"  #{p.ticket} {p.symbol} {p.side.value} {p.volume:g} @ {p.price_open} SL {p.sl} TP {p.tp} "
            f"P&L {p.profit:+.2f} magic {p.magic} | {known}"
        )
    closed = [t for t in trades if t.status == "CLOSED"]
    out(f"Trades journalisés: {len(trades)} (ouverts {len(trades) - len(closed)}, clôturés {len(closed)})")
    ok, msg = comps.repo.verify_chain(rid)
    events = comps.repo.events(rid)
    out(f"Journal: {len(events)} événements | intégrité: {'OK' if ok else 'ALTÉRÉ'} ({msg})")
    for e in events[-5:]:
        out(f"  {e.ts:%H:%M:%S} {e.type}")


@challenge_app.command("status")
def challenge_status(broker_kind: BrokerOpt = "mt5", run: RunOpt = None) -> None:
    """Equity, capital de travail, risque max, drawdowns, objectif, phase et état du run."""
    settings = get_settings()
    broker = make_broker(broker_kind, settings)
    _connect(broker)
    comps = build_services(settings, broker, run_id=run)
    if comps is None:
        out("Aucun run actif : aperçu calculé depuis le profil et le compte (aucun état enregistré).")
        out("Créer un run :  python -m alladin runs new --broker " + broker_kind + "\n")
        profile = load_profile(settings.default_profile, settings.profiles_dir)
        from alladin.challenge.watchdog import ChallengeWatchdog

        acct = broker.account_info()
        wd = ChallengeWatchdog.create(profile, "(aperçu)", acct.balance)
        rep = wd.update(acct, broker.now())
        risk, label = profile.risk, "(aperçu)"
    else:
        acct = comps.broker.account_info()
        comps.monitor.sync()  # met aussi le watchdog à jour avec l'equity réelle
        rep = comps.run.watchdog.report(acct, broker.now())
        risk, label = comps.profile.risk, comps.run.run_id
    out(
        status_block(
            run_id=label,
            mode="demo" if acct.account_type is AccountType.DEMO else acct.account_type.value,
            account=acct,
            report=rep,
            working_capital_pct=risk.working_capital_pct,
            max_trade_risk_pct=risk.max_trade_risk_pct_of_working_capital,
            universe="voir `market scan`",
            broker=broker.name,
            agent=settings.agent,
            title="ALLADIN — CHALLENGE STATUS",
        )
    )
    if comps is not None:
        _print_run_positions_and_journal(comps)


@runs_app.command("new")
def runs_new(
    broker_kind: BrokerOpt = "mt5",
    profile: Annotated[
        str | None, typer.Option(help="Profil de challenge (défaut : DEFAULT_PROFILE)")
    ] = None,
    system_test: Annotated[
        bool, typer.Option("--system-test", help="Crée un run SYSTEM-TEST-nnn (intégration technique)")
    ] = False,
) -> None:
    """Crée un nouveau run (expérience indépendante) ; les anciens runs ne sont jamais modifiés."""
    settings = get_settings()
    broker = make_broker(broker_kind, settings)
    _connect(broker)
    acct = broker.account_info()
    if acct.account_type is not AccountType.DEMO:
        raise die(block_message(acct.account_type), 3)
    comps = build_services(
        settings,
        broker,
        create_run=True,
        profile_id=profile,
        run_kind="SYSTEM-TEST" if system_test else "RUN",
    )
    assert comps is not None
    out(
        f"Run créé : {comps.run.run_id} | profil {comps.profile.id} | solde de départ {money(acct.balance, acct.currency)} | magic {comps.run.magic} | état {comps.run.watchdog.run_state.value}"
    )
    out(f"Profils disponibles : {', '.join(list_profiles(settings.profiles_dir))}")


@runs_app.command("list")
def runs_list(broker_kind: BrokerOpt = "mock") -> None:
    """Liste tous les runs enregistrés (lecture seule de la base)."""
    from alladin.journal.repository import JournalRepository

    repo = JournalRepository.from_url(get_settings().db_url)
    runs = repo.list_runs()
    if not runs:
        out("Aucun run.")
    for r in runs:
        out(
            f"{r.run_id}  {r.state:<15} phase {r.phase}  profil {r.profile_id}  broker {r.broker}  départ {r.initial_balance:,.0f}  créé {r.created_at:%Y-%m-%d %H:%M}"
        )


@runs_app.command("verify")
def runs_verify(run_id: Annotated[str, typer.Argument()]) -> None:
    """Vérifie la chaîne de hachage du journal d'un run."""
    from alladin.journal.repository import JournalRepository

    ok, msg = JournalRepository.from_url(get_settings().db_url).verify_chain(run_id)
    out(f"{run_id}: {'INTÈGRE' if ok else 'ALTÉRÉ'} — {msg}")
    raise typer.Exit(0 if ok else 1)


# ---------------------------------------------------------------------------- autonome


@app.command("sync")
def sync_cmd(
    broker_kind: BrokerOpt = "mt5",
    run: RunOpt = None,
    system_test: Annotated[bool, typer.Option("--system-test", help="Cibler le dernier SYSTEM-TEST")] = False,
) -> None:
    """Réconcilie MT5 <-> base <-> journal (comme au redémarrage). Ne ferme JAMAIS rien."""
    settings = get_settings()
    broker = make_broker(broker_kind, settings)
    _connect(broker)
    comps = build_services(settings, broker, run_id=run, run_kind="SYSTEM-TEST" if system_test else "RUN")
    if comps is None:
        raise die("Aucun run actif à réconcilier.", 2)
    rep = comps.monitor.reconcile()
    out(f"Run: {comps.run.run_id} ({comps.run.watchdog.run_state.value}) | magic {comps.run.magic}")
    out(
        f"Réconciliation: {rep.open_positions} position(s) ALLADIN reconnue(s) par magic+commentaire, "
        f"{len(rep.adopted)} adoptée(s), {len(rep.newly_closed)} clôturée(s) hors-ligne, "
        f"{rep.foreign_ignored} étrangère(s) ignorée(s), {len(rep.unresolved_closed)} en attente d'historique"
    )
    _print_run_positions_and_journal(comps)


@app.command("run")
def run_cmd(
    broker_kind: BrokerOpt = "mt5",
    agent: Annotated[str | None, typer.Option(help="mock | claude | codex (défaut : AGENT)")] = None,
    interval: Annotated[float, typer.Option(help="Secondes entre deux cycles")] = 300.0,
    cycles: Annotated[int | None, typer.Option(help="Nombre de cycles (défaut : illimité)")] = 1,
    mode: Annotated[
        str,
        typer.Option(
            help=(
                "OBSERVE (défaut) : scan+analyse, aucun order_send. "
                "PAPER : même pipeline + simulation interne. "
                "DEMO : order_send sur compte DEMO (confirmation requise)."
            )
        ),
    ] = "OBSERVE",
    run: RunOpt = None,
) -> None:
    """Mode autonome : MT5 -> univers -> scanner -> régime -> routeur -> agent -> Risk -> exécution.

    Par défaut en mode OBSERVE (lecture seule). Utiliser --mode DEMO pour trader sur le compte DEMO.
    """
    try:
        run_mode = RunMode(mode.upper())
    except ValueError as exc:
        raise die(f"--mode : OBSERVE | PAPER | DEMO (reçu '{mode}')", 2) from exc

    settings = get_settings()
    comps = _components(settings, broker_kind, run_id=run)
    acct = comps.broker.account_info()
    if acct.account_type is not AccountType.DEMO:
        raise die(block_message(acct.account_type), 3)
    if comps.run.watchdog.run_state in (RunState.CREATED, RunState.READY):
        comps.manager.start(comps.run, acct)

    if run_mode is RunMode.DEMO:
        assert isinstance(comps.broker, MT5Broker)
        _require_algo_trading(comps.broker, acct.trade_allowed)
        out(f"MODE DEMO — exécution réelle sur {acct.server} ({acct.login_masked}), run {comps.run.run_id}.")
        if (
            typer.prompt(
                f"Tapez le nom du run ({comps.run.run_id}) pour autoriser l'envoi d'ordres",
                default="",
                show_default=False,
            ).strip()
            != comps.run.run_id
        ):
            raise die("Annulé : aucun ordre ne sera envoyé.", 0)
    elif run_mode is RunMode.PAPER:
        out("MODE PAPER : pipeline complet + simulation interne des trades. Aucun ordre broker envoyé.")
    else:
        out(
            "MODE OBSERVE : scan et analyse complets. RiskEngine actif. Aucun ordre envoyé. "
            "(--mode DEMO pour trader sur le DEMO)"
        )

    agent_impl = make_agent(agent or settings.agent, settings)
    engine = comps.engine(agent_impl, run_mode=run_mode)
    rec = comps.monitor.reconcile()
    out(
        f"Réconciliation: {rec.open_positions} position(s) ALLADIN, {len(rec.adopted)} adoptée(s), "
        f"{len(rec.newly_closed)} clôturée(s) hors-ligne, {rec.foreign_ignored} étrangère(s) ignorée(s)"
    )
    engine.run_loop(
        interval,
        max_cycles=cycles,
        on_cycle=lambda o: out(
            f"[cycle {o.cycle}] {o.run_state} | {o.decision} | {o.reason} | shortlist: {', '.join(o.shortlist) or '-'}"
        ),
    )


# ---------------------------------------------------------------------------- kill / pause / positions


@app.command()
def kill(
    reason: Annotated[str, typer.Option(help="Motif journalisé")] = "kill switch manuel",
    clear: Annotated[
        bool, typer.Option("--clear", help="Lever le kill switch (un nouveau run reste nécessaire)")
    ] = False,
) -> None:
    """Kill switch : bloque toute nouvelle exécution et passe le run actif en KILLED (irréversible)."""
    settings = get_settings()
    from alladin.core.killswitch import KillSwitch

    ks = KillSwitch(settings.kill_switch_path)
    if clear:
        ks.clear()
        out("Kill switch levé. Les runs KILLED restent KILLED : créer un nouveau run (runs new).")
        return
    ks.activate(reason)
    from alladin.journal.repository import JournalRepository
    from alladin.journal.service import JournalService
    from alladin.orchestration.state import RunManager

    repo = JournalRepository.from_url(settings.db_url)
    mgr = RunManager(repo, JournalService(repo), ks, settings.magic_base)
    rid = mgr.latest_run_id(only_open=True)
    if rid:
        rec = repo.get_run(rid)
        assert rec is not None
        ctx = mgr.load_run(rid, load_profile(rec.profile_id, settings.profiles_dir))
        mgr.kill(ctx, reason)
        out(
            f"KILLED : {rid}. Aucune nouvelle exécution possible. Les positions ouvertes ne sont PAS fermées (voir: positions close-all)."
        )
    else:
        out("Kill switch activé (aucun run actif). Aucune exécution possible tant qu'il n'est pas levé.")


@app.command()
def pause(
    run: RunOpt = None,
    resume: Annotated[bool, typer.Option("--resume", help="Reprendre un run en pause")] = False,
) -> None:
    """Met un run en PAUSED (ou le reprend avec --resume). Un run FAILED/KILLED/PASSED ne reprend jamais."""
    settings = get_settings()
    from alladin.core.killswitch import KillSwitch
    from alladin.journal.repository import JournalRepository
    from alladin.journal.service import JournalService
    from alladin.orchestration.state import RunManager

    repo = JournalRepository.from_url(settings.db_url)
    mgr = RunManager(repo, JournalService(repo), KillSwitch(settings.kill_switch_path), settings.magic_base)
    rid = run or mgr.latest_run_id(only_open=True)
    rec = repo.get_run(rid) if rid else None
    if rec is None:
        raise die("Aucun run actif.", 2)
    ctx = mgr.load_run(rec.run_id, load_profile(rec.profile_id, settings.profiles_dir))
    try:
        mgr.resume(ctx) if resume else mgr.pause(ctx)
    except AlladinError as exc:
        raise die(f"Refusé : {exc}") from exc
    out(f"{rec.run_id} -> {ctx.watchdog.run_state.value}")


@positions_app.command("close-all")
def positions_close_all(broker_kind: BrokerOpt = "mt5", run: RunOpt = None) -> None:
    """Ferme (explicitement, après confirmation) les positions de CE run — jamais celles d'autres origines."""
    settings = get_settings()
    comps = _components(settings, broker_kind, run_id=run)
    mine = comps.execution.my_positions()
    if not mine:
        out(f"Aucune position ALLADIN ouverte pour {comps.run.run_id}.")
        return
    for p in mine:
        out(f"  {p.ticket} {p.symbol} {p.side.value} {p.volume:g} lots  P&L {p.profit:+.2f}")
    if (
        typer.prompt("Tapez CLOSE pour fermer ces positions", default="", show_default=False).strip()
        != "CLOSE"
    ):
        raise die("Annulé.", 0)
    n = comps.execution.close_all("fermeture manuelle (positions close-all)")
    comps.monitor.sync()
    out(f"{n} ordre(s) de fermeture envoyé(s) ; journal mis à jour.")


@app.command()
def stats(
    by: Annotated[str, typer.Option(help="strategy | symbol | regime | session | agent")] = "strategy",
    run: RunOpt = None,
) -> None:
    """Statistiques des trades clôturés (lecture seule du journal)."""
    from alladin.journal.repository import JournalRepository
    from alladin.journal.service import JournalService

    svc = JournalService(JournalRepository.from_url(get_settings().db_url))
    rows = svc.stats(by, run)
    if not rows:
        out("Aucun trade clôturé.")
    for r in rows:
        out(
            f"{r.key:<28} n={r.trades:<4} win={r.win_rate:>5.0%} net={r.net_pnl:>10,.2f} R_moy={r.avg_r:+.2f} [{r.worst_r:+.2f}; {r.best_r:+.2f}]"
        )


@replay_app.command("cycle")
def replay_cycle(cycle_id: str) -> None:
    """Reconstruit un cycle depuis le journal et l'archive. N'envoie jamais d'ordre."""
    from alladin.journal.repository import JournalRepository
    from alladin.replay import ReplayContext

    try:
        replay = ReplayContext.from_cycle(JournalRepository.from_url(get_settings().db_url), cycle_id)
    except ValueError as exc:
        raise die(str(exc), 2) from exc
    out(replay.model_dump_json(indent=2))


@archive_app.command("stats")
def archive_stats() -> None:
    """Statistiques de l'archive de barres OHLCV."""
    from alladin.journal.repository import JournalRepository
    from alladin.market.archive import MarketDataArchive

    repo = JournalRepository.from_url(get_settings().db_url)
    arch = MarketDataArchive(repo.engine, workspace=repo.workspace)
    s = arch.stats()
    out(f"Barres archivees : {s['bars']:,}")
    out(f"Symboles         : {s['symbols']}")


@archive_app.command("inspect")
def archive_inspect(cycle_id: str) -> None:
    """Inspecte les barres archivees pour un cycle donné."""
    from alladin.journal.repository import JournalRepository
    from alladin.market.archive import MarketDataArchive

    repo = JournalRepository.from_url(get_settings().db_url)
    arch = MarketDataArchive(repo.engine, workspace=repo.workspace)
    inputs = arch.cycle_inputs(cycle_id)
    if not inputs:
        out(f"Aucune donnée archivée pour le cycle {cycle_id}")
        raise typer.Exit(1)
    by_key: dict[str, int] = {}
    for row in inputs:
        key = f"{row['symbol']}@{row['timeframe']}"
        by_key[key] = by_key.get(key, 0) + 1
    for key, count in sorted(by_key.items()):
        out(f"  {key}: {count} barres")


@app.command()
def serve(
    host: str = "127.0.0.1",
    port: int = 8000,
    broker_kind: BrokerOpt = "mock",
) -> None:
    """Mission Control en LECTURE SEULE. Aucun endpoint de trading."""
    import uvicorn

    from alladin.api.app import create_app
    from alladin.journal.repository import JournalRepository

    setup_logging()
    settings = get_settings()
    broker = make_broker(broker_kind, settings)
    _connect(broker)
    uvicorn.run(
        create_app(settings, JournalRepository.from_url(settings.db_url), broker), host=host, port=port
    )


def _jafar_components(kind: str, *, create: bool = False, run_id: str | None = None) -> Components:
    if kind not in ("crypto-mock", "crypto-public", "crypto-testnet"):
        raise die("Jafar: --broker crypto-mock | crypto-public | crypto-testnet", 2)
    settings = get_settings()
    broker = make_broker(kind, settings)
    _connect(broker)
    try:
        comps = build_services(
            settings, broker, workspace=WorkspaceId.JAFAR, create_run=create, run_id=run_id
        )
    except AlladinError as exc:
        raise die(str(exc), 2) from exc
    if comps is None:
        raise die("Créer un run: python -m alladin jafar new --broker " + kind, 2)
    return comps


@jafar_app.command("new")
def jafar_new(broker_kind: BrokerOpt = "crypto-mock") -> None:
    """Crée un run isolé, avec budget virtuel et aucune stratégie."""
    comps = _jafar_components(broker_kind, create=True)
    out(
        f"{comps.run.run_id} | JAFAR | {comps.jafar_mode.value if comps.jafar_mode else 'OBSERVE'} | budget virtuel {comps.profile.initial_balance:g} USDT"
    )


@jafar_app.command("mode")
def jafar_mode(
    target: str,
    broker_kind: BrokerOpt = "crypto-mock",
    run: RunOpt = None,
    reason: str = "operator_request",
) -> None:
    """Change le mode persiste; les transitions dangereuses sont progressives."""
    from alladin.orchestration.jafar import JafarModeStore

    try:
        requested = JafarMode(target.upper())
    except ValueError as exc:
        raise die("mode Jafar invalide: OBSERVE | PAPER | TESTNET | LIVE_GATED | LIVE", 2) from exc
    comps = _jafar_components(broker_kind, run_id=run)
    try:
        selected = JafarModeStore(comps.journal, comps.run.run_id).transition(requested, reason=reason)
    except AlladinError as exc:
        raise die(str(exc), 2) from exc
    out(f"{comps.run.run_id} | mode {selected.value} persiste")


@jafar_app.command("run")
def jafar_run(
    broker_kind: BrokerOpt = "crypto-mock",
    run: RunOpt = None,
    interval: float = 300,
    cycles: int = 1,
    mode: str = "OBSERVE",
) -> None:
    """Observe (ou simule PAPER) les donnees spot sans jamais envoyer d'ordre production."""
    try:
        requested_mode = JafarMode(mode.upper())
    except ValueError as exc:
        raise die("mode Jafar invalide: OBSERVE | PAPER | TESTNET | LIVE_GATED | LIVE", 2) from exc
    if interval < 0 or cycles < 1:
        raise die("interval >= 0 et cycles >= 1 requis", 2)
    comps = _jafar_components(broker_kind, run_id=run)
    if comps.jafar_mode is not requested_mode:
        raise die(
            f"mode demande {requested_mode.value} != mode persiste {comps.jafar_mode.value if comps.jafar_mode else 'UNKNOWN'}",
            2,
        )
    if requested_mode not in (JafarMode.OBSERVE, JafarMode.PAPER):
        raise die(
            f"runtime {requested_mode.value} non raccorde via CLI: utiliser jafar serve pour TESTNET/LIVE",
            2,
        )
    if comps.run.watchdog.run_state in (RunState.CREATED, RunState.READY):
        comps.manager.start(comps.run, comps.broker.account_info())

    if requested_mode is JafarMode.PAPER:
        _jafar_run_paper(comps, broker_kind, cycles, interval)
        return

    # OBSERVE
    engine = comps.engine(make_agent("mock", comps.settings))
    engine.run_loop(
        interval,
        max_cycles=cycles,
        on_cycle=lambda o: out(
            f"{comps.run.run_id} | OBSERVE | {o.decision} | {o.reason} | {', '.join(o.shortlist) or '-'}"
        ),
    )


def _jafar_run_paper(comps: Any, broker_kind: str, cycles: int, interval: float) -> None:
    """Boucle PAPER Jafar : donnees reelles Binance, execution 100% simulee."""
    import time as _time

    from alladin.jafar.paper import JafarPaperEngine, JafarPaperRuntime
    from alladin.market.archive import MarketDataArchive
    from alladin.market.scanner import MarketScanner
    from alladin.market.universe import MarketUniverse
    from alladin.orchestration.jafar import JafarPaperBrain

    broker = comps.broker
    provider = getattr(broker, "provider", None)
    if provider is None:
        raise die("broker sans provider crypto - utiliser crypto-mock ou crypto-public", 2)

    paper_engine = JafarPaperEngine(
        provider=provider,
        run_id=comps.run.run_id,
        workspace=comps.run.workspace,
        initial_capital=comps.profile.initial_balance,
        repo=comps.repo,
        lifecycle=comps.order_lifecycle,
        journal=comps.journal,
    )
    restored = paper_engine.restore()
    if restored:
        out(f"{comps.run.run_id} | PAPER | {restored} position(s) restauree(s)")

    runtime = JafarPaperRuntime(
        broker=broker,
        scanner=MarketScanner(
            broker,
            MarketUniverse(broker, comps.profile.universe),
            comps.profile.universe,
            archive=MarketDataArchive(comps.repo.engine, workspace=comps.run.workspace),
        ),
        brain=JafarPaperBrain(),
        risk=comps.risk,
        engine=paper_engine,
        journal=comps.journal,
        outcomes=comps.outcomes,
        run_state=lambda: comps.run.watchdog.run_state,
    )
    for cycle_n in range(cycles):
        result = runtime.run_cycle()
        snap = paper_engine.portfolio_snapshot()
        out(
            f"{comps.run.run_id} | PAPER | cycle={cycle_n+1}/{cycles} "
            f"decision={result.decision} "
            f"capital={snap.total_value:.2f} cash={snap.cash:.2f} "
            f"open={snap.open_positions} closed={snap.closed_trades} "
            f"pnl={snap.realized_pnl:+.2f}"
        )

        if cycle_n < cycles - 1 and interval > 0:
            _time.sleep(interval)


@jafar_app.command("serve")
def jafar_serve(broker_kind: BrokerOpt = "crypto-mock", host: str = "127.0.0.1", port: int = 8002) -> None:
    """Cockpit Jafar rouge en lecture seule ; seules les données Jafar sont exposées."""
    import uvicorn

    from alladin.api.app import create_app

    comps = _jafar_components(broker_kind)
    uvicorn.run(create_app(comps.settings, comps.repo, comps.broker), host=host, port=port)


@jafar_app.command("kill")
def jafar_kill(
    broker_kind: BrokerOpt = "crypto-mock", reason: str = "arrêt Jafar", clear: bool = False
) -> None:
    """Arrête le workspace Jafar sans toucher au kill switch Alladin."""
    if clear:
        from alladin.core.killswitch import KillSwitch

        KillSwitch(get_settings().for_workspace(WorkspaceId.JAFAR).kill_switch_path).clear()
        out("Kill switch Jafar levé ; les runs KILLED restent terminaux. Créer un nouveau run.")
        return
    comps = _jafar_components(broker_kind)
    comps.manager.kill(comps.run, reason)
    out(f"{comps.run.run_id} KILLED — Alladin indépendant")


@jafar_app.command("account")
def jafar_account(symbol: str | None = None, testnet: bool = False) -> None:
    """Lit le compte Binance et son historique sans exposer de credential ni envoyer d'ordre."""
    import json

    from alladin.brokers.binance import BinanceError
    from alladin.orchestration.bootstrap import make_binance_account_client

    try:
        client = make_binance_account_client(get_settings(), testnet=testnet)
        account = client.account()
        restrictions = client.api_restrictions()
        payload: dict[str, object] = {
            "observed_at": account.observed_at.isoformat(),
            "can_trade_account_flag": account.can_trade,
            "can_withdraw_account_flag": account.can_withdraw,
            "permissions": account.permissions,
            "api_key_restrictions": restrictions.model_dump(mode="json"),
            "api_key_read_only_safe": restrictions.safe_for_read_only,
            "nonzero_balances": [b.model_dump() for b in account.balances if b.total > 0],
            "open_orders": [o.model_dump(mode="json") for o in client.open_orders(symbol)],
        }
        if symbol:
            payload["order_history"] = [o.model_dump(mode="json") for o in client.order_history(symbol)]
            payload["trade_history"] = [t.model_dump(mode="json") for t in client.trade_history(symbol)]
        out(json.dumps(payload, indent=2, ensure_ascii=False))
    except (AlladinError, BinanceError, OSError, ValueError) as exc:
        raise die(f"Binance read-only indisponible: {exc}", 2) from exc


@jafar_app.command("positions")
def jafar_positions(broker_kind: BrokerOpt = "crypto-mock", run: RunOpt = None) -> None:
    """Liste les positions PAPER ouvertes et le portefeuille simule."""
    import json

    from alladin.jafar.paper import JafarPaperEngine

    comps = _jafar_components(broker_kind, run_id=run)
    provider = getattr(comps.broker, "provider", None)
    if provider is None:
        raise die("broker sans provider crypto", 2)

    engine = JafarPaperEngine(
        provider=provider,
        run_id=comps.run.run_id,
        workspace=comps.run.workspace,
        initial_capital=comps.profile.initial_balance,
        repo=comps.repo,
    )
    engine.restore()
    engine.tick_all()

    snap = engine.portfolio_snapshot()
    out(json.dumps({
        "run_id": comps.run.run_id,
        "mode": "PAPER",
        "portfolio": {
            "initial_capital": snap.initial_capital,
            "total_value": round(snap.total_value, 4),
            "cash": round(snap.cash, 4),
            "invested": round(snap.invested, 4),
            "unrealized_pnl": round(snap.unrealized_pnl, 4),
            "realized_pnl": round(snap.realized_pnl, 4),
            "total_fees": round(snap.total_fees, 4),
            "drawdown_pct": round(snap.drawdown_pct, 2),
            "win_rate": snap.win_rate,
        },
        "open_positions": [
            {
                "position_id": p.position_id,
                "symbol": p.symbol,
                "side": p.side.value,
                "quantity": p.quantity,
                "entry_price": p.entry_price,
                "sl": p.sl,
                "tp": p.tp,
                "unrealized_pnl": round(p.unrealized_pnl, 4),
                "fees_paid": round(p.fees_paid, 4),
                "opened_at": p.opened_at.isoformat(),
            }
            for p in engine.open_positions()
        ],
        "closed_count": len(engine.closed_positions()),
    }, indent=2, ensure_ascii=False))


@jafar_app.command("open-orders")
def jafar_open_orders(broker_kind: BrokerOpt = "crypto-mock", run: RunOpt = None) -> None:
    """Liste les ordres lifecycle non-terminaux (SUBMITTING, PENDING_CONFIRMATION, etc.)."""
    import json

    from sqlalchemy import create_engine as _create_engine

    from alladin.execution.order_lifecycle import OrderLifecycleRepository

    comps = _jafar_components(broker_kind, run_id=run)
    settings = comps.settings.for_workspace(comps.run.workspace)
    lifecycle = OrderLifecycleRepository(_create_engine(settings.db_url), comps.run.workspace)
    pending = lifecycle.pending_reconciliation()
    out(json.dumps({
        "run_id": comps.run.run_id,
        "pending_reconciliation": [
            {
                "client_order_id": c.client_order_id,
                "symbol": c.symbol,
                "status": c.status.value,
                "exchange_order_id": c.exchange_order_id,
                "created_at": c.created_at.isoformat(),
                "updated_at": c.updated_at.isoformat(),
            }
            for c in pending
        ],
        "count": len(pending),
    }, indent=2, ensure_ascii=False))


@jafar_app.command("reconcile")
def jafar_reconcile(broker_kind: BrokerOpt = "crypto-mock", run: RunOpt = None, testnet: bool = False) -> None:
    """Diagnostic de reconciliation : ordres locaux vs exchange (sans envoi d'ordre)."""
    import json

    from sqlalchemy import create_engine as _create_engine

    from alladin.brokers.binance import BinanceError
    from alladin.execution.order_lifecycle import OrderLifecycleRepository
    from alladin.jafar.execution import JafarRestartReconciler
    from alladin.orchestration.bootstrap import make_binance_account_client

    comps = _jafar_components(broker_kind, run_id=run)
    settings = comps.settings.for_workspace(comps.run.workspace)
    try:
        read_client = make_binance_account_client(get_settings(), testnet=testnet)
    except (AlladinError, Exception) as exc:
        raise die(f"Binance read-only client indisponible: {exc}", 2) from exc
    lifecycle = OrderLifecycleRepository(_create_engine(settings.db_url), comps.run.workspace)
    symbols = tuple(s.symbol for s in comps.broker.list_symbols()[:20]) or ("BTCUSDT",)
    reconciler = JafarRestartReconciler(
        lifecycle=lifecycle,
        read_client=read_client,
        journal=comps.journal,
        run_id=comps.run.run_id,
        workspace=comps.run.workspace,
        symbols=symbols,
    )
    try:
        report = reconciler.reconcile()
    except (BinanceError, Exception) as exc:
        raise die(f"reconciliation echouee: {exc}", 2) from exc
    out(json.dumps({
        "run_id": comps.run.run_id,
        "coherent": report.coherent,
        "inspected": report.inspected,
        "resolved": report.resolved,
        "ambiguous": list(report.ambiguous),
        "errors": list(report.errors),
    }, indent=2, ensure_ascii=False))
    if not report.coherent:
        raise typer.Exit(1)


@outcomes_app.command("refresh")
def outcomes_refresh(run_id: str, workspace: WorkspaceId = WorkspaceId.ALLADIN) -> None:
    """Capture les trades déjà clôturés depuis la base et le journal, sans broker."""
    from alladin.journal.repository import JournalRepository
    from alladin.journal.service import JournalService
    from alladin.research.outcomes import OutcomeEngine, RewardPolicy

    settings = get_settings().for_workspace(workspace)
    repo = JournalRepository.from_url(settings.db_url, workspace)
    engine = OutcomeEngine(repo, JournalService(repo), RewardPolicy.load(settings.reward_policy_path))
    try:
        report = engine.collect_run(run_id)
    except ValueError as exc:
        raise die(str(exc), 2) from exc
    out(report.model_dump_json(indent=2))
    if report.errors:
        raise typer.Exit(2)


@outcomes_app.command("show")
def outcomes_show(run_id: str, workspace: WorkspaceId = WorkspaceId.ALLADIN, limit: int = 200) -> None:
    """Lit les snapshots persistés ; ne calcule pas de récompenses et ne parle pas au broker."""
    import json

    from alladin.journal.repository import JournalRepository
    from alladin.research.outcomes import OutcomeRepository, outcome_summary

    if not 1 <= limit <= 1000:
        raise die("limit entre 1 et 1000 requis", 2)
    settings = get_settings().for_workspace(workspace)
    repo = JournalRepository.from_url(settings.db_url, workspace)
    if repo.get_run(run_id) is None:
        raise die("run inconnu ou hors workspace", 2)
    rows = OutcomeRepository(repo, read_only=True).list(run_id, limit=limit)
    out(
        json.dumps(
            {
                "workspace": workspace.value,
                "run_id": run_id,
                "summary_scope": "RETURNED_ROWS",
                "summary": outcome_summary(rows),
                "outcomes": [r.model_dump(mode="json") for r in rows],
            },
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
