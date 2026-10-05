from dataclasses import replace
from datetime import timedelta

import pytest

from config import CRYPTO, STOCKS
from risk_manager import ExitReason, RiskManager
from tests.conftest import NOW


def plan_for(rm: RiskManager, *, price=100.0, atr=0.3, equity=10_000.0, cash=10_000.0,
             asset_class=STOCKS, symbol="AAPL", min_notional=1.0):
    return rm.build_trade_plan(symbol=symbol, asset_class=asset_class, price=price, atr=atr,
                               equity=equity, cash=cash, normalize_qty=lambda q: round(q, 6),
                               min_notional=min_notional)


def open_position(rm: RiskManager, *, price=100.0, atr=0.3, symbol="AAPL", asset_class=STOCKS, now=NOW):
    plan, _ = plan_for(rm, price=price, atr=atr, symbol=symbol, asset_class=asset_class)
    assert plan is not None
    return rm.register_open(plan, plan.qty, price, 0.0, now)


# --- Stop dinámico -------------------------------------------------------------
@pytest.mark.parametrize("atr, expected_pct", [
    (0.01, 0.005),   # ATR minúsculo -> suelo del 0.5 %
    (0.3, 0.006),    # 2 x ATR = 0.6 %
    (5.0, 0.01),     # ATR enorme -> techo del 1 %
    (None, 0.01),    # sin ATR -> 1 % por defecto
])
def test_stop_distance_is_clamped(risk_cfg, atr, expected_pct):
    rm = RiskManager(risk_cfg)
    assert rm.stop_distance(100.0, atr) == pytest.approx(100.0 * expected_pct)


# --- Tamaño de posición --------------------------------------------------------
def test_position_never_exceeds_5_percent(risk_cfg):
    plan, why = plan_for(RiskManager(risk_cfg))
    assert plan.notional <= 10_000 * 0.05 + 1e-9
    assert "5%" in why


def test_hard_cap_applies_even_if_config_is_tampered(risk_cfg):
    rm = RiskManager(replace(risk_cfg, max_position_pct=0.5, max_total_exposure_pct=1.0))
    plan, _ = plan_for(rm)
    assert plan.notional <= 10_000 * 0.05 + 1e-9


def test_risk_budget_limits_size(risk_cfg):
    rm = RiskManager(replace(risk_cfg, max_risk_per_trade_pct=0.0002))  # 2 $ de riesgo
    plan, why = plan_for(rm)
    assert "riesgo" in why
    assert plan.risk_amount == pytest.approx(2.0, rel=1e-3)


def test_cash_limits_size(risk_cfg):
    plan, why = plan_for(RiskManager(risk_cfg), cash=100.0)
    assert "efectivo" in why
    assert plan.notional <= 100.0


def test_total_exposure_limit(risk_cfg):
    rm = RiskManager(replace(risk_cfg, max_total_exposure_pct=0.06))
    open_position(rm, symbol="MSFT")                      # ocupa 5 %
    plan, why = plan_for(rm, symbol="AAPL")
    assert "exposición" in why
    assert plan.notional == pytest.approx(10_000 * 0.01, rel=2e-3)


def test_levels_and_take_profit(risk_cfg):
    plan, _ = plan_for(RiskManager(risk_cfg), atr=0.3)
    assert plan.stop_price == pytest.approx(99.4)          # 0.6 % por debajo
    assert plan.take_profit_price == pytest.approx(100.9)  # 1.5R


def test_fee_filter_rejects_unprofitable_take_profit(risk_cfg):
    rm = RiskManager(replace(risk_cfg, fee_pct_crypto=0.003))
    plan, why = plan_for(rm, asset_class=CRYPTO, symbol="BTC/USDT")
    assert plan is None and "costes" in why


def test_min_notional_and_zero_qty(risk_cfg):
    rm = RiskManager(risk_cfg)
    plan, why = plan_for(rm, min_notional=10_000)
    assert plan is None and "mínimo" in why
    plan, why = rm.build_trade_plan(symbol="AAPL", asset_class=STOCKS, price=100, atr=0.3,
                                    equity=10_000, cash=10_000, normalize_qty=lambda q: 0.0,
                                    min_notional=1)
    assert plan is None and "cantidad 0" in why


# --- Salidas -----------------------------------------------------------------------
def test_stop_loss_and_take_profit(risk_cfg):
    rm = RiskManager(risk_cfg)
    pos = open_position(rm)
    assert rm.update_and_check_exit(pos, 99.5, NOW) is None
    assert rm.update_and_check_exit(pos, 99.4, NOW) == ExitReason.STOP_LOSS
    pos = open_position(rm, symbol="MSFT")
    assert rm.update_and_check_exit(pos, 100.95, NOW) == ExitReason.TAKE_PROFIT


def test_trailing_stop_ratchets_up_and_never_down(risk_cfg):
    rm = RiskManager(replace(risk_cfg, take_profit_rr=0))   # sin TP para ver el trailing
    pos = open_position(rm)                                  # R = 0.6
    assert rm.update_and_check_exit(pos, 100.6, NOW) is None  # +1R -> se activa
    assert pos.trailing_active
    assert pos.stop_price == pytest.approx(100.6 - 0.45)     # máximo - 0.75R
    rm.update_and_check_exit(pos, 101.2, NOW)
    assert pos.stop_price == pytest.approx(101.2 - 0.45)
    rm.update_and_check_exit(pos, 100.9, NOW)                # retrocede: el stop no baja
    assert pos.stop_price == pytest.approx(101.2 - 0.45)
    assert rm.update_and_check_exit(pos, 100.7, NOW) == ExitReason.TRAILING_STOP


