"""
SUI Market Making Backtester
Based on the backtesting framework discussion
"""

import argparse
import logging
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


class SUIMarketMakingBacktester:
    """
    Backtester for SUI Market Making Strategy

    Features:
    - Candles-only simulation
    - Spread-based quoting
    - Volatility adjustment
    - Inventory skew
    - Risk controls
    - Performance metrics
    """

    def __init__(self,
                 base_spread_bps: float = 20,
                 vol_window: int = 60,
                 vol_k: float = 1.5,
                 max_inventory: float = 1000,
                 skew_k: float = 0.5,
                 order_size: float = 100,
                 fee_bps: float = 10):
        """
        Initialize backtester

        Args:
            base_spread_bps: Base spread in basis points
            vol_window: Volatility calculation window (minutes)
            vol_k: Volatility multiplier
            max_inventory: Maximum inventory
            skew_k: Inventory skew factor
            order_size: Order size
            fee_bps: Trading fee in basis points
        """
        self.base_spread_bps = base_spread_bps
        self.vol_window = vol_window
        self.vol_k = vol_k
        self.max_inventory = max_inventory
        self.skew_k = skew_k
        self.order_size = order_size
        self.fee_bps = fee_bps

        # State variables
        self.inventory = 0.0
        self.cash = 10000.0  # Starting cash
        self.equity = 10000.0
        self.max_equity = 10000.0
        self.trades_count = 0
        self.total_pnl = 0.0
        self.total_fees = 0.0

        # Price tracking
        self.last_price = None
        self.price_history = []
        self.volatility = 0.0

        # Results tracking
        self.equity_curve = []
        self.trade_log = []
        self.inventory_curve = []

        # Risk management
        self.max_drawdown = 0.0
        self.current_drawdown = 0.0

    def load_data(self, csv_path: str) -> pd.DataFrame:
        """Load historical data from CSV"""
        try:
            df = pd.read_csv(csv_path)

            # Ensure required columns exist
            required_cols = ['time', 'open', 'high', 'low', 'close']
            if not all(col in df.columns for col in required_cols):
                raise ValueError(f"Missing required columns. Need: {required_cols}")

            # Convert time to datetime
            df['time'] = pd.to_datetime(df['time'])
            df = df.sort_values('time').reset_index(drop=True)

            # Add volume if not present
            if 'volume' not in df.columns:
                df['volume'] = 1000  # Default volume

            self.logger().info(f"Loaded {len(df)} candles from {csv_path}")
            return df

        except Exception as e:
            self.logger().error(f"Error loading data: {e}")
            raise

    def calculate_volatility(self, prices: List[float]) -> float:
        """Calculate rolling volatility"""
        if len(prices) < self.vol_window:
            return 0.0

        recent_prices = prices[-self.vol_window:]
        returns = np.diff(recent_prices) / np.array(recent_prices[:-1])
        return np.std(returns) * np.sqrt(60)  # Annualized

    def calculate_spread(self) -> float:
        """Calculate spread based on volatility"""
        base_spread = self.base_spread_bps / 10000  # Convert to decimal
        vol_adjustment = self.volatility * self.vol_k
        return base_spread + vol_adjustment

    def calculate_inventory_skew(self) -> float:
        """Calculate inventory skew factor"""
        if self.max_inventory == 0:
            return 0.0

        inventory_ratio = self.inventory / self.max_inventory
        return inventory_ratio * self.skew_k * 0.01  # 1% max skew

    def simulate_fill(self, price: float, is_buy: bool) -> bool:
        """Simulate order fill based on OHLC data"""
        # This is a simplified fill model
        # In reality, you'd need order book data for accurate simulation
        return True  # Assume all orders get filled for now

    def execute_trade(self, price: float, is_buy: bool, size: float):
        """Execute a trade"""
        # Calculate fees
        fee = size * price * (self.fee_bps / 10000)
        self.total_fees += fee

        # Update inventory and cash
        if is_buy:
            self.inventory += size
            self.cash -= (size * price + fee)
        else:
            self.inventory -= size
            self.cash += (size * price - fee)

        # Update equity
        self.equity = self.cash + self.inventory * price
        if self.equity > self.max_equity:
            self.max_equity = self.equity

        # Update trade count
        self.trades_count += 1

        # Log trade
        trade = {
            'timestamp': self.last_price,
            'price': price,
            'size': size,
            'is_buy': is_buy,
            'inventory': self.inventory,
            'cash': self.cash,
            'equity': self.equity,
            'fee': fee
        }
        self.trade_log.append(trade)

        # Update drawdown
        self.current_drawdown = (self.max_equity - self.equity) / self.max_equity
        if self.current_drawdown > self.max_drawdown:
            self.max_drawdown = self.current_drawdown

    def run_backtest(self, df: pd.DataFrame) -> Dict:
        """Run the backtest"""
        self.logger().info("Starting backtest...")

        for idx, row in df.iterrows():
            # Update price
            self.last_price = row['close']
            self.price_history.append(self.last_price)

            # Keep only recent history
            if len(self.price_history) > self.vol_window * 2:
                self.price_history = self.price_history[-self.vol_window * 2:]

            # Calculate volatility
            self.volatility = self.calculate_volatility(self.price_history)

            # Calculate spread and skew
            spread = self.calculate_spread()
            skew = self.calculate_inventory_skew()

            # Calculate bid and ask prices
            mid_price = self.last_price
            bid_price = mid_price * (1 - spread / 2 + skew)
            ask_price = mid_price * (1 + spread / 2 + skew)

            # Check for fills
            # Buy fill: if low <= bid_price
            if row['low'] <= bid_price and self.inventory < self.max_inventory:
                if self.simulate_fill(bid_price, True):
                    self.execute_trade(bid_price, True, self.order_size)

            # Sell fill: if high >= ask_price
            if row['high'] >= ask_price and self.inventory > -self.max_inventory:
                if self.simulate_fill(ask_price, False):
                    self.execute_trade(ask_price, False, self.order_size)

            # Record equity curve
            self.equity_curve.append(self.equity)
            self.inventory_curve.append(self.inventory)

            # Log progress
            if idx % 1000 == 0:
                self.logger().info(f"Processed {idx}/{len(df)} candles")

        # Calculate final results
        results = self.calculate_results()
        self.logger().info("Backtest completed!")
        return results

    def calculate_results(self) -> Dict:
        """Calculate backtest results"""
        if not self.equity_curve:
            return {}

        # Basic metrics
        initial_equity = self.equity_curve[0]
        final_equity = self.equity_curve[-1]
        total_return = (final_equity - initial_equity) / initial_equity

        # Volatility
        returns = np.diff(self.equity_curve) / np.array(self.equity_curve[:-1])
        volatility = np.std(returns) * np.sqrt(252 * 24 * 60)  # Annualized

        # Sharpe ratio (assuming 0% risk-free rate)
        sharpe_ratio = np.mean(returns) / np.std(returns) * np.sqrt(252 * 24 * 60) if np.std(returns) > 0 else 0

        # Win rate
        winning_trades = len([t for t in self.trade_log if t['equity'] > t.get('prev_equity', 0)])
        win_rate = winning_trades / len(self.trade_log) if self.trade_log else 0

        # Average trade
        avg_trade = np.mean([t['equity'] - t.get('prev_equity', 0) for t in self.trade_log]) if self.trade_log else 0

        results = {
            'initial_equity': initial_equity,
            'final_equity': final_equity,
            'total_return': total_return,
            'total_return_pct': total_return * 100,
            'max_drawdown': self.max_drawdown,
            'max_drawdown_pct': self.max_drawdown * 100,
            'volatility': volatility,
            'sharpe_ratio': sharpe_ratio,
            'trades_count': self.trades_count,
            'win_rate': win_rate,
            'avg_trade': avg_trade,
            'total_fees': self.total_fees,
            'final_inventory': self.inventory,
            'final_cash': self.cash
        }

        return results

    def plot_results(self, save_path: str = "sui_backtest_results.png"):
        """Plot backtest results"""
        if not self.equity_curve:
            return

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))

        # Equity curve
        ax1.plot(self.equity_curve, label='Equity', color='blue')
        ax1.set_title('SUI Market Making - Equity Curve')
        ax1.set_ylabel('Equity ($)')
        ax1.legend()
        ax1.grid(True)

        # Inventory curve
        ax2.plot(self.inventory_curve, label='Inventory', color='red')
        ax2.set_title('Inventory Over Time')
        ax2.set_xlabel('Time')
        ax2.set_ylabel('SUI Inventory')
        ax2.legend()
        ax2.grid(True)

        plt.tight_layout()
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        plt.show()

    def save_results(self, results: Dict, save_path: str = "sui_backtest_results.csv"):
        """Save results to CSV"""
        # Save trade log
        if self.trade_log:
            trade_df = pd.DataFrame(self.trade_log)
            trade_df.to_csv(save_path, index=False)

        # Save summary
        summary_df = pd.DataFrame([results])
        summary_df.to_csv(save_path.replace('.csv', '_summary.csv'), index=False)

    def logger(self) -> logging.Logger:
        return logging.getLogger(self.__class__.__name__)


