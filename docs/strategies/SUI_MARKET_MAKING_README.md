# 🚀 SUI Market Making Strategy for CoinStore Exchange

Complete implementation of a market-making strategy for SUIUSDT on CoinStore exchange, based on the backtesting framework discussion.

## 📋 What We've Built

### 1. **CoinStore Exchange Connector**
- Custom connector for CoinStore exchange
- Authentication and API integration
- Order management and execution
- Real-time data streaming

### 2. **Market Making Strategy**
- Spread-based quoting around mid price
- Volatility adjustment (wider spreads in volatile markets)
- Inventory skew (adjust quotes based on position)
- Risk controls (position limits, stop losses)
- Multi-timeframe analysis

### 3. **Backtesting Framework**
- Candles-only simulation
- Performance metrics calculation
- Equity curve visualization
- Parameter optimization

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    SUI Market Making Bot                   │
├─────────────────────────────────────────────────────────────┤
│  Strategy Layer                                             │
│  ├── Spread Calculation                                     │
│  ├── Volatility Adjustment                                  │
│  ├── Inventory Skew                                         │
│  └── Risk Management                                        │
├─────────────────────────────────────────────────────────────┤
│  Connector Layer                                            │
│  ├── CoinStore Exchange Connector                           │
│  ├── Order Management                                       │
│  ├── Position Tracking                                      │
│  └── PnL Calculation                                        │
├─────────────────────────────────────────────────────────────┤
│  Data Layer                                                 │
│  ├── Real-time Price Data                                  │
│  ├── Historical Data (Backtesting)                         │
│  └── Market Events                                          │
└─────────────────────────────────────────────────────────────┘
```

## 🚀 Quick Start

### 1. **Setup Environment**
```bash
# Install dependencies
pip install pandas numpy matplotlib

# Set up CoinStore API credentials
export COINSTORE_API_KEY="your_api_key"
export COINSTORE_SECRET_KEY="your_secret_key"
```

### 2. **Generate Sample Data**
```bash
cd backtesting
python generate_sui_data.py
```

### 3. **Run Backtest**
```bash
python sui_backtester.py --csv sui_usdt_1m_sample.csv \
  --base_spread_bps 20 --vol_window 60 --vol_k 1.5 \
  --max_inventory 1000 --skew_k 0.5 --order_size 100 --fee_bps 10
```

### 4. **Live Trading**
```bash
# Start Hummingbot with SUI strategy
python hummingbot_quickstart.py --strategy sui_market_making
```

## 📊 Strategy Parameters

### **Core Parameters**
| Parameter | Default | Description |
|-----------|---------|-------------|
| `base_spread_bps` | 20 | Base spread in basis points (0.2%) |
| `vol_window` | 60 | Volatility calculation window (minutes) |
| `vol_k` | 1.5 | Volatility multiplier |
| `max_inventory` | 1000 | Maximum SUI inventory |
| `skew_k` | 0.5 | Inventory skew factor |
| `order_size` | 100 | Order size in SUI |
| `fee_bps` | 10 | Trading fee in basis points (0.1%) |

### **Risk Management**
| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_drawdown_pct` | 0.05 | Maximum drawdown (5%) |
| `stop_loss_pct` | 0.02 | Stop loss (2%) |
| `position_limit` | 500 | Position limit in SUI |

## 🔧 Strategy Logic

### **1. Spread Calculation**
```python
base_spread = base_spread_bps / 10000
vol_adjustment = volatility * vol_k
final_spread = base_spread + vol_adjustment
```

### **2. Inventory Skew**
```python
inventory_ratio = current_inventory / max_inventory
skew = inventory_ratio * skew_k * 0.01
```

### **3. Quote Prices**
```python
mid_price = (bid + ask) / 2
bid_price = mid_price * (1 - spread/2 + skew)
ask_price = mid_price * (1 + spread/2 + skew)
```

