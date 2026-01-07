"""
Generate sample SUIUSDT data for backtesting
"""

import random
from datetime import datetime, timedelta

import numpy as np
import pandas as pd


def generate_sui_data(days: int = 365, start_price: float = 3.50) -> pd.DataFrame:
    """
    Generate sample SUIUSDT data for backtesting

    Args:
        days: Number of days to generate
        start_price: Starting price for SUI

    Returns:
        DataFrame with OHLCV data
    """

    # Generate timestamps (1-minute intervals)
    start_date = datetime.now() - timedelta(days=days)
    timestamps = pd.date_range(start=start_date, periods=days * 24 * 60, freq='1min')

    # Generate price data using geometric Brownian motion
    n_points = len(timestamps)
    dt = 1 / (24 * 60)  # 1 minute in days

    # Parameters for price simulation
    mu = 0.0001  # Daily drift (slight upward trend)
    sigma = 0.02  # Daily volatility

    # Generate random returns
    returns = np.random.normal(mu * dt, sigma * np.sqrt(dt), n_points)

    # Calculate prices
    prices = [start_price]
    for ret in returns[1:]:
        prices.append(prices[-1] * (1 + ret))

    # Generate OHLC data
    data = []
    for i, (timestamp, price) in enumerate(zip(timestamps, prices)):
        # Add some intraday volatility
        volatility = 0.001 + 0.002 * np.random.random()  # 0.1% to 0.3%

        # Generate OHLC
        open_price = price
        close_price = price * (1 + np.random.normal(0, volatility))

        # High and low
        high_price = max(open_price, close_price) * (1 + np.random.random() * volatility)
        low_price = min(open_price, close_price) * (1 - np.random.random() * volatility)

        # Volume (random but realistic)
        volume = 1000 + np.random.exponential(500)

        data.append({
            'time': timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            'open': round(open_price, 4),
            'high': round(high_price, 4),
            'low': round(low_price, 4),
            'close': round(close_price, 4),
            'volume': round(volume, 2)
        })

        # Update price for next iteration
        price = close_price

    return pd.DataFrame(data)


def add_market_events(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add realistic market events (gaps, trends, volatility clusters)
    """
    df = df.copy()

    # Add some price gaps (market opens)
    gap_indices = np.random.choice(len(df), size=50, replace=False)
    for idx in gap_indices:
        if idx > 0:
            gap_size = np.random.normal(0, 0.01)  # 1% gap
            df.loc[idx:, ['open', 'high', 'low', 'close']] *= (1 + gap_size)

    # Add volatility clusters
    cluster_indices = np.random.choice(len(df), size=20, replace=False)
    for idx in cluster_indices:
        cluster_length = np.random.randint(60, 300)  # 1-5 hours
        end_idx = min(idx + cluster_length, len(df))

        # Increase volatility in this cluster
        for i in range(idx, end_idx):
            if i < len(df):
                volatility_multiplier = 2.0 + np.random.random()
                df.loc[i, 'high'] *= (1 + np.random.random() * 0.005 * volatility_multiplier)
                df.loc[i, 'low'] *= (1 - np.random.random() * 0.005 * volatility_multiplier)

    return df


def main():
    """Generate and save sample data"""
    print("Generating SUIUSDT sample data...")

    # Generate 1 year of data
    df = generate_sui_data(days=365, start_price=3.50)

    # Add market events
    df = add_market_events(df)

    # Save to CSV
    output_file = "sui_usdt_1m_sample.csv"
    df.to_csv(output_file, index=False)

    print(f"Generated {len(df)} candles")
    print(f"Date range: {df['time'].iloc[0]} to {df['time'].iloc[-1]}")
    print(f"Price range: ${df['low'].min():.4f} - ${df['high'].max():.4f}")
    print(f"Saved to: {output_file}")

    # Show sample
    print("\nSample data:")
    print(df.head(10))


if __name__ == "__main__":
    main()