def main():
    """Main function for running backtest"""
    parser = argparse.ArgumentParser(description='SUI Market Making Backtester')
    parser.add_argument('--csv', required=True, help='Path to SUIUSDT CSV data')
    parser.add_argument('--base_spread_bps', type=float, default=20, help='Base spread in basis points')
    parser.add_argument('--vol_window', type=int, default=60, help='Volatility window (minutes)')
    parser.add_argument('--vol_k', type=float, default=1.5, help='Volatility multiplier')
    parser.add_argument('--max_inventory', type=float, default=1000, help='Maximum inventory')
    parser.add_argument('--skew_k', type=float, default=0.5, help='Inventory skew factor')
    parser.add_argument('--order_size', type=float, default=100, help='Order size')
    parser.add_argument('--fee_bps', type=float, default=10, help='Trading fee in basis points')

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(level=logging.INFO)

    # Create backtester
    backtester = SUIMarketMakingBacktester(
        base_spread_bps=args.base_spread_bps,
        vol_window=args.vol_window,
        vol_k=args.vol_k,
        max_inventory=args.max_inventory,
        skew_k=args.skew_k,
        order_size=args.order_size,
        fee_bps=args.fee_bps
    )

    # Load data
    df = backtester.load_data(args.csv)

    # Run backtest
    results = backtester.run_backtest(df)

    # Print results
    print("\n" + "=" * 50)
    print("SUI MARKET MAKING BACKTEST RESULTS")
    print("=" * 50)
    for key, value in results.items():
        if isinstance(value, float):
            print(f"{key}: {value:.4f}")
        else:
            print(f"{key}: {value}")
    print("=" * 50)

    # Plot results
    backtester.plot_results()

    # Save results
    backtester.save_results(results)


if __name__ == "__main__":
    main()
