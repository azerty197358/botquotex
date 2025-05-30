import asyncio
import time
import websocket
import numpy as np
import pandas as pd
from finta import TA
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from quotexapi.config import credentials
from quotexapi.stable_api import Quotex

console = Console()

# Constants
TRADE_DURATION = 60  # مدة الصفقة 60 ثانية لكل صفقة
ACTIVATION_CODE = "X7B9-KD3P-2YQL-V6TZ"  # ضع هنا كود التفعيل الصحيح

# استرجاع بيانات الاعتماد الخاصة بك لـ Quotex
email, password = credentials()

# إنشاء العميل الخاص بـ Quotex
client = Quotex(
    email=email,
    password=password,
    lang="en",  # استخدام اللغة الإنجليزية
)

def detect_correction_candle(candles):
    """
    تحليل آخر شمعتين لتحديد ما إذا كانت الشمعة الحالية تُعتبر شمعة تصحيح.
    - إذا كانت الشمعة السابقة صعودية والشمعة الحالية هبوطية صغيرة (أقل من 50% من نطاق الشمعة السابقة)،
      فهذا يعني وجود تصحيح داخل اتجاه صعودي -> نختار "call".
    - إذا كانت الشمعة السابقة هبوطية والشمعة الحالية صعودية صغيرة، فهذا يعني وجود تصحيح داخل اتجاه هبوطي -> نختار "put".
    """
    if len(candles) < 2:
        return None

    prev = candles[-2]
    curr = candles[-1]

    prev_range = prev['high'] - prev['low']
    curr_body = abs(curr['close'] - curr['open'])

    if prev['close'] > prev['open']:
        if curr['open'] > curr['close'] and curr_body < 0.5 * prev_range:
            return "call"
    elif prev['close'] < prev['open']:
        if curr['close'] > curr['open'] and curr_body < 0.5 * prev_range:
            return "put"

    return None

async def analyze_sentiment(asset_name: str, duration: int):
    """
    استرجاع وعرض توجه السوق في الوقت الحقيقي للمدة المحددة.
    """
    count = duration
    while count > 0:
        market_mood = await client.get_realtime_sentiment(asset_name)
        sentiment = market_mood.get('sentiment')
        if sentiment:
            console.print(
                f"[bold cyan]Sell:[/bold cyan] {sentiment.get('sell')}  [bold green]Buy:[/bold green] {sentiment.get('buy')}",
                end="\r"
            )
        await asyncio.sleep(0.5)
        count -= 1

async def calculate_profit(asset_name: str, amount: float, balance: float):
    """
    حساب الربح بناءً على العائد للأصل.
    """
    payout = client.get_payout_by_asset(asset_name)
    profit = ((payout / 100) * amount)
    balance += amount + profit
    return balance, profit

async def countdown_and_check(buy_data: dict, direction: str, duration: int = 60):
    """
    بعد فتح الصفقة، يتم العد تنازليًا لمدة دقيقة مع مراجعة السعر كل ثانية.
    يتم التحقق من النتيجة عند انتهاء المدة.
    """
    open_price = buy_data.get('openPrice')
    if open_price is None:
        console.print("[red]Missing open price data.[/red]")
        return 'NoData'
        
    for remaining in range(duration, 0, -1):
        prices = await client.get_realtime_price(buy_data['asset'])
        current_price = prices[-1]['price'] if prices else None
        console.print(f"[bold yellow]Time remaining: {remaining} seconds - Current Price: {current_price}[/bold yellow]", end="\r")
        await asyncio.sleep(1)
    
    console.print("\n[bold yellow]Time's up! Checking final result...[/bold yellow]")
    prices = await client.get_realtime_price(buy_data['asset'])
    if not prices:
        console.print("[red]No price data available to check result[/red]")
        return 'NoData'
    final_price = prices[-1]['price']
    console.print(f"[bold yellow]Final Price:[/bold yellow] {final_price}  [bold blue]Open Price:[/bold blue] {open_price}")
    
    if (direction == "call" and final_price > open_price) or (direction == "put" and final_price < open_price):
        console.print("[bold green]Result: WIN[/bold green]")
        return 'Win'
    elif (direction == "call" and final_price <= open_price) or (direction == "put" and final_price >= open_price):
        console.print("[bold red]Result: LOSS[/bold red]")
        return 'Loss'
    else:
        console.print("[bold magenta]Result: DOJI[/bold magenta]")
        return 'Doji'

