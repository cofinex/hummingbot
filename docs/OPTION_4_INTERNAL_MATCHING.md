# Option 4: Internal Matching Exchange - Self-Trading Guide

## Overview

**Good news!** If you're using `exchange-core` (or building your own exchange), **self-trading is already supported!** The exchange-core matching engine allows orders from the same user to match each other, with special handling for balance updates and fees.

---

## How Exchange-Core Handles Self-Trading

### Current Implementation

Exchange-core **does NOT prevent self-trading**. The matching engine will match orders from the same user if:
1. Prices overlap (buy price >= sell price)
2. Orders are on the orderbook
3. Standard matching conditions are met

### Self-Trade Detection

The system detects self-trades by comparing user IDs:

```python
# In wallet_updater.py
is_self_trade = (taker_user_id == maker_user_id)
```

When `maker_user_id == taker_user_id`, the system treats it as a self-trade and applies special logic.

---

## How Self-Trading Works in Exchange-Core

### Standard Trade Flow

```
1. User places BUY order → Reserved in INTRADE wallet
2. User places SELL order → Reserved in INTRADE wallet
3. Matching engine matches orders (same user)
4. Trade executed:
   - BUY order filled → Releases quote currency from INTRADE
   - SELL order filled → Releases base currency from INTRADE
5. Fees charged appropriately
```

### Self-Trade Special Handling

**Key Difference:** For self-trades, the system:
- ✅ **Processes the trade** (orders match and execute)
- ✅ **Handles fees** (both maker and taker fees charged)
- ⚠️ **Skips SPOT balance updates** (no net change - funds stay in same account)
- ⚠️ **Skips external transfers** (no SQS transfers needed)

**Why Skip SPOT Updates?**
- Same user is both maker and taker
- INTRADE balance updates are sufficient
- No net change in SPOT balances (just moving funds between own orders)

### Fee Handling for Self-Trades

**Example: Self-Trade BUY Order**

```
User places:
- BUY order: 10 USDR @ 1.01 USDC = 10.10 USDC
- SELL order: 10 USDR @ 1.01 USDC (matches)

Initial State:
- INTRADE USDC: -(10.10 + 0.0101) = -10.1101 USDC (reserved)
- INTRADE USDR: +10 USDR (reserved)

After Trade:
- INTRADE USDC: -0.0101 USDC (fee remains reserved)
- INTRADE USDR: 0 (released)
- FEES wallet: +0.0101 (taker) + 0.0101 (maker) = 0.0202 USDC
- SPOT: No change (skipped for self-trades)
```

---

## Using Self-Trading with Hummingbot

### Step 1: Connect Hummingbot to Exchange-Core

1. **Configure Exchange Connector**
   - Set up your exchange connector to point to exchange-core API
   - Configure authentication (API keys, user ID)

2. **Verify Self-Trading is Enabled**
   - Exchange-core allows self-trading by default
   - No special configuration needed in matching engine

### Step 2: Use Pure Market Making Strategy

**Standard PMM will work!** When you place both buy and sell orders:

```python
# Pure Market Making Strategy
- Places BUY order at $100
- Places SELL order at $101

# If prices overlap (buy >= sell), exchange-core will match them!
- Buy at $100.50 matches Sell at $100.50
- Trade executes (self-trade)
- Fees charged, balances updated
```

### Step 3: Monitor Self-Trades

The system logs self-trades with:
```python
is_self_trade = (taker_user_id == maker_user_id)
logger.info(f"Self-trade detected: {is_self_trade}")
```

---

## Configuration

### Exchange-Core Configuration

**No special configuration needed!** Self-trading works out of the box.

However, you can monitor/control it through:

1. **Matching Engine**
   - Located in: `OrderBookDirectImpl.java` or `OrderBookNaiveImpl.java`
   - Currently: No self-trade prevention logic
   - Orders match based on price-time priority, regardless of user ID

2. **Risk Engine**
   - Located in: `RiskEngine.java`
   - Checks balance sufficiency (same for self-trades)
   - No special restrictions for self-trades

3. **Wallet Updates**
   - Located in: `wallet_updater.py`
   - Detects self-trades and applies special handling
   - Skips SPOT updates for self-trades

### Hummingbot Configuration

**Standard configuration works!** No special settings needed.

```yaml
# conf/strategies/conf_pure_market_making_strategy.yml
strategy: pure_market_making
exchange: your_exchange_core_connector
trading_pair: BTC-USDT
bid_spread: 0.001
ask_spread: 0.001
order_amount: 0.01
```

---

## Benefits of Self-Trading

### 1. **Liquidity Provision**
- Your orders provide liquidity to the orderbook
- Can match your own orders when prices overlap
- Earn maker fees (even on self-trades)

### 2. **Price Discovery**
- Self-trades contribute to price discovery
- Help establish market prices
- Create trading activity

### 3. **Strategy Testing**
- Test market making strategies
- Simulate trading scenarios
- Validate order execution logic

### 4. **Inventory Management**
- Move funds between base and quote currencies
- Manage inventory positions
- Rebalance holdings

---

## Considerations and Limitations

### 1. **Fee Costs**
- Both maker and taker fees are charged
- Example: 0.1% maker + 0.1% taker = 0.2% total cost
- Consider fee structure when designing strategies

### 2. **Balance Management**
- SPOT balances don't change (for self-trades)
- INTRADE balances are updated
- Monitor INTRADE wallet for reserved funds

