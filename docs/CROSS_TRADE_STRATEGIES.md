# Cross-Trade Strategies: Trading Between Bot's Own Orders

## Question

**Can Hummingbot perform cross trades within the same exchange - i.e., match the bot's own buy and sell orders?**

## Short Answer

**No, there is currently no built-in strategy in Hummingbot that actively matches the bot's own orders within the same exchange.** However, there are strategies that can work around this limitation, and you can create a custom script strategy to achieve this.

---

## Current Strategy Behavior

### Pure Market Making (PMM)

**What it does:**
- Places limit buy and sell orders around the mid-price
- Waits for **external market participants** to fill the orders
- Does **NOT** actively match its own orders

**Key Parameter: `take_if_crossed`**
- When `take_if_crossed=True`: Allows placing **taker orders** (market orders) to take the **best external order** if the orderbook crosses
- This is about taking **external orders**, not matching the bot's own orders
- Still requires external market participants

**Example:**
```
Bot places:
- Buy order at $100
- Sell order at $101

External trader buys at $101 → Bot's sell order fills
External trader sells at $100 → Bot's buy order fills

Bot's orders do NOT match each other directly.
```

### Cross Exchange Market Making (XEMM)

**What it does:**
- Places maker orders on one exchange (maker market)
- Hedges fills by placing taker orders on another exchange (taker market)
- Works **between different exchanges**, not within the same exchange

**Not suitable for:** Matching orders within the same exchange

### Triangular Arbitrage

**What it does:**
- Executes sequential trades across 3 trading pairs on the same exchange
- Example: `ADA-USDT → ADA-BTC → BTC-USDT`
- Trades are **sequential** (one after another), not simultaneous matching

**Not suitable for:** Matching buy and sell orders on the same trading pair

---

## Why Self-Matching is Limited

### Exchange-Level Restrictions

Most exchanges have **self-trading prevention** mechanisms:
- Orders from the same account/user typically **cannot match each other**
- This is to prevent wash trading and market manipulation
- Even if you place both buy and sell orders, the exchange's matching engine will not match them

### Hummingbot Architecture

Hummingbot strategies are designed to:
- Place orders and wait for external fills
- React to market events (order fills, price changes)
- Not actively match their own orders

---

## Solutions and Workarounds

### Option 1: Use Paper Trading (Simulation)

**Paper Trading** simulates order fills based on market price movements:
- If market price crosses your limit order price, the order is automatically filled
- This can create the appearance of "self-matching" when both orders are filled
- However, this is simulation, not actual self-matching

**Example:**
```python
# Paper trading mode
Bot places:
- Buy order at $100
- Sell order at $101

If market price moves to $100.50:
- Both orders might appear "filled" in simulation
- But this is based on market price, not actual matching
```

### Option 2: Create a Custom Script Strategy

You can create a custom script strategy that:
1. Places limit orders (buy and sell)
2. Monitors the orderbook
3. When conditions are met, places market orders to "take" the limit orders
4. This simulates self-matching by using market orders to fill limit orders

**Example Implementation Concept:**
```python
class SelfMatchingStrategy(ScriptStrategyBase):
    def on_tick(self):
        # Check if buy and sell orders are both active
        active_buy = self.get_active_buy_order()
        active_sell = self.get_active_sell_order()

        if active_buy and active_sell:
            # Check if prices overlap (buy price >= sell price)
            if active_buy.price >= active_sell.price:
                # Cancel limit orders
                self.cancel_order(active_buy.order_id)
                self.cancel_order(active_sell.order_id)

                # Place market orders to execute the trade
                # This simulates "matching" by using market orders
                self.place_market_buy(active_sell.quantity)
                self.place_market_sell(active_buy.quantity)
```

**Limitations:**
- Still subject to exchange self-trading prevention
- May incur higher fees (market orders vs limit orders)
- More complex to implement correctly

### Option 3: Use Multiple Accounts/Sub-Accounts