async def get_last_thirty_candles(asset: str, candle_size: int = 60):
    """
    استرجاع آخر 30 شمعة للأصل باستخدام واجهة Quotex.
    (كل شمعة تمثل دقيقة واحدة افتراضياً)
    """
    max_reconnect_attempts = 3
    reconnect_delay = 2  # ثواني
    for attempt in range(1, max_reconnect_attempts + 1):
        try:
            end_from_time = int(time.time())
            candles = await client.get_candles(asset, end_from_time, offset=1800, period=candle_size)
            return candles[-30:]
        except websocket._exceptions.WebSocketConnectionClosedException:
            console.print(f"[yellow]WebSocket connection closed. Reconnecting (attempt {attempt})...[/yellow]")
            await client.reconnect()
        except Exception as e:
            console.print(f"[red]Error getting candles: {str(e)}[/red]")
        if attempt < max_reconnect_attempts:
            await asyncio.sleep(reconnect_delay)
    console.print("[red]Failed to get candles after multiple attempts[/red]")
    return []

async def monitor_candles(asset_name: str, duration: int):
    """
    متابعة الشموع (كل دقيقة) واستخدام مؤشري RSI وMACD لاتخاذ قرارات التداول.
    كما يتم التحقق من ظهور شموع التصحيح للدخول في صفقة.
    يعيد 'call' أو 'put' أو None.
    """
    last_candles = await get_last_thirty_candles(asset_name, duration)
    if not last_candles:
        console.print("[red]Error getting candles. Cannot make a trading decision.[/red]")
        return None

    console.print("[bold blue]Waiting for the next candle to close...[/bold blue]")
    while True:
        current_time = int(time.time())
        time_to_next_candle = duration - (current_time % duration)
        console.print(f"[bold yellow]Time until the next candle close:[/bold yellow] {time_to_next_candle:.2f} seconds")
        await asyncio.sleep(time_to_next_candle)

        new_candles = await get_last_thirty_candles(asset_name, duration)
        if not new_candles:
            console.print("[red]Error getting new candles. Cannot make a trading decision.[/red]")
            continue

        try:
            df = pd.DataFrame(new_candles)
            if 'volume' not in df.columns:
                df['volume'] = 0

            # حساب مؤشر RSI
            rsi_series = TA.RSI(df)
            last_rsi = rsi_series.iloc[-1] if not rsi_series.empty else None

            # حساب مؤشر MACD
            macd_df = TA.MACD(df)
            if not macd_df.empty:
                last_macd = macd_df.iloc[-1]["MACD"]
                last_signal = macd_df.iloc[-1]["SIGNAL"]
            else:
                last_macd, last_signal = None, None

            console.print(
                f"[bold cyan]RSI:[/bold cyan] {last_rsi}  [bold magenta]MACD:[/bold magenta] {last_macd}  [bold magenta]Signal:[/bold magenta] {last_signal}"
            )
        except Exception as e:
            console.print(f"[red]Error calculating indicators with Finta: {e}[/red]")
            last_rsi, last_macd, last_signal = None, None, None

        if last_rsi is not None and last_macd is not None and last_signal is not None:
            if last_rsi < 30 and last_macd > last_signal:
                direction = "call"
                console.print("[bold green]Strong Buy signal: RSI < 30 and MACD crossing upward.[/bold green]")
            elif last_rsi > 70 and last_macd < last_signal:
                direction = "put"
                console.print("[bold red]Strong Sell signal: RSI > 70 and MACD crossing downward.[/bold red]")
            else:
                direction = detect_correction_candle(new_candles)
                if direction == "call":
                    console.print("[bold green]Correction candle detected in an uptrend. Entering call.[/bold green]")
                elif direction == "put":
                    console.print("[bold red]Correction candle detected in a downtrend. Entering put.[/bold red]")
                else:
                    console.print("[yellow]No clear signal detected. Skipping trade.[/bold yellow]")
        else:
            console.print("[red]Indicators could not be calculated. Skipping trade.[/bold red]")
            direction = None

        return direction

