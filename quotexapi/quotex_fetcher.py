import asyncio
import csv
from datetime import datetime
from pyquotex import Quotex
import os

# Configuration
ASSET = "BTCUSD"  # Quotex OTC asset (e.g., BTCUSD, ETHUSD)
HISTORICAL_CANDLES = 1000  # Number of historical candles to fetch
CSV_FILE = "quotex_otc_data.csv"

async def main():
    # Initialize Quotex client
    client =Quotex(email="your_email", password="your_password")
    await client.connect()
    logged_in = await client.login()
    
    if not logged_in:
        print("Login failed!")
        await client.close()
        return

    # Fetch historical data
    historical_data = await client.get_candles(ASSET, interval=60, count=HISTORICAL_CANDLES)
    
    # Save historical data to CSV
    with open(CSV_FILE, "w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["timestamp", "open", "high", "low", "close"])
        for candle in historical_data:
            writer.writerow([
                candle["from"],  # Timestamp
                candle["open"],
                candle["high"],
                candle["low"],
                candle["close"]
            ])
    print(f"Saved {len(historical_data)} historical candles to {CSV_FILE}.")

    # Stream real-time data and append to CSV
    await client.subscribe_realtime_candles(ASSET)
    print("Streaming real-time data...")
    
    try:
        async for candle in client.realtime_candles:
            if candle["asset"] == ASSET:
                # Append new candle to CSV
                with open(CSV_FILE, "a", newline="") as file:
                    writer = csv.writer(file)
                    writer.writerow([
                        candle["from"],
                        candle["open"],
                        candle["high"],
                        candle["low"],
                        candle["close"]
                    ])
                print(f"Updated CSV with new candle: {candle}")
    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run (main())