def test_time_stop(risk_cfg):
    rm = RiskManager(risk_cfg)
    pos = open_position(rm)
    later = NOW + timedelta(minutes=risk_cfg.max_holding_minutes)
    assert rm.update_and_check_exit(pos, 100.1, later) == ExitReason.TIME_STOP


def test_register_close_pnl_and_fees(risk_cfg):
    rm = RiskManager(risk_cfg)
    plan, _ = plan_for(rm)
    rm.register_open(plan, 4.0, 100.0, 0.4, NOW)
    trade = rm.register_close("AAPL", 101.0, 4.0, 0.4, ExitReason.TAKE_PROFIT, NOW + timedelta(minutes=30))
    assert trade.gross_pnl == pytest.approx(4.0)
    assert trade.net_pnl == pytest.approx(3.2)
    assert trade.to_row()["holding_minutes"] == 30
    assert "AAPL" not in rm.positions
    assert rm.realized_pnl_today == pytest.approx(3.2)


# --- Cortafuegos de cartera --------------------------------------------------------
def test_consecutive_losses_pause_and_cooldown(risk_cfg):
    rm = RiskManager(risk_cfg)
    for symbol in ("A1", "A2", "A3"):
        open_position(rm, symbol=symbol)
        rm.register_close(symbol, 99.0, 1e9, 0, ExitReason.STOP_LOSS, NOW)
    ok, why = rm.can_open("A4", STOCKS, NOW, 100_000)
    assert not ok and "pausa" in why
    later = NOW + timedelta(minutes=risk_cfg.pause_after_losses_minutes + 1)
    assert rm.can_open("A4", STOCKS, later, 100_000)[0]
    ok, why = rm.can_open("A1", STOCKS, NOW + timedelta(minutes=5), 100_000)
    assert not ok


def test_max_open_positions(risk_cfg):
    rm = RiskManager(replace(risk_cfg, max_open_positions=1))
    open_position(rm, symbol="MSFT")
    ok, why = rm.can_open("AAPL", STOCKS, NOW, 100_000)
    assert not ok and "posiciones" in why


def test_daily_kill_switch(risk_cfg):
    rm = RiskManager(risk_cfg)
    rm.roll_day_if_needed(NOW, 10_000)
    pos = open_position(rm)
    rm.update_and_check_exit(pos, 99.5, NOW)
    assert not rm.check_daily_loss()
    rm.realized_pnl_today = -250   # -2.5 % del capital
    assert rm.check_daily_loss()
    assert not rm.can_open("MSFT", STOCKS, NOW, 10_000)[0]
    rm.roll_day_if_needed(NOW + timedelta(days=1), 9_750)   # nuevo día: se rearma
    assert not rm.kill_switch and rm.realized_pnl_today == 0


def test_pdt_protection(risk_cfg):
    rm = RiskManager(risk_cfg)
    for symbol in ("A1", "A2", "A3"):
        open_position(rm, symbol=symbol)
        rm.register_close(symbol, 100.5, 1e9, 0, ExitReason.TAKE_PROFIT, NOW + timedelta(minutes=10))
    later = NOW + timedelta(hours=1)
    ok, why = rm.can_open("A9", STOCKS, later, 10_000)
    assert not ok and "PDT" in why
    assert rm.can_open("A9", STOCKS, later, 30_000)[0]       # >= 25.000 $: no aplica
    assert rm.can_open("BTC/USDT", CRYPTO, later, 10_000)[0]  # cripto: no aplica


def test_spread_filter(risk_cfg):
    rm = RiskManager(risk_cfg)
    assert rm.check_spread(99.99, 100.01)[0]
    assert not rm.check_spread(99.0, 101.0)[0]
    assert rm.check_spread(0, 0)[0]   # sin datos: no bloquea


# --- Persistencia --------------------------------------------------------------------
def test_state_survives_restart(risk_cfg, tmp_path):
    path = tmp_path / "risk.json"
    rm = RiskManager(risk_cfg, path)
    rm.roll_day_if_needed(NOW, 10_000)
    pos = open_position(rm)
    rm.update_and_check_exit(pos, 100.7, NOW)
    rm.save()

    restored = RiskManager(risk_cfg, path)
    assert set(restored.positions) == {"AAPL"}
    p = restored.positions["AAPL"]
    assert p.trailing_active and p.stop_price == pytest.approx(pos.stop_price)
    assert p.opened_at == NOW
    assert restored.day_start_equity == 10_000


def test_corrupt_state_is_quarantined(risk_cfg, tmp_path):
    path = tmp_path / "risk.json"
    path.write_text("{no es json")
    rm = RiskManager(risk_cfg, path)
    assert rm.positions == {}
    assert list(tmp_path.glob("risk.json.corrupt-*"))
    open_position(rm)  # y sigue pudiendo guardar
    assert path.exists()