async def trade_and_monitor_asset(asset: str, trade_amount: float, initial_balance: float,
                                  stop_loss_amount: float, take_profit_amount: float):
    current_balance = await client.get_balance()
    console.print(f"[bold cyan]Initial Balance for {asset}:[/bold cyan] {current_balance}")

    asset_info = await client.get_available_asset(asset, force_open=True)
    asset_name = asset_info[0]
    asset_data = asset_info[1]
    
    if not asset_data[2]:
        console.print(f"[bold red]ERROR:[/bold red] Asset {asset} is closed.")
        return
    console.print(f"[bold green]OK:[/bold green] Asset {asset} is open.")

    # نستخدم الحساب الابتدائي كأساس للتحكم بالمخاطر
    base_balance = initial_balance

    while True:
        # قبل بدء صفقة جديدة يتم التحقق من رصيد الحساب بالنسبة للحدود المُحددة
        current_balance = await client.get_balance()
        if current_balance <= base_balance - stop_loss_amount:
            console.print(f"[bold red]Stop loss reached. Current balance: {current_balance} | Base balance: {base_balance}[/bold red]")
            break
        if current_balance >= base_balance + take_profit_amount:
            console.print(f"[bold green]Take profit target reached. Current balance: {current_balance} | Base balance: {base_balance}[/bold green]")
            break

        console.rule(f"Trading for {asset}")
        duration = TRADE_DURATION

        is_connected = await client.check_connect()
        if not is_connected:
            console.print("[yellow]Connection lost. Attempting to reconnect...[/yellow]")
            connected, message = await client.connect()
            if not connected:
                console.print("[red]Could not reconnect. Stopping trades.[/red]")
                break

        direction = await monitor_candles(asset_name, duration)
        if direction is None:
            console.print(f"[yellow]No clear trade signal for {asset}. Waiting for the next candle...[/yellow]")
            await asyncio.sleep(duration)
            continue

        console.print(f"[bold blue]Placing a trade of {trade_amount} on {asset_name} in the {direction} direction for {duration}s[/bold blue]")
        status, buy_info = await client.buy(trade_amount, asset_name, direction, duration)
        console.print(f"[bold]Trade status:[/bold] {status}  [bold]Buy info:[/bold] {buy_info}")

        if status:
            console.print(f"[bold green]Trade placed:[/bold green] {trade_amount} on {asset} in {direction} direction.")
            result = await countdown_and_check(buy_info, direction, duration)
            if result == "Win":
                current_balance, profit = await calculate_profit(asset_name, trade_amount, current_balance)
                console.print(f"[bold green]Profit for {asset}:[/bold green] {profit}")
            elif result == "Doji":
                console.print(f"[bold magenta]Result: DOJI. No profit or loss for {asset}.[/bold magenta]")
            else:
                console.print("[red]Trade lost.[/red]")
            console.print(f"[bold cyan]Balance updated: {current_balance}[/bold cyan]")
        else:
            console.print(f"[red]Operation failed for {asset}.[/red]")
        
        await asyncio.sleep(1)

async def main():
    user_activation_code = console.input("[bold]Enter activation code: [/bold]").strip()
    if user_activation_code != ACTIVATION_CODE:
        console.print("[red]Invalid activation code. Exiting...[/red]")
        return

    telegram_channel = "https://t.me/Quotex_Signals_Tradings"  # استبدل الرابط برابط قناتك الفعلي
    console.print(Panel(f"[bold green]Welcome![/bold green]\nFor support and inquiries, please join our Telegram channel:\n[bold blue]{telegram_channel}[/bold blue]",
                        title="Telegram Channel", expand=False))
    
    account_type = console.input("[bold]Select account type (practice or real): [/bold]").strip().lower()

    try:
        trade_amount = float(console.input("[bold]Enter trade amount per trade: [/bold]"))
    except ValueError:
        console.print("[red]Invalid amount. Defaulting to 1.0[/red]")
        trade_amount = 1.0

    try:
        stop_loss_amount = float(console.input("[bold]Enter maximum loss amount (stop loss): [/bold]"))
    except ValueError:
        console.print("[red]Invalid input. Defaulting stop loss to 10.0[/red]")
        stop_loss_amount = 10.0

    try:
        take_profit_amount = float(console.input("[bold]Enter profit target amount (take profit): [/bold]"))
    except ValueError:
        console.print("[red]Invalid input. Defaulting take profit to 10.0[/red]")
        take_profit_amount = 10.0

    connected, message = await client.connect()
    if not connected:
        console.print("[red]Could not connect to Quotex. Please check your credentials or network.[/red]")
        return

    if account_type == "real":
        client.change_account("REAL")
        console.print("[green]Using REAL account.[/green]")
    else:
        client.change_account("PRACTICE")
        console.print("[green]Using PRACTICE (demo) account.[/green]")

    # الحصول على الحساب الابتدائي لتحديد حدود وقف الخسارة وجني الأرباح
    initial_balance = await client.get_balance()

    asset_list = ["EURUSD", "AUDUSD"]
    tasks = []
    for asset in asset_list:
        tasks.append(asyncio.create_task(
            trade_and_monitor_asset(asset, trade_amount, initial_balance, stop_loss_amount, take_profit_amount)
        ))
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        console.print("\n[bold red]Closing the program.[/bold red]")
    finally:
        loop.close()
