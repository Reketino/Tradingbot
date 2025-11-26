import os
import time
import json
import threading
from collections import deque
import ccxt
import websocket

# ----------- CONFIG --------
SYMBOL = "DOGE/USDT"          
TRADE_AMOUNT_USDT = 0.5           # ~5kr per trade
VOLUME_WINDOW_SECONDS = 30
HISTORICAL_WINDOW_SECONDS = 300
VOLUME_SPIKE_THRESHOLD = 3.0     # 3x volum = kjøp
TP_PERCENT = 0.05                 # 5% stigning tar han profitten
SL_PERCENT = 0.03                 # 3% stopper tap


# ---------- OPPSETT CCXT --------
api_key = os.getenv("BINANCE_APIKEY")
secret = os.getenv("BINANCE_SECRET")


if not api_key or not secret:
    raise SystemExit("Mangler API-nøkler. Sett BINANCE_APIKEY og BINANCE_SECRET i miljøvariabler.")


exchange = ccxt.binance({
    "apiKey":api_key,
    "secret": secret,
})
exchange.set_sandbox_mode(True)

# Bruk kø for handelhistorikk
trade_queue = deque()
open_position = None
lock = threading.Lock()

#----------- WEBSOCKET -----------
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
        while trade_queue and trade_queue[0][0]< cutoff:
            trade_queue.popleft()



def start_websocket():
    stream = f"{ws_symbol}@trade"
    url = f"wss://stream.binance.com:9443/ws/{stream}"
    ws = websocket.WebSocketApp(
        url,
        on_message=on_message
    )
    ws.run_forever(ping_interval=20, ping_timeout=10)


#------------Hjelper----------
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
            order = exchange.create_market_sell_order(symbol, amount)


        print (f"order ({side.upper()}):", order)
        return order
    except Exception as e:
        print("Order error:", e)
        return None 
    
#----------- Hvoed loopen ---------
def main_loop():
    global open_position


    while True:
        vol_recent = compute_volume(VOLUME_WINDOW_SECONDS)
        vol_hist = compute_volume(HISTORICAL_WINDOW_SECONDS)
        hist_avg = vol_hist / max(1, (HISTORICAL_WINDOW_SECONDS/VOLUME_WINDOW_SECONDS))

     
        print(f"[INFO] Recent vol=>{vol_recent:.4f}, Hist avg={hist_avg:.4f}")


        # Kjøper når coin "spiker"
        if hist_avg > 0 and vol_recent > VOLUME_SPIKE_THRESHOLD * hist_avg:
            print("🔥 Volume spike oppdaget!")


            if open_position is None:
                buy = place_market_order("buy", SYMBOL, TRADE_AMOUNT_USDT)
                if buy:
                    entry = float(buy.get("average") or buy.get("price") or 0)
                    open_position = {
                        "entry": entry,
                        "size": float(buy["amount"])
                    }
                    print("📈 Åpen posisjon", open_position)
            else:
                print("Allerede i posisjon, kjøper ikke")

            
        # Håndtering av eksisterende posisjoner
        if open_position:
            ticker = exchange.fetch_ticker(SYMBOL)
            last = ticker["last"]


            change = (last - open_position["entry"]) / open_position["entry"]
            print(f"[POS] P/L: {change*100:.2f}%")


            if change >= TP_PERCENT or change <= -SL_PERCENT:
                side = "sell"
                place_market_order(side, SYMBOL, TRADE_AMOUNT_USDT)
                print("💰 Posisjon stengt (TP/SL hit)")
                open_position = None


        time.sleep(2)


#----------- Start ----------

if __name__ == "__main__":
    t = threading.Thread(target=start_websocket, daemon=True)
    t.start()
    main_loop()
   