"""
utils.py
========
Utilidades transversales: logging, reintentos con backoff exponencial,
persistencia atómica de estado en JSON, redondeo seguro y diario de
operaciones (trade journal).
"""

from __future__ import annotations

import contextlib
import csv
import json
import logging
import os
import random
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")
logger = logging.getLogger(__name__)

TRADE_LOGGER_NAME = "trades"
_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-14s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
def setup_logging(log_dir: Path, level: str = "INFO", paper: bool = True) -> Path:
    """
    Configura tres salidas:
      - consola
      - logs/bot.log                 -> todo el funcionamiento del bot (rotativo)
      - logs/{paper|live}_trades.log -> SOLO operaciones (diario de trading)
    Devuelve la ruta del log de operaciones.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(_LOG_FORMAT, _DATE_FORMAT)

    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    main_file = RotatingFileHandler(log_dir / "bot.log", maxBytes=5_000_000,
                                    backupCount=5, encoding="utf-8")
    main_file.setFormatter(formatter)
    root.addHandler(main_file)

    trades_path = log_dir / f"{'paper' if paper else 'live'}_trades.log"
    trades_logger = logging.getLogger(TRADE_LOGGER_NAME)
    trades_logger.setLevel(logging.INFO)
    for handler in list(trades_logger.handlers):
        trades_logger.removeHandler(handler)
        handler.close()
    trades_file = RotatingFileHandler(trades_path, maxBytes=10_000_000,
                                      backupCount=10, encoding="utf-8")
    trades_file.setFormatter(logging.Formatter("%(asctime)s | %(message)s", _DATE_FORMAT))
    trades_logger.addHandler(trades_file)
    trades_logger.propagate = True  # también aparece en consola y bot.log

    # Librerías muy verbosas
    for noisy in ("urllib3", "ccxt", "alpaca", "websockets", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return trades_path


# -----------------------------------------------------------------------------
# Reintentos con backoff exponencial + jitter
# -----------------------------------------------------------------------------
def call_with_retry(fn: Callable[[], T], *, is_transient: Callable[[BaseException], bool],
                    attempts: int = 3, base_delay: float = 1.0, max_delay: float = 15.0,
                    description: str = "operación") -> T:
    """
    Ejecuta `fn` reintentando SOLO los errores transitorios (caídas de red,
    timeouts, rate limits, 5xx). Los errores permanentes (credenciales,
    parámetros inválidos, saldo insuficiente) se propagan inmediatamente.

    El retardo crece exponencialmente (1s, 2s, 4s...) con un ±20 % aleatorio
    para no sincronizar reintentos con otros clientes (thundering herd).
    NO usar con el envío de órdenes: reintentar una orden cuyo resultado se
    desconoce podría duplicarla.
    """
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - se decide abajo si se relanza
            if attempt >= attempts or not is_transient(exc):
                raise
            delay = min(max_delay, base_delay * 2 ** (attempt - 1)) * random.uniform(0.8, 1.2)
            # INFO: el fallo definitivo (si llega) lo registra quien llama
            logger.info("%s falló (intento %d/%d): %s — reintento en %.1fs",
                        description, attempt, attempts, exc, delay)
            time.sleep(delay)
    raise RuntimeError("call_with_retry: no alcanzable")  # pragma: no cover


# -----------------------------------------------------------------------------
# Persistencia de estado
# -----------------------------------------------------------------------------
def atomic_write_json(path: Path, data: Any) -> None:
    """
    Escribe JSON de forma atómica (archivo temporal + os.replace) para que un
    corte de luz o un kill a mitad de escritura nunca deje el estado corrupto.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, default=str, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def read_json(path: Path, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default
    except (OSError, json.JSONDecodeError) as exc:
        # Se aparta el archivo dañado para inspección en vez de sobrescribirlo
        backup = path.with_suffix(path.suffix + f".corrupt-{int(time.time())}")
        logger.error("Estado ilegible en %s (%s). Se mueve a %s y se arranca limpio.",
                     path, exc, backup)
        with contextlib.suppress(OSError):
            os.replace(path, backup)
        return default


# -----------------------------------------------------------------------------
# Números
# -----------------------------------------------------------------------------
def floor_to_decimals(value: float, decimals: int) -> float:
    """Redondea HACIA ABAJO sin errores de coma flotante (0.29 -> 0.29, no 0.28)."""
    if value <= 0:
        return 0.0
    quantum = Decimal(1).scaleb(-decimals)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_DOWN))


def fmt_money(value: float) -> str:
    return f"{value:,.2f}"


def fmt_price(value: float) -> str:
    """Precio con decimales adaptados a su magnitud (BTC vs. memecoins)."""
    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 1:
        return f"{value:,.4f}"
    return f"{value:.8f}"


# -----------------------------------------------------------------------------
# Diario de operaciones
# -----------------------------------------------------------------------------
class TradeJournal:
    """
    Registra cada apertura/cierre en el log de operaciones (legible) y cada
    operación cerrada en un CSV (para analizar resultados con `bot.py --report`
    o con Excel/pandas).
    """

    CSV_FIELDS = [
        "closed_at", "opened_at", "mode", "symbol", "asset_class", "qty",
        "entry_price", "exit_price", "notional", "gross_pnl", "fees", "net_pnl",
        "return_pct", "r_multiple", "exit_reason", "holding_minutes",
    ]

    def __init__(self, log_dir: Path, paper: bool):
        self.mode = "PAPER" if paper else "LIVE"
        self.csv_path = log_dir / f"{'paper' if paper else 'live'}_trades.csv"
        self.log = logging.getLogger(TRADE_LOGGER_NAME)
        log_dir.mkdir(parents=True, exist_ok=True)

    def log_open(self, *, symbol: str, qty: float, price: float, stop: float,
                 take_profit: float | None, notional: float, fee: float, reason: str) -> None:
        tp_txt = fmt_price(take_profit) if take_profit else "—"
        self.log.info(
            "[%s] ABRIR  | %-9s | qty=%s @ %s | SL=%s | TP=%s | nominal=%s | comisión=%s | %s",
            self.mode, symbol, f"{qty:.8g}", fmt_price(price), fmt_price(stop), tp_txt,
            fmt_money(notional), fmt_money(fee), reason,
        )

    def log_close(self, row: dict[str, Any]) -> None:
        self.log.info(
            "[%s] CERRAR | %-9s | qty=%s @ %s | PnL neto=%+.2f (%+.2f%%, %+.2fR) | motivo=%s | %.0f min",
            self.mode, row["symbol"], f"{row['qty']:.8g}", fmt_price(row["exit_price"]),
            row["net_pnl"], row["return_pct"], row["r_multiple"], row["exit_reason"],
            row["holding_minutes"],
        )
        self._append_csv({**row, "mode": self.mode})

    def log_event(self, message: str) -> None:
        self.log.info("[%s] %s", self.mode, message)

    def _append_csv(self, row: dict[str, Any]) -> None:
        try:
            new_file = not self.csv_path.exists()
            with open(self.csv_path, "a", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=self.CSV_FIELDS, extrasaction="ignore")
                if new_file:
                    writer.writeheader()
                writer.writerow(row)
        except OSError as exc:  # el bot no debe caerse por no poder escribir el CSV
            logger.error("No se pudo escribir %s: %s", self.csv_path, exc)
