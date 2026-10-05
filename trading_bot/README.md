# Bot de trading por sentimiento (Risk-First)

Bot modular en Python para **day trading / scalping** en acciones USA (Alpaca) y criptomonedas
(Binance o Kraken). Las noticias financieras en tiempo real son el **catalizador** y los
indicadores técnicos la **confirmación**. El objetivo son micro-beneficios consistentes y,
por encima de todo, la **preservación del capital**.

> ⚠️ **Aviso.** Este software es una herramienta educativa y no constituye asesoramiento
> financiero. Operar en mercados conlleva riesgo de pérdida. Ningún bot garantiza beneficios:
> úsalo primero en modo simulación (`PAPER_TRADING = True`, el valor por defecto) durante
> semanas y analiza los resultados antes de arriesgar dinero real.

---

## Índice

1. [Cómo funciona](#1-cómo-funciona)
2. [Estructura del proyecto](#2-estructura-del-proyecto)
3. [Gestión de riesgo con números](#3-gestión-de-riesgo-con-números)
4. [Instalación](#4-instalación)
5. [Registrar las claves API](#5-registrar-las-claves-api)
6. [Configurar el archivo .env](#6-configurar-el-archivo-env)
7. [Ejecutar en local](#7-ejecutar-en-local)
8. [Ejecutar en un VPS (24/7)](#8-ejecutar-en-un-vps-247)
9. [Pasar a dinero real (checklist)](#9-pasar-a-dinero-real-checklist)
10. [Logs, estado y resultados](#10-logs-estado-y-resultados)
11. [Personalización](#11-personalización)
12. [Limitaciones conocidas](#12-limitaciones-conocidas)
13. [Solución de problemas](#13-solución-de-problemas)

---

## 1. Cómo funciona

```
 Noticias                                                Mercado
 RSS · Alpaca News · NewsAPI · Alpha Vantage             Alpaca · Binance · Kraken
        │                                                        │ velas, bid/ask
        ▼                                                        ▼
 ┌──────────────┐    ┌──────────────┐  Score   ┌──────────┐  señal   ┌──────────────┐  plan   ┌─────────────┐
 │ news_handler │──► │  sentiment   │────────► │ strategy │────────► │ risk_manager │───────► │ api_handler │──► orden
 │ dedup + map  │    │ VADER+léxico │ -100…+100│ técnico  │          │ tamaño, SL,  │         │ real o      │   (o simulada
 │ a símbolos   │    │ financiero   │          │ confirma │          │ TP, trailing │         │ PaperBroker │    en el .log)
 └──────────────┘    └──────────────┘          └──────────┘          └──────────────┘         └─────────────┘
                              bot.py: bucle, persistencia, reconciliación y logs
```

**Cada ciclo (30 s por defecto):**

1. Lee el capital de las cuentas y gestiona el cambio de jornada.
2. Revisa las posiciones abiertas **antes que nada**: stop-loss, trailing stop, take-profit,
   tiempo máximo, cierre de mercado (acciones) y señales de salida.
3. Descarga noticias (cada proveedor con su propia frecuencia y backoff si falla).
4. Comprueba el *kill switch* de pérdida diaria.
5. Busca entradas: primero el filtro de sentimiento (sin llamadas al broker) y solo para los
   candidatos descarga velas y confirma con el análisis técnico.

### Score de Trading (sentiment.py)

Cada titular se puntúa con **VADER** ampliado con ~140 términos financieros (*surges, beats,
downgrade, hacked, bankruptcy…*) y neutralizando palabras que en finanzas no tienen carga
emocional (*shares, interest, credit…*). Sin ese ajuste, "Bitcoin surges to record high"
puntuaría 0; con él puntúa +0,86.

Las noticias de cada símbolo se agregan así:

| Concepto | Fórmula |
|---|---|
| Peso de cada noticia | `relevancia × 0,5^(antigüedad / 60 min)` (una noticia de hace 2 h pesa ¼) |
| Score medio | media ponderada del *compound* VADER ∈ [-1, 1] |
| Confianza | `min(1, Σpesos / 3) × (1 − 0,5 × dispersión)`: baja con pocas noticias o si se contradicen |
| **Score de Trading** | `100 × score × confianza` ∈ [-100, +100] → etiqueta Positivo / Negativo / Neutral |

La relevancia es 1,0 si el símbolo aparece en el titular, 0,6 si solo lo etiqueta el
proveedor y 0,5 si solo sale en el resumen.

### Estrategia (strategy.py), solo largos

**Entrada**, deben cumplirse todas:

| # | Condición | Por qué |
|---|---|---|
| 1 | Score de Trading ≥ +25 con ≥ 2 noticias | catalizador claro |
| 2 | Alguna noticia de los últimos 90 min, posterior a la última entrada | tiempo real, no repetir catalizador |
| 3 | El sentimiento del mercado no está en *risk-off* (≤ −30) | no nadar contra la marea |
| 4 | EMA 9 > EMA 21 | tendencia alcista corta |
| 5 | Precio > VWAP | dominan los compradores |
| 6 | 50 ≤ RSI ≤ 70 | momentum sin sobrecompra |
| 7 | Volumen ≥ media de 20 velas | el movimiento tiene participación |
| 8 | Spread ≤ 0,2 % y TP ≥ 2 × costes | que el beneficio no se lo coman las comisiones |

**Salida anticipada** (además de SL/TP/trailing): el Score cae a −20 o menos, o la tendencia se
rompe (EMA 9 < EMA 21 **y** precio < VWAP).

Los indicadores se calculan **solo con velas cerradas** (la vela en curso se descarta para
evitar señales que "parpadean").

---

## 2. Estructura del proyecto

```
trading_bot/
├── bot.py               # Orquestador: bucle principal, reconciliación, informe (--report)
├── api_handler.py       # Conexión con brokers: AlpacaBroker, CCXTBroker (Binance/Kraken), PaperBroker
├── strategy.py          # Señales de entrada/salida (sentimiento + técnico)
├── risk_manager.py      # Tamaño de posición, stops, trailing, kill switch, PDT, persistencia
├── sentiment.py         # VADER + léxico financiero → Score de Trading
├── news_handler.py      # Ingesta RSS / Alpaca News / NewsAPI / Alpha Vantage, deduplicación
├── indicators.py        # EMA, RSI, ATR, VWAP, ratio de volumen (pandas puro, sin TA-Lib)
├── config.py            # PAPER_TRADING (flag global) + carga y validación del .env
├── utils.py             # Logging, reintentos con backoff, JSON atómico, diario de operaciones
├── requirements.txt     # Dependencias
├── requirements-dev.txt # + pytest
├── .env.example         # Plantilla de configuración (copiar a .env)
├── deploy/
│   └── trading-bot.service   # Servicio systemd para el VPS
└── tests/               # 92 tests (sin red: brokers y noticias simulados)
```

---

## 3. Gestión de riesgo con números

Valores por defecto (todos ajustables en `.env`):

| Regla | Valor | Efecto |
|---|---|---|
| Tamaño máximo por operación | **5 % del saldo** (límite duro en código) | nunca más de 500 $ en una operación con 10.000 $ |
| Riesgo máximo por operación | **1 % del capital** | tope de pérdida al dimensionar |
| Stop-loss dinámico | 2 × ATR, acotado entre **0,5 % y 1 %** del precio | se adapta a la volatilidad, nunca más del 1 % |
| Take-profit | **1,5 R** (1,5 × distancia del stop) | beneficios pequeños pero frecuentes |
| Trailing stop | se activa con **+1 R**, sigue al precio a 0,75 R | una operación que fue +1 R ya no acaba en pérdida (salvo gaps) |
| Kill switch diario | pérdida (realizada + abierta) ≥ **2 %** | cierra todo y no opera hasta el día siguiente |
| Pérdidas seguidas | 3 → **pausa de 60 min** | evita "operar en tilt" |
| Exposición total | 15 % por cuenta, máx. 3 posiciones, 20 operaciones/día | |
| Stop temporal | 180 min | el scalping no se convierte en inversión |
| Acciones | sin entradas a < 30 min del cierre, **liquidación 10 min antes** | sin riesgo de gap nocturno |
| Protección PDT | máx. 3 day trades / 5 días si la cuenta < 25.000 $ | evita el bloqueo de FINRA |

**Ejemplo:** cuenta de 10.000 $, acción a 100 $, ATR(5 min) = 0,30 $:

- Stop = 2 × 0,30 = 0,60 $ (0,6 %) → **SL 99,40 $**, **TP 100,90 $**
- Por riesgo (1 %) podría comprar ~142 acciones, pero el **tope del 5 %** lo limita a ~5 acciones (500 $)
- Si salta el stop: pérdida ≈ 5 × (0,60 + costes) ≈ **3,5 $ = 0,035 % del capital**
- Si llega al TP: beneficio ≈ **4 $**

**Costes:** el filtro de rentabilidad exige que el TP cubra al menos 2 veces los costes de ida
y vuelta. Con comisiones del 0,1 % por lado (Binance), un scalp necesita acertar ~6 de cada 10
operaciones para ser rentable; en acciones sin comisión basta con ~47 %. Revisa estas cifras con
`python bot.py --report` antes de pasar a real.

---

## 4. Instalación

Requisitos: **Python 3.10 o superior** (probado en 3.10, 3.11, 3.12 y 3.13) y `git`.

```bash
cd trading_bot
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

Opcional, para ejecutar los tests:

```bash
pip install -r requirements-dev.txt
pytest                                # 92 tests, sin conexión a internet
```

---

## 5. Registrar las claves API

> **Regla de oro:** crea las claves **sin permiso de retirada de fondos** y, en exchanges que lo
> permitan, **restringidas a la IP** de tu VPS. Si alguien roba la clave, como mucho podrá operar,
> no llevarse el dinero.

### Alpaca (acciones USA): recomendado

1. Regístrate en <https://alpaca.markets> (la cuenta *Paper Trading* es gratuita y no requiere
   depositar dinero; desde fuera de EE. UU. también puedes abrir una cuenta paper).
2. En el panel, selecciona la cuenta **Paper** (selector arriba a la izquierda).
3. En la página de inicio, sección **API Keys** → **Generate New Keys**.
4. Copia el **API Key ID** y el **Secret Key** (el secreto solo se muestra una vez).
5. En el `.env`: `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` y `ALPACA_PAPER=true`.

Las claves de Alpaca dan acceso también a **datos de mercado** (feed IEX gratuito) y a
**Alpaca News** (Benzinga, tiempo real), que el bot usa automáticamente. Sin claves de Alpaca la
parte de acciones se desactiva y el bot sigue con cripto.

> Las claves *paper* y las *live* son distintas. `ALPACA_PAPER` debe coincidir con el tipo de clave.

### Binance (cripto)

En **modo simulación no necesitas claves**: el bot usa los datos públicos de Binance.

*Para la Testnet (pruebas con órdenes reales en sandbox):*

1. Entra en <https://testnet.binance.vision> e inicia sesión con GitHub.
2. **Generate HMAC_SHA256 Key** → copia API Key y Secret Key.
3. En el `.env`: `CRYPTO_EXCHANGE=binance`, `CRYPTO_API_KEY`, `CRYPTO_API_SECRET`, `CRYPTO_SANDBOX=true`.

*Para la cuenta real:*

1. Cuenta verificada en <https://www.binance.com>. **Recomendado:** crea una **subcuenta**
   dedicada al bot (el capital se calcula con el saldo de la cuenta).
2. Perfil → **Gestión de API** → **Crear API** → *Generada por el sistema*.
3. Permisos: ✅ *Habilitar lectura*, ✅ *Habilitar trading spot y margen*, ❌ **nunca** *Habilitar retiros*.
4. **Restringir acceso a IPs de confianza** → la IP pública de tu VPS.

> Binance.com no da servicio en algunos países (por ejemplo EE. UU.). Si recibes un error
> *451 / restricted location*, usa Kraken.

### Kraken (cripto, alternativa)

1. <https://www.kraken.com> → **Settings → API → Create API Key**.
2. Permisos: *Query Funds*, *Query Open Orders & Trades*, *Query Closed Orders & Trades*,
   *Create & Modify Orders*, *Cancel/Close Orders*. ❌ **Nunca** *Withdraw Funds*.
3. En el `.env`: `CRYPTO_EXCHANGE=kraken` y pares en USD (`CRYPTO_SYMBOLS=BTC/USD,ETH/USD`).

> Kraken **no tiene sandbox de spot**: con `PAPER_TRADING = False`, Kraken siempre es dinero real
> (el bot se niega a arrancar si pides `CRYPTO_SANDBOX=true` con Kraken).

### Noticias

| Proveedor | Registro | Plan gratuito | Notas |
|---|---|---|---|
| RSS | no requiere | ilimitado | CNBC, MarketWatch, CoinDesk, Cointelegraph, Decrypt y Yahoo Finance por ticker |
| Alpaca News | claves de Alpaca | incluido | **la mejor fuente gratuita en tiempo real** |
| NewsAPI | <https://newsapi.org/register> | 100 peticiones/día | el plan *Developer* es solo para desarrollo y sus artículos llegan con retardo |
| Alpha Vantage | <https://www.alphavantage.co/support/#api-key> | 25 peticiones/día | el bot consulta una vez por hora |

Cada proveedor se activa solo si tiene clave; no hace falta tocar `NEWS_PROVIDERS`.

---

## 6. Configurar el archivo .env

```bash
cp .env.example .env
nano .env          # rellena las claves
chmod 600 .env     # solo tu usuario puede leerlo
```

El `.env` está en `.gitignore`: **nunca lo subas a git**. Todos los parámetros de estrategia y
riesgo están documentados en `.env.example`; el bot valida los valores al arrancar y te dice
exactamente cuál es incorrecto.

**El flag de modo pruebas está en `config.py`**, no en el `.env`:

```python
PAPER_TRADING = True    # True = simulación (por defecto). Nunca envía órdenes reales.
```

---

## 7. Ejecutar en local

```bash
source .venv/bin/activate
python bot.py --once          # un ciclo de prueba: comprueba claves y conexión
python bot.py                 # bucle continuo (Ctrl+C para parar de forma ordenada)
python bot.py --report        # estadísticas de las operaciones cerradas
python bot.py --log-level DEBUG   # ver por qué se descarta cada símbolo
```

Al arrancar verás un banner con el modo (`PAPER TRADING` o `REAL`), la watchlist y los
parámetros de riesgo. En modo simulación cada compra y venta queda registrada en
`logs/paper_trades.log`:

```
2026-10-05 14:02:31 | [PAPER] ORDEN SIMULADA BUY  BTC/USDT  qty=0.00712 @ 70,135.06 (bid=70,099.99 ask=70,100.01, slippage 0.05%) comisión=0.50 | efectivo=9,500.14 USDT
2026-10-05 14:02:31 | [PAPER] ABRIR  | BTC/USDT  | qty=0.00712 @ 70,135.06 | SL=69,694.10 | TP=70,796.50 | nominal=499.36 | comisión=0.50 | sentimiento=+52 (Positivo, 3 noticias, confianza 81%) | ...
2026-10-05 14:31:02 | [PAPER] CERRAR | BTC/USDT  | qty=0.00712 @ 70,801.20 | PnL neto=+3.74 (+0.75%, +1.19R) | motivo=TAKE_PROFIT | 29 min
```

---

## 8. Ejecutar en un VPS (24/7)

Ejemplo con **Ubuntu 22.04/24.04** (vale cualquier VPS de 1 vCPU y 1 GB de RAM: Hetzner,
DigitalOcean, OVH, Contabo…).

```bash
# 1) Sistema base y usuario sin privilegios
sudo apt update && sudo apt install -y python3 python3-venv git
sudo adduser --disabled-password --gecos "" trader
sudo timedatectl set-ntp true          # reloj sincronizado (Binance rechaza peticiones con hora desfasada)
sudo ufw allow OpenSSH && sudo ufw enable

# 2) Código y entorno (como usuario trader)
sudo -iu trader
git clone <URL-de-tu-repositorio> repo && cp -r repo/trading_bot ~/trading_bot   # o súbelo con scp/rsync
cd ~/trading_bot
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env && nano .env && chmod 600 .env
.venv/bin/python bot.py --once         # prueba: debe terminar sin errores de configuración
exit

# 3) Servicio systemd (arranque automático y reinicio si se cae)
sudo cp /home/trader/trading_bot/deploy/trading-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now trading-bot

# 4) Operación diaria
sudo systemctl status trading-bot      # estado
journalctl -u trading-bot -f           # logs en vivo
tail -f /home/trader/trading_bot/logs/paper_trades.log
sudo systemctl restart trading-bot     # tras cambiar el .env o actualizar el código
sudo systemctl stop trading-bot        # parada ordenada (guarda el estado)
```

Si prefieres no usar systemd: `tmux new -s bot`, ejecuta `python bot.py` y sal con `Ctrl+B, D`.

Para actualizar: `git pull` (o copia los archivos nuevos), `pip install -r requirements.txt` y
`sudo systemctl restart trading-bot`. Las posiciones abiertas y los contadores de riesgo se
conservan en `state/`.

---

## 9. Pasar a dinero real (checklist)

Hay **tres cerrojos** entre el bot y tu dinero:

| Paso | `config.py` | `.env` | Resultado |
|---|---|---|---|
| 1. Simulación local | `PAPER_TRADING = True` | (por defecto) | órdenes simuladas en el `.log` |
| 2. Sandbox del broker | `PAPER_TRADING = False` | `LIVE_TRADING_CONFIRMATION=ACEPTO_EL_RIESGO`, `ALPACA_PAPER=true`, `CRYPTO_SANDBOX=true` | órdenes reales en Alpaca Paper / Binance Testnet |
| 3. Dinero real | `PAPER_TRADING = False` | `ALPACA_PAPER=false` (claves live), `CRYPTO_SANDBOX=false` | **órdenes con dinero real** |

Antes del paso 3:

- [ ] Al menos 2–4 semanas en simulación con `python bot.py --report` mostrando **esperanza
      positiva** (`Esperanza por trade > 0`) y *profit factor* > 1,2 después de comisiones.
- [ ] Una semana en el paso 2 sin errores de órdenes en `logs/bot.log`.
- [ ] Claves sin permiso de retirada y restringidas por IP.
- [ ] Subcuenta dedicada con **capital pequeño**, solo dinero que puedas permitirte perder.
- [ ] No operes a mano los mismos símbolos en la cuenta del bot.
- [ ] Revisa `logs/live_trades.log` a diario las primeras semanas.

El estado de simulación y el real se guardan en archivos distintos
(`state/risk_state_paper.json` / `state/risk_state_live.json`): las posiciones simuladas nunca
se mezclan con las reales.

---

## 10. Logs, estado y resultados

| Archivo | Contenido |
|---|---|
| `logs/bot.log` | todo el funcionamiento (rotativo, 5 × 5 MB) |
| `logs/paper_trades.log` / `live_trades.log` | **diario de operaciones**: cada orden, apertura y cierre con su motivo |
| `logs/paper_trades.csv` / `live_trades.csv` | operaciones cerradas para analizar en Excel/pandas (o con `--report`) |
| `state/risk_state_*.json` | posiciones abiertas con sus stops, contadores diarios, cooldowns |
| `state/paper_*.json` | saldo y posiciones de la cuenta simulada |

Para **reiniciar la simulación desde cero**, borra `state/` (y opcionalmente `logs/`). Para cambiar
el capital simulado usa `PAPER_INITIAL_CASH_STOCKS` / `PAPER_INITIAL_CASH_CRYPTO` antes de la
primera ejecución.

---

## 11. Personalización

- **Añadir símbolos:** amplía `STOCK_SYMBOLS` / `CRYPTO_SYMBOLS` en el `.env` y añade sus
  nombres al diccionario `DEFAULT_KEYWORDS` de `config.py` (por ejemplo `"COIN": ["coinbase"]`)
  para que las noticias se asocien correctamente.
- **Más o menos agresivo:** `ENTRY_SCORE`, `TAKE_PROFIT_RR`, `ATR_STOP_MULTIPLIER`,
  `MAX_POSITION_PCT` (máximo 0,05).
- **Solo trailing, sin TP fijo:** `TAKE_PROFIT_RR=0`.
- **Otra temporalidad:** `BAR_TIMEFRAME=1m|5m|15m|30m|1h`.
- **Otro broker:** implementa la interfaz `BaseBroker` de `api_handler.py` (7 métodos) y
  añádelo en `build_brokers()`. Estrategia y riesgo no cambian.
- **Mejor NLP:** sustituye `SentimentAnalyzer.score_text()` por FinBERT (`transformers`), con
  el mismo contrato: devolver un valor en [-1, 1].

---

## 12. Limitaciones conocidas

- **Los stops los gestiona el bot**, no son órdenes stop en el broker. Si el bot o el VPS se
  caen, la posición queda sin vigilancia hasta que vuelva (systemd lo reinicia en 15 s y el
  estado se restaura). Un *gap* brusco puede ejecutar el stop peor de lo previsto.
- **VADER es un léxico**: no entiende ironía ni matices ("beats estimates but guidance
  disappoints"). La confirmación técnica y la exigencia de varias noticias mitigan errores.
- **Latencia de noticias:** los RSS publican con minutos de retraso. El bot no compite con
  fondos de alta frecuencia; busca movimientos que duran decenas de minutos.
- **Solo posiciones largas.** El sentimiento negativo se usa para no entrar y para salir.
- **Sin backtesting histórico**: la validación es *forward testing* en simulación. El
  `PaperBroker` aplica spread, slippage y comisiones para que sea realista.
- En cripto, el capital se calcula como saldo en la divisa de cotización + valor de los
  activos de la watchlist: usa una **subcuenta** dedicada.

---

## 13. Solución de problemas

| Mensaje | Causa / solución |
|---|---|
| `ACCIONES DESACTIVADAS: faltan ALPACA_API_KEY…` | sin claves de Alpaca; el bot sigue solo con cripto |
| `Error de configuración: X=… debe ser…` | valor inválido en el `.env`; el mensaje indica cuál |
| `PAPER_TRADING=False pero falta LIVE_TRADING_CONFIRMATION` | cerrojo de seguridad: ver sección 9 |
| `binance … 451` / `restricted location` | Binance no opera en tu país/IP: usa `CRYPTO_EXCHANGE=kraken` |
| `Timestamp for this request is outside of the recvWindow` | reloj desfasado: `sudo timedatectl set-ntp true` |
| `Noticias alphavantage falló … rate limit` | cuota diaria agotada; el bot aplica backoff y sigue con el resto de fuentes |
| `Feed RSS … no disponible` | el feed está caído o cambió de URL; sustitúyelo con `RSS_FEEDS` |
| `candidato descartado — … el técnico no confirma (…)` | normal: el sentimiento acompaña pero el precio no. Es el filtro funcionando |
| `protección PDT` | cuenta de acciones < 25.000 $ con 3 day trades en 5 días; espera o usa cripto |
| El bot no abre operaciones | ejecuta con `--log-level DEBUG` para ver el motivo exacto por símbolo |
