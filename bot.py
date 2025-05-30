import logging
from flask import Flask, render_template_string, request, jsonify
import threading
import asyncio
import time
import pandas as pd
from datetime import datetime
from quotexapi.stable_api import Quotex
import os

# Global state
client = None
bot_thread = None
log_records = []
bot_paused = False

# Trading settings
CANDLE_INTERVAL       = 60
TRADE_DURATION        = 60
SCAN_INTERVAL         = 0.2
LOOK_BACK_BARS        = 6
MARTINGALE_MULTIPLIER = 2
QUALITY_THRESHOLD     = 0.0005
RETRY_DELAY           = 500

class TradingBot:
    def __init__(self, config):
        self.config = config
        self._pause_event = threading.Event()
        self._stop_event = threading.Event()
    
    def pause(self):
        self._pause_event.set()
    
    def resume(self):
        self._pause_event.clear()
    
    def stop(self):
        self._stop_event.set()
    
    def run(self):
        asyncio.run(self._run())
    
    async def _run(self):
        global client, bot_paused
        
        email = self.config['email']
        password = self.config['password']
        mode = self.config['mode']
        symbol = self.config['symbol']
        amount = self.config['amount']
        logger = self.config['logger']
        
        client = Quotex(email=email, password=password, lang="en")
        logger("Starting login...", "info")
        await self.silent_login(client)
        try:
            client.change_account(mode)
        except:
            logger("Failed to set account mode", "error")
        try:
            bal = await client.get_balance()
            logger(f"Balance: ${bal:.2f}", "info")
        except:
            logger("Failed to fetch balance", "error")
        logger(f"Bot running on {symbol} @ ${amount:.2f}", "success")
        await self.trading_cycle(symbol, amount, logger)
    
    async def silent_login(self, cli: Quotex):
        while True:
            try:
                if await cli.connect():
                    log("Login successful", "success")
                    return
            except Exception as e:
                log(f"Login error: {e}", "error")
            log(f"Retrying login in {RETRY_DELAY}s...", "warning")
            await asyncio.sleep(RETRY_DELAY)
    
    async def fetch_candles(self, asset, interval, lookback):
        end_ts = int(time.time() // interval * interval)
        raw = await client.get_candles(asset, end_ts, lookback, interval)
        if not raw:
            return None
        return list(reversed([
            {'open': float(c['open']), 'high': float(c['high']),
             'low': float(c['low']),   'close': float(c['close'])}
            for c in raw
        ]))
    
    async def execute_trade(self, asset, amount, direction, logger):
        ok, info = await client.buy(amount, asset, direction, TRADE_DURATION)
        if not ok:
            return 'Error'
        await asyncio.sleep(TRADE_DURATION - 2)
        prices = await client.get_realtime_price(asset)
        if not prices:
            return 'Error'
        final = prices[-1]['price']
        if final == info['openPrice']:
            return 'Draw'
        win = (direction=='call' and final>info['openPrice']) or \
              (direction=='put'  and final<info['openPrice'])
        return 'Win' if win else 'Loss'
    
    async def trading_cycle(self, symbol, base_amount, logger):
        global bot_paused
        
        multiplier = 1
        while True:
            # Check if paused
            if bot_paused:
                await asyncio.sleep(1)
                continue
            
            # wait next candle
            now = int(time.time())
            nxt = (now//CANDLE_INTERVAL+1)*CANDLE_INTERVAL
            await asyncio.sleep(max(0, nxt-now))

            candles = await self.fetch_candles(symbol, CANDLE_INTERVAL, LOOK_BACK_BARS)
            if not candles or len(candles)<LOOK_BACK_BARS:
                await asyncio.sleep(SCAN_INTERVAL)
                continue

            df = pd.DataFrame(candles)
            df['ma3'] = df['close'].rolling(3).mean()
            df['ma6'] = df['close'].rolling(6).mean()
            ma3, ma6 = df.iloc[-1][['ma3','ma6']]
            if pd.isna(ma3) or pd.isna(ma6):
                continue

            diff = abs(ma3-ma6)
            if diff < QUALITY_THRESHOLD:
                logger(f"Weak signal ΔMA={diff:.6f}", "warning")
                continue

            direction = 'call' if ma3>ma6 else 'put'
            logger(f"Signal: {direction.upper()} Δ={diff:.6f}", "info")

            amount = base_amount * multiplier
            result = await self.execute_trade(symbol, amount, direction, logger)
            
            if result == 'Win':
                logger(f"Trade {direction.upper()} ${amount:.2f} → {result}", "trade_up")
            elif result == 'Loss':
                logger(f"Trade {direction.upper()} ${amount:.2f} → {result}", "trade_down")
            else:
                logger(f"Trade {direction.upper()} ${amount:.2f} → {result}", "info")

            if result=='Loss':
                multiplier *= MARTINGALE_MULTIPLIER
                logger(f"Martingale → next stake ${base_amount*multiplier:.2f}", "warning")
            else:
                multiplier = 1

            await asyncio.sleep(SCAN_INTERVAL)

def log(msg: str, msg_type: str = 'info'):
    timestamp = datetime.now().strftime("%H:%M:%S")
    
    # تقليل طول الرسائل الطويلة
    if len(msg) > 150:
        msg = msg[:150] + "..."
    
    # إضافة ألوان حسب نوع الرسالة
    if msg_type == 'success':
        colored_msg = f"[{timestamp}] \\033[92m{msg}\\033[0m"  # أخضر
    elif msg_type == 'error':
        colored_msg = f"[{timestamp}] \\033[91m{msg}\\033[0m"  # أحمر
    elif msg_type == 'warning':
        colored_msg = f"[{timestamp}] \\033[93m{msg}\\033[0m"  # أصفر
    elif msg_type == 'trade_up':
        colored_msg = f"[{timestamp}] \\033[94m▲ UP: {msg}\\033[0m"  # أزرق فاتح
    elif msg_type == 'trade_down':
        colored_msg = f"[{timestamp}] \\033[95m▼ DOWN: {msg}\\033[0m"  # أرجواني
    elif msg_type == 'profit':
        colored_msg = f"[{timestamp}] \\033[92m💰 {msg}\\033[0m"  # أخضر
    elif msg_type == 'loss':
        colored_msg = f"[{timestamp}] \\033[91m💸 {msg}\\033[0m"  # أحمر
    else:
        colored_msg = f"[{timestamp}] {msg}"
    
    log_records.append(colored_msg)
    if len(log_records) > 200:
        log_records.pop(0)

app = Flask(__name__)

@app.route('/pause', methods=['POST'])
def pause_bot():
    global bot_paused
    bot_paused = True
    log("تم إيقاف البوت مؤقتاً", "warning")
    return jsonify(success=True, message="Bot paused")

@app.route('/resume', methods=['POST'])
def resume_bot():
    global bot_paused
    bot_paused = False
    log("تم استئناف عمل البوت", "success")
    return jsonify(success=True, message="Bot resumed")

@app.route('/logs', methods=['GET'])
def get_logs():
    return jsonify(logs=log_records)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)