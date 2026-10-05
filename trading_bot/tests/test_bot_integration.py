"""Ciclo completo del bot contra un mercado y unas noticias simuladas."""

from datetime import timedelta

import pandas as pd
import pytest

import bot as bot_module
import config
from api_handler import AccountInfo, BrokerError, PaperBroker, build_brokers
from config import CRYPTO, STOCKS, NewsSettings, RiskSettings, Settings, StrategySettings, build_instruments
from news_handler import NewsAggregator
from risk_manager import RiskManager
from sentiment import SentimentAnalyzer
from strategy import SentimentMomentumStrategy
from tests.conftest import NOW, FakeDataBroker, StaticNewsProvider, article, make_bars
from utils import TradeJournal


@pytest.fixture
def env(tmp_path):
    instruments = build_instruments([], ["BTC/USDT"])
    settings = Settings(paper_trading=True, instruments=instruments, log_dir=tmp_path / "logs",
                        state_dir=tmp_path / "state", strategy=StrategySettings(), risk=RiskSettings(),
                        news=NewsSettings())
    bars = make_bars()
    data = FakeDataBroker(CRYPTO, bars=bars, price=float(bars["close"].iloc[-2]), spread=0.01)
    paper = PaperBroker(data, initial_cash=10_000, fee_pct=0.001, slippage_pct=0.0005,
                        state_path=tmp_path / "state" / "paper_crypto.json", currency="USDT")
    provider = StaticNewsProvider([
        article("Bitcoin surges to record high as ETF inflows jump", 3),
        article("Analysts turn bullish on Bitcoin after strong rally", 8),
        article("Bitcoin soars past key resistance", 12),
    ])
    news = NewsAggregator(settings.news, instruments, providers=[provider])
    risk = RiskManager(settings.risk, tmp_path / "state" / "risk.json")
    trading_bot = bot_module.TradingBot(
        settings=settings, brokers={CRYPTO: paper}, news=news,
        analyzer=SentimentAnalyzer(), strategy=SentimentMomentumStrategy(settings.strategy),
        risk=risk, journal=TradeJournal(settings.log_dir, paper=True))
    return trading_bot, data, paper, risk, provider, settings


def test_full_trade_lifecycle(env):
    trading_bot, data, paper, risk, provider, settings = env

    # 1) Noticias positivas + tendencia alcista -> compra simulada
    trading_bot.run_cycle(NOW)
    assert "BTC/USDT" in risk.positions
    position = risk.positions["BTC/USDT"]
    assert position.qty * position.entry_price <= 10_000 * 0.05 + 1e-6
    assert paper.holdings["BTC/USDT"] == pytest.approx(position.qty)

    # 2) El precio alcanza el take-profit -> venta simulada con beneficio
    data.price = position.take_profit_price + 0.05
    trading_bot.run_cycle(NOW + timedelta(minutes=1))
    assert "BTC/USDT" not in risk.positions
    journal = pd.read_csv(settings.log_dir / "paper_trades.csv")
    assert list(journal["exit_reason"]) == ["TAKE_PROFIT"]
    assert journal["net_pnl"].iloc[0] > 0
    assert paper.cash > 10_000

    # 3) Mismo catalizador + cooldown -> no se vuelve a entrar
    trading_bot.run_cycle(NOW + timedelta(minutes=30))
    assert "BTC/USDT" not in risk.positions


def test_stop_loss_and_losing_trade(env):
    trading_bot, data, paper, risk, _, settings = env
    trading_bot.run_cycle(NOW)
    position = risk.positions["BTC/USDT"]
    data.price = position.stop_price - 0.05
    trading_bot.run_cycle(NOW + timedelta(minutes=1))
    journal = pd.read_csv(settings.log_dir / "paper_trades.csv")
    assert list(journal["exit_reason"]) == ["STOP_LOSS"]
    loss = -journal["net_pnl"].iloc[0]
    # Pérdida acotada: stop (<= 1 % del nominal) + costes de ida y vuelta (0.3 %) + hueco
    assert 0 < loss <= 0.014 * journal["notional"].iloc[0]
    # ...lo que supone menos del 0.1 % del capital de la cuenta
    assert loss < 0.001 * 10_000


def test_no_entry_without_news_or_with_network_errors(env):
    trading_bot, data, _, risk, provider, _ = env
    provider.articles = []
    trading_bot.run_cycle(NOW)
    assert not risk.positions

    data.fail_quotes = True     # caída de red: el ciclo no explota
    provider.articles = [article("Bitcoin surges to record high", 1)]
    trading_bot.news._next_poll.clear()
    trading_bot.run_cycle(NOW + timedelta(minutes=1))
    assert not risk.positions


def test_kill_switch_blocks_entries(env):
    trading_bot, _, _, risk, _, _ = env
    risk.roll_day_if_needed(NOW, 10_000)
    risk.realized_pnl_today = -300
    trading_bot.run_cycle(NOW)
    assert risk.kill_switch and not risk.positions