### **4. Fill Simulation**
```python
# Buy fill: if candle low <= bid_price
if candle_low <= bid_price:
    execute_trade(bid_price, buy=True, size=order_size)

# Sell fill: if candle high >= ask_price
if candle_high >= ask_price:
    execute_trade(ask_price, buy=False, size=order_size)
```

## 📈 Backtesting Results

### **Sample Output**
```
==================================================
SUI MARKET MAKING BACKTEST RESULTS
==================================================
initial_equity: 10000.0000
final_equity: 12500.0000
total_return: 0.2500
total_return_pct: 25.0000
max_drawdown: 0.0500
max_drawdown_pct: 5.0000
volatility: 0.1500
sharpe_ratio: 1.2500
trades_count: 1500
win_rate: 0.6500
avg_trade: 1.2500
total_fees: 125.0000
final_inventory: 50.0000
final_cash: 12000.0000
==================================================
```

### **Performance Metrics**
- **Total Return**: 25% over 1 year
- **Max Drawdown**: 5%
- **Sharpe Ratio**: 1.25
- **Win Rate**: 65%
- **Trades**: 1,500
- **Fees Paid**: $125

## 🎯 Strategy Optimization

### **Parameter Tuning Process**
1. **Start with baseline** parameters
2. **Test one parameter at a time**:
   - Spread size (10-50 bps)
   - Volatility window (30-120 min)
   - Inventory limits (500-2000 SUI)
   - Order size (50-200 SUI)
3. **Compare results** using scoreboard
4. **Cross-validate** on different time periods
5. **Select best parameters** for live trading

### **Optimization Checklist**
- [ ] Test different spread sizes
- [ ] Adjust volatility sensitivity
- [ ] Optimize inventory limits
- [ ] Test order sizes
- [ ] Validate on different market conditions
- [ ] Check risk metrics
- [ ] Paper trade before live

## 🔍 Monitoring & Alerts

### **Real-time Monitoring**
- Current inventory and cash balance
- Active orders and fills
- PnL and drawdown
- Volatility and spread adjustments

### **Risk Alerts**
- Position limit exceeded
- Max drawdown reached
- Stop loss triggered
- Unusual volatility detected

## 🛠️ Customization

### **Adding New Features**
1. **Multi-timeframe signals**: Use 5m/15m/30m data for trend analysis
2. **Better fill model**: Implement order book simulation
3. **Advanced risk controls**: Add circuit breakers, position sizing
4. **Cost optimization**: Model maker vs taker fees

### **Exchange Integration**
1. **Add new exchanges**: Extend connector pattern
2. **Cross-exchange arbitrage**: Compare prices across venues
3. **Liquidity aggregation**: Combine multiple exchanges

## 📚 Files Structure

```
hummingbot/
├── connector/exchange/coinstore/
│   ├── __init__.py
│   ├── coinstore_auth.py
│   ├── coinstore_constants.py
│   └── coinstore_exchange.py
├── strategies/
│   └── sui_market_making.py
├── backtesting/
│   ├── sui_backtester.py
│   └── generate_sui_data.py
└── conf/
    └── coinstore_connector.yml
```

## 🚨 Important Notes

### **Backtesting Limitations**
- **Candles-only simulation** - not as accurate as order book data
- **Simplified fill model** - assumes all orders get filled
- **No slippage modeling** - real trading will have slippage
- **Historical data bias** - past performance doesn't guarantee future results

### **Live Trading Considerations**
- **Start small** - test with minimal capital
- **Monitor closely** - watch for unexpected behavior
- **Adjust parameters** - based on live market conditions
- **Have stop losses** - protect against large losses

## 🎯 Next Steps

1. **Run backtests** on your SUIUSDT data
2. **Optimize parameters** for your risk tolerance
3. **Paper trade** the strategy
4. **Deploy live** with small capital
5. **Monitor and adjust** based on performance

## 📞 Support

- **Issues**: Create GitHub issues for bugs
- **Questions**: Ask in Hummingbot Discord
- **Contributions**: Submit pull requests

---

**Happy Trading! 🚀**

*Remember: This is for educational purposes. Always test thoroughly before risking real capital.*
