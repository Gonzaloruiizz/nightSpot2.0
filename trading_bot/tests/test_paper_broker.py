import pytest

from api_handler import BUY, SELL, AlpacaBroker, BrokerError, CCXTBroker, InsufficientFunds, OrderRejected, PaperBroker
from tests.conftest import FakeDataBroker


def make_paper(tmp_path, **kwargs):
    data = FakeDataBroker(price=100.0, spread=0.2)  # bid 99.9 / ask 100.1
    params = dict(initial_cash=10_000.0, fee_pct=0.001, slippage_pct=0.001,
                  state_path=tmp_path / "paper.json")
    params.update(kwargs)
    return data, PaperBroker(data, **params)


def test_buy_and_sell_apply_spread_slippage_and_fees(tmp_path):
    data, paper = make_paper(tmp_path)
    buy = paper.submit_market_order("BTC/USDT", BUY, 10)
    assert buy.avg_price == pytest.approx(100.1 * 1.001)
    assert buy.fee == pytest.approx(10 * buy.avg_price * 0.001)
    assert paper.cash == pytest.approx(10_000 - 10 * buy.avg_price - buy.fee)

    sell = paper.submit_market_order("BTC/USDT", SELL, 10)
    assert sell.avg_price == pytest.approx(99.9 * 0.999)
    assert paper.get_positions() == {}
    # Ida y vuelta sin movimiento de precio = pérdida por costes
    assert paper.cash < 10_000


def test_equity_marks_holdings_at_bid(tmp_path):
    data, paper = make_paper(tmp_path, fee_pct=0.0, slippage_pct=0.0)
    paper.submit_market_order("BTC/USDT", BUY, 10)
    data.price = 110.0
    account = paper.get_account()
    assert account.equity == pytest.approx(10_000 - 10 * 100.1 + 10 * 109.9)


def test_rejections(tmp_path):
    _, paper = make_paper(tmp_path)
    with pytest.raises(InsufficientFunds):
        paper.submit_market_order("BTC/USDT", BUY, 1_000)
    with pytest.raises(OrderRejected):
        paper.submit_market_order("BTC/USDT", SELL, 1)
    with pytest.raises(OrderRejected):
        paper.submit_market_order("BTC/USDT", BUY, 0)


def test_sell_never_exceeds_holdings(tmp_path):
    _, paper = make_paper(tmp_path)
    paper.submit_market_order("BTC/USDT", BUY, 2)
    result = paper.submit_market_order("BTC/USDT", SELL, 5)
    assert result.filled_qty == 2


def test_paper_account_persists(tmp_path):
    data, paper = make_paper(tmp_path)
    paper.submit_market_order("BTC/USDT", BUY, 3)
    restored = PaperBroker(data, initial_cash=999.0, fee_pct=0.001, slippage_pct=0.001,
                           state_path=tmp_path / "paper.json")
    assert restored.cash == pytest.approx(paper.cash)
    assert restored.holdings == {"BTC/USDT": 3}


def test_paper_logs_every_simulated_order(tmp_path, caplog):
    _, paper = make_paper(tmp_path)
    with caplog.at_level("INFO", logger="trades"):
        paper.submit_market_order("BTC/USDT", BUY, 1)
    assert "ORDEN SIMULADA" in caplog.text


def test_real_clients_are_read_only_in_paper_mode():
    """Defensa en profundidad: los clientes reales creados en modo paper no pueden operar."""
    crypto = CCXTBroker("binance", sandbox=False, read_only=True, symbols=["BTC/USDT"])
    with pytest.raises(BrokerError, match="SOLO LECTURA"):
        crypto.submit_market_order("BTC/USDT", BUY, 1)
    stocks = AlpacaBroker("key", "secret", paper_endpoint=True, read_only=True)
    with pytest.raises(BrokerError, match="SOLO LECTURA"):
        stocks.submit_market_order("AAPL", BUY, 1)


def test_ccxt_broker_validation():
    with pytest.raises(BrokerError, match="no soportado"):
        CCXTBroker("exchange_inventado")
    with pytest.raises(BrokerError, match="misma divisa"):
        CCXTBroker("binance", symbols=["BTC/USDT", "ETH/EUR"])
    with pytest.raises(BrokerError, match="sandbox"):
        CCXTBroker("kraken", "k", "s", sandbox=True, symbols=["BTC/USD"])
    with pytest.raises(BrokerError, match="ALPACA_API_KEY"):
        AlpacaBroker("", "")