If your exchange supports:
- **Sub-accounts** or **API keys with different user IDs**
- You could run two separate Hummingbot instances:
  - Instance 1: Places buy orders
  - Instance 2: Places sell orders
  - They can match each other (different accounts)

**Limitations:**
- Requires multiple accounts/API keys
- More complex setup and management
- May violate exchange terms of service

### Option 4: Internal Matching Exchange ✅ **RECOMMENDED**

If you're using `exchange-core` (or building your own exchange):
- ✅ **Self-trading is already supported!** Exchange-core allows same-user orders to match
- ✅ **No special configuration needed** - works out of the box
- ✅ **Works with standard Hummingbot strategies** (PMM, etc.)
- ✅ **Proper fee handling** - both maker and taker fees charged
- ⚠️ **SPOT balances unchanged** - INTRADE balances updated (by design)

**See detailed guide:** [OPTION_4_INTERNAL_MATCHING.md](./OPTION_4_INTERNAL_MATCHING.md)

**Key Points:**
- Exchange-core matching engine does NOT prevent self-trading
- Orders from same user will match if prices overlap
- Special handling: SPOT updates skipped, fees still charged
- Perfect for market making strategies on your own exchange

---

## Technical Details: How Orders Match

### Standard Exchange Matching

```
Order Book:
- Best Bid: $100 (from User A)
- Best Ask: $101 (from User B)

New Order: Buy at $102 (from User C)
→ Matches with User B's sell order at $101
→ Trade executed: User C buys from User B
```

### Self-Trading Prevention

```
Order Book:
- Best Bid: $100 (from Your Account)
- Best Ask: $101 (from Your Account)

New Order: Buy at $102 (from Your Account)
→ Exchange matching engine: "Same user, skip matching"
→ Order placed on book at $102
→ Your orders do NOT match each other
```

---

## Recommendations

### For Testing/Simulation
- Use **Paper Trading** mode - it simulates fills based on market price
- This gives you the behavior you want for testing strategies

### For Live Trading
1. **Accept the limitation**: Most exchanges prevent self-trading
2. **Use PMM with tight spreads**: Let external market participants fill your orders
3. **Consider market making programs**: Some exchanges offer special programs for market makers with different matching rules
4. **Build custom solution**: If you control the exchange, implement internal matching

### For Custom Development
- Create a script strategy that monitors and manages orders
- Use market orders strategically to "take" your own limit orders when needed
- Be aware of exchange restrictions and fees

---

## Related Strategies

### Strategies That Work Within Same Exchange

1. **Pure Market Making (PMM)**
   - Places orders, waits for external fills
   - Best for: Providing liquidity, earning maker fees

2. **Triangular Arbitrage**
   - Sequential trades across 3 pairs
   - Best for: Exploiting price discrepancies

3. **Avellaneda Market Making**
   - Advanced market making with inventory management
   - Best for: Optimal bid-ask spread placement

### Strategies That Work Across Exchanges

1. **Cross Exchange Market Making (XEMM)**
   - Maker on one exchange, taker on another
   - Best for: Arbitrage between exchanges

2. **Spot-Perpetual Arbitrage**
   - Arbitrage between spot and perpetual futures
   - Best for: Funding rate arbitrage

---

## Summary

| Requirement | Solution | Status |
|------------|----------|--------|
| Match bot's own orders on same exchange | Custom script strategy | ⚠️ Limited by exchange restrictions |
| Simulate self-matching | Paper Trading | ✅ Works for testing |
| Match orders across exchanges | Cross Exchange Market Making | ✅ Built-in strategy |
| Sequential trades on same exchange | Triangular Arbitrage | ✅ Built-in strategy |
| Place orders and wait for fills | Pure Market Making | ✅ Built-in strategy |

**Bottom Line:** Hummingbot is designed for **external market interaction**, not internal self-matching. If you need self-matching behavior, you'll need to build a custom solution or use paper trading for simulation.
