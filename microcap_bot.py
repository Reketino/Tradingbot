import os
import time
import json
import threading
from collections import deque
import ccxt
import websocket


SYMBOL = "DOGE/USDT"
TRADE_AMOUNT_USDT = 0.5
VOLUME_WINDOW_SECONDS = 30
HISTORICAL_WINDOW_SECONDS = 300
VOLUME_SPIKE_THRESHOLD = 3.0 
TP_PERCENT = 0.05    
SL_PERCENT = 0.03



api_key = os.getenv("BINANCE_APIKEY")
secret = os.getenv("BINANCE_SECRET")


if not api_key or not secret:
    raise SystemExit("Mangler API-nøkler. Sett BINANCE_APIKEY og BINANCE_SECRET i miljøvariabler.")


exchange = ccxt.binance({
    "apiKey":api_key,
    "secret": secret,
})
exchange.set_sandbox_mode(True)


trade_queue = deque()
open_position = None
lock = threading.lock()


ws_symbol = SYMBOL.replace("/", "").lower()


def on_message(ws, message):
    data = json.loads(message)
    payload = data.get("data", data)


    price = float(payload.get("p", 0))
    qty = float(payload.get("q", 0))
    ts = int(payload.get("T", time.time() * 1000)) / 1000


    with lock:
        trade_queue.append((ts, qty, price))
        cutoff = time.time() - HISTORICAL_WINDOW_SECONDS
        while trade_queue and trade_queue [0][0]< cutoff:
            trade_queue.popleft()



def start_websocket():
    stream = f"{ws_symbol}@trade"
    url = f"wss://stream.binance.com:9443/ws/{stream}"
    ws = websocket.WebSocketApp(
        url,
        on_message=on_message
    )
    ws.run_forever(ping_interval=20, ping_timeout=10)



def compute_volume(window):
    now = time.time()
    total = 0
    with lock:
        for ts, qty, price in trade_queue:
            if ts >= now-window:
                total += qty * price
    return total



def place_market_order(side, symbol, usdt_amount):
    ticker = exchange.fetch_ticker(symbol)
    price = ticker["last"]
    amount = usdt_amount / price
    amount = exchange.amount_to_precision(symbol, amount)


    try:
        if side == "buy":
            order = exchange.create_market_buy_order(symbol, amount)
        else:
            order = exchange.amount_to_precision(symbol, amount)


        print (f"order ({side.upper()}):", order)
        return order
    except Exception as e:
        print("Order error:", e)
        return None 