def test_paper_mode_builds_simulated_brokers_without_keys(tmp_path):
    settings = Settings(paper_trading=True, instruments=build_instruments(["AAPL"], ["BTC/USDT"]),
                        state_dir=tmp_path)
    brokers = build_brokers(settings)
    assert set(brokers) == {CRYPTO}            # acciones desactivadas: no hay claves de Alpaca
    assert isinstance(brokers[CRYPTO], PaperBroker)
    assert brokers[CRYPTO].data.read_only and not brokers[CRYPTO].data.has_credentials


def test_live_mode_requires_explicit_confirmation(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PAPER_TRADING", False)
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("LIVE_TRADING_CONFIRMATION", raising=False)
    assert bot_module.main(["--once", "--env-file", str(tmp_path / "missing.env")]) == 3


def test_report(tmp_path, capsys, env):
    trading_bot, data, _, risk, _, settings = env
    trading_bot.run_cycle(NOW)
    data.price = risk.positions["BTC/USDT"].take_profit_price + 0.05
    trading_bot.run_cycle(NOW + timedelta(minutes=1))
    assert bot_module.print_report(settings.log_dir / "paper_trades.csv") == 0
    assert "Tasa de acierto       : 100.0%" in capsys.readouterr().out


# --- Acciones: horario de mercado ---------------------------------------------------
def make_stock_bot(tmp_path, paper_mode=True, broker=None):
    instruments = build_instruments(["AAPL"], [])
    settings = Settings(paper_trading=paper_mode, instruments=instruments, log_dir=tmp_path / "logs",
                        state_dir=tmp_path / "state")
    bars = make_bars()
    data = FakeDataBroker(STOCKS, bars=bars, price=float(bars["close"].iloc[-2]), spread=0.01)
    if broker is None:
        broker = PaperBroker(data, initial_cash=10_000, fee_pct=0.0, slippage_pct=0.0005, currency="USD")
    provider = StaticNewsProvider([article("Apple beats estimates and raises outlook", 3),
                                   article("Apple shares soar on record iPhone sales", 6),
                                   article("Analysts upgrade Apple to outperform", 9)])
    news = NewsAggregator(settings.news, instruments, providers=[provider])
    risk = RiskManager(settings.risk)
    trading_bot = bot_module.TradingBot(
        settings=settings, brokers={STOCKS: broker}, news=news, analyzer=SentimentAnalyzer(),
        strategy=SentimentMomentumStrategy(settings.strategy), risk=risk,
        journal=TradeJournal(settings.log_dir, paper=paper_mode))
    return trading_bot, data, risk


def test_stocks_only_trade_in_market_hours_and_flatten_before_close(tmp_path):
    trading_bot, data, risk = make_stock_bot(tmp_path)
    data.market_open = False
    trading_bot.run_cycle(NOW)
    assert not risk.positions                     # mercado cerrado: nada

    data.market_open, data.close_in_minutes = True, 20
    trading_bot.run_cycle(NOW + timedelta(seconds=30))
    assert not risk.positions                     # < 30 min para el cierre: sin entradas

    data.close_in_minutes = 120
    trading_bot.run_cycle(NOW + timedelta(seconds=60))
    assert "AAPL" in risk.positions

    data.close_in_minutes = 5                     # se acerca el cierre: se liquida
    trading_bot.run_cycle(NOW + timedelta(seconds=90))
    assert not risk.positions
    journal = pd.read_csv(tmp_path / "logs" / "paper_trades.csv")
    assert list(journal["exit_reason"]) == ["CIERRE_MERCADO"]


# --- Modo real: recuperación y reconciliación ---------------------------------------
class FlakyLiveBroker(FakeDataBroker):
    """Broker 'real' cuya respuesta a la orden se pierde aunque sí se ejecuta."""

    def __init__(self, **kwargs):
        super().__init__(STOCKS, **kwargs)
        self.holdings = {}

    def get_account(self):
        return AccountInfo(equity=50_000.0, cash=50_000.0)

    def get_positions(self):
        return dict(self.holdings)

    def submit_market_order(self, symbol, side, qty, client_order_id=None):
        if side == "buy":
            self.holdings[symbol] = self.holdings.get(symbol, 0.0) + qty
        raise BrokerError("timeout leyendo la respuesta (simulado)")


def test_lost_order_response_is_recovered_with_stops(tmp_path):
    bars = make_bars()
    broker = FlakyLiveBroker(bars=bars, price=float(bars["close"].iloc[-2]), spread=0.01)
    trading_bot, _, risk = make_stock_bot(tmp_path, paper_mode=False, broker=broker)
    trading_bot.run_cycle(NOW)
    position = risk.positions["AAPL"]             # adoptada pese al error
    assert position.qty == pytest.approx(broker.holdings["AAPL"])
    assert position.stop_price < position.entry_price


def test_reconcile_drops_positions_closed_outside_the_bot(tmp_path):
    bars = make_bars()
    broker = FlakyLiveBroker(bars=bars, price=float(bars["close"].iloc[-2]), spread=0.01)
    trading_bot, _, risk = make_stock_bot(tmp_path, paper_mode=False, broker=broker)
    trading_bot.run_cycle(NOW)
    assert "AAPL" in risk.positions
    broker.holdings.clear()                        # el usuario cerró a mano en el broker
    trading_bot.run_cycle(NOW + timedelta(seconds=30))
    assert "AAPL" not in risk.positions