### 3. **Regulatory Compliance**
- Self-trading may be restricted in some jurisdictions
- Check local regulations
- May be considered "wash trading" in some markets

### 4. **Market Manipulation**
- Excessive self-trading can be seen as manipulation
- Use responsibly
- Consider rate limiting or controls

---

## Implementation Example

### Using Pure Market Making with Self-Trading

```python
# Hummingbot PMM Strategy
# When both orders are placed and prices overlap:

Order Book:
- Best Bid: $100 (Your BUY order)
- Best Ask: $100.50 (Your SELL order)

New Order: BUY at $101 (Your account)
→ Matches with Your SELL order at $100.50
→ Self-trade executed!
→ Fees charged: Maker (0.1%) + Taker (0.1%)
→ INTRADE balances updated
→ SPOT balances unchanged (self-trade)
```

### Custom Script Strategy for Self-Trading

You can create a custom strategy that actively manages self-trading:

```python
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase
from decimal import Decimal

class SelfMatchingStrategy(ScriptStrategyBase):
    """
    Strategy that actively manages self-trading on exchange-core
    """

    def on_tick(self):
        # Get active orders
        active_orders = self.active_orders

        # Find buy and sell orders
        buy_orders = [o for o in active_orders if o.is_buy]
        sell_orders = [o for o in active_orders if not o.is_buy]

        # Check if prices overlap (self-trade opportunity)
        if buy_orders and sell_orders:
            best_buy = max(buy_orders, key=lambda x: x.price)
            best_sell = min(sell_orders, key=lambda x: x.price)

            # If buy price >= sell price, orders will match
            if best_buy.price >= best_sell.price:
                self.logger().info(
                    f"Self-trade opportunity: Buy at {best_buy.price} >= "
                    f"Sell at {best_sell.price}"
                )
                # Exchange-core will automatically match these!
                # No action needed - matching engine handles it
```

---

## Monitoring Self-Trades

### Logs

Exchange-core logs self-trades in:
- `wallet_updater.py`: Detects and logs self-trades
- Matching engine: Logs all trades (including self-trades)

### Database Queries

Query ClickHouse to find self-trades:

```sql
SELECT
    trade_id,
    taker_order_id,
    maker_order_id,
    taker_user_id,
    maker_user_id,
    quantity,
    price,
    timestamp
FROM trades
WHERE taker_user_id = maker_user_id
  AND symbol = 'BTC/USDT'
  AND timestamp >= now() - INTERVAL 1 DAY
ORDER BY timestamp DESC;
```

### Metrics

Track self-trade metrics:
- Self-trade count
- Self-trade volume
- Self-trade fees
- Self-trade percentage of total volume

---

## Best Practices

### 1. **Spread Management**
- Maintain minimum spread to avoid constant self-trading
- Example: If spread < 0.1%, orders might constantly match
- Consider dynamic spread adjustment

### 2. **Order Size**
- Use appropriate order sizes
- Avoid very large orders that might self-match immediately
- Consider partial fills

### 3. **Rate Limiting**
- Implement rate limiting if needed
- Prevent excessive self-trading
- Monitor self-trade frequency

### 4. **Fee Optimization**
- Consider maker/taker fee structure
- Optimize for maker fees (lower cost)
- Balance between liquidity and costs

---

## Comparison: Self-Trading vs External Trading

| Aspect | Self-Trading | External Trading |
|--------|-------------|------------------|
| **Matching** | Same user (maker == taker) | Different users |
| **SPOT Updates** | Skipped (no net change) | Updated |
| **Fees** | Both maker + taker | One side pays |
| **Liquidity** | Internal | External |
| **Price Impact** | Minimal | Can have impact |
| **Regulatory** | May be restricted | Standard |

---

## Troubleshooting

### Issue: Orders Not Matching

**Check:**
1. Prices must overlap: `buy_price >= sell_price`
2. Orders must be on orderbook (not cancelled)
3. Sufficient balance in INTRADE wallet
4. Matching engine is running

### Issue: Fees Too High

**Solutions:**
1. Optimize for maker fees (place limit orders)
2. Reduce order frequency
3. Increase spread to reduce self-trading
4. Review fee structure

### Issue: Balance Not Updating

**For Self-Trades:**
- SPOT balances don't update (by design)
- Check INTRADE wallet for updates
- Fees are charged to FEES wallet

---

## Summary

✅ **Exchange-core supports self-trading out of the box**
✅ **No special configuration needed**
✅ **Works with standard Hummingbot strategies**
✅ **Fees are handled correctly**
✅ **INTRADE balances updated, SPOT unchanged**

**Use Cases:**
- Market making strategies
- Liquidity provision
- Strategy testing
- Inventory management

**Considerations:**
- Fee costs (both maker + taker)
- Regulatory compliance
- Market manipulation concerns
- Balance management (INTRADE vs SPOT)

---

## Next Steps

1. **Test with Paper Trading**
   - Verify self-trading behavior
   - Monitor logs and balances
   - Test different scenarios

2. **Implement Strategy**
   - Use PMM or custom strategy
   - Configure appropriate spreads
   - Monitor self-trade frequency

3. **Monitor and Optimize**
   - Track self-trade metrics
   - Optimize fees and spreads
   - Adjust strategy parameters

4. **Production Deployment**
   - Ensure regulatory compliance
   - Set up monitoring and alerts
   - Implement rate limiting if needed
