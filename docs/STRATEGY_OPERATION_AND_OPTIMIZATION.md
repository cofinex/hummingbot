# Multi-Level Self-Trading Strategy - Operation and Optimization Guide

## Overview

This comprehensive guide explains how the Multi-Level Self-Trading strategy operates, including timing mechanisms, price movement behavior, drift analysis, and optimization recommendations for both paper trading and live trading with exchange-core.

---

## Table of Contents

1. [Strategy Overview](#strategy-overview)
2. [Balanced Configuration](#balanced-configuration)
3. [Timing Mechanisms](#timing-mechanisms)
4. [Price Movement and Drift Analysis](#price-movement-and-drift-analysis)
5. [Refresh Triggers](#refresh-triggers)
6. [Configuration Guide](#configuration-guide)
7. [Troubleshooting](#troubleshooting)

---

## Strategy Overview

The Multi-Level Self-Trading strategy places 5 levels of buy and sell orders around a reference price, with Level 1 designed for self-trading (overlapping orders) and Levels 2-5 providing additional liquidity.

### Key Features

- **Level 1**: Overlapping orders (buy >= sell) for self-trading - $10 per order
- **Levels 2-5**: Different amounts for buy ($10-$50) and sell ($500-$1500)
- **Dynamic Price Shift**: Adjusts all order prices based on Bitget BTC/USDT 24h price change
- **Intelligent Refresh**: Refreshes based on fills, Bitget shift changes, or periodically
- **Market Price Movement**: Level 1 self-trades move market price, Levels 2-5 follow

### Order Structure

```
Reference Price (with Bitget shift)
    ↓
Level 1: Buy @ +0.05%, Sell @ -0.05% (overlapping for self-trade)
    ↓
Level 2: ±0.2% from Level 1
    ↓
Level 3: ±0.4% from Level 1
    ↓
Level 4: ±0.6% from Level 1
    ↓
Level 5: ±0.8% from Level 1
```

---

## Balanced Configuration

### Recommended Settings

```yaml
# Strategy Settings (BALANCED)
order_refresh_time: 300         # Periodic refresh every 5 minutes (backup)
filled_order_delay: 30          # Wait 30s after fill before refresh (balanced)
price_type: "last"              # Use self-trade price to move market ⭐
enable_self_trading: true

# Refresh Control
refresh_on_level1_fill: true    # ✅ Refresh after Level 1 (move price)
refresh_on_level2_5_fill: true  # ✅ Refresh after real market activity

# Bitget Shift Change Detection
price_shift_update_interval: 60 # Check every 60 seconds
price_shift_change_threshold: 0.1  # Refresh if shift changes by >= 0.1%
```

### What This Balanced Setup Provides

**Price Movement Characteristics:**
- Drift rate: ~0.0435% per cycle (30-second intervals)
- Typical correction: Every 2-3 minutes (when Bitget shift changes ≥0.1%)
- Typical drift before correction: 0.17% - 0.26%
- Maximum drift: 0.435% (worst case over 5 minutes, corrected by periodic refresh)

**Refresh Frequency:**
- Level 1 fills: Refresh every ~30 seconds (after delay)
- Bitget corrections: Every 60-180 seconds (when significant shift change)
- Periodic backup: Every 5 minutes (ensures maximum drift cap)

**Benefits:**
- ✅ Controlled movement: Price moves but stays aligned with BTC trend
- ✅ Market interaction: 30s delay allows Levels 2-5 to interact
- ✅ Efficient: Not too many API calls, not too few updates
- ✅ Responsive: Adapts to Bitget price changes (every 60s check)
- ✅ Safe: Maximum 0.435% drift cap (5-minute periodic refresh)

---

## Timing Mechanisms

### How the Script Works - Main Flow

The strategy runs in a **tick-based loop** (`on_tick()` method), where Hummingbot calls `on_tick()` approximately **once per second**. Each tick, the strategy checks various conditions and takes actions accordingly.

### Updated Timing Flow Diagram

```
Strategy Start
    ↓
[Initial Order Placement]
    ├─ Cancel all existing orders
    ├─ Fetch Bitget change24h (if enabled)
    ├─ Calculate reference price with shift
    ├─ Create 5 levels of orders
    ├─ Adjust orders to budget
    ├─ Place orders
    └─ Set create_timestamp = current_time + 300s
        ↓
[Every Tick (1 second)]
    ├─ Check: Is precision detected? → Detect if not
    ├─ Check: Time to update Bitget? → Fetch if 60s passed
    ├─ Check: Bitget shift changed significantly? → Refresh if threshold exceeded
    ├─ Check: Fill happened? → Wait delay, then refresh (if configured)
    └─ Check: 300s passed? → Periodic refresh (backup)
```

### Detailed Timing Mechanisms

#### 1. Initial Order Placement

**When:** At strategy start (first tick where `create_timestamp == 0`)

**What happens:**
- Connector becomes ready
- Orders are placed immediately
- `create_timestamp` is set to `current_time + 300 seconds`

**Example Timeline:**
```
T=0s:   Strategy starts
T=2s:   Connector ready, orders placed
        create_timestamp = 302s (T=2 + 300)
```

#### 2. Periodic Order Refresh (Backup Timer)

**Parameter:** `order_refresh_time = 300 seconds (5 minutes)`

**How it works:**
- Every tick, checks: `if current_timestamp >= create_timestamp`
- When true, cancels ALL orders and places new ones
- Updates `create_timestamp` to `current_time + 300s`

**Purpose:**
- Backup timer to ensure maximum drift is capped
- Ensures orders refresh even if no fills or Bitget changes occur
- Provides safety net for long periods without activity

#### 3. Fill-Based Refresh (Conditional)

**Parameter:** `filled_order_delay = 30 seconds` (balanced)

**How it works:**
- When an order fills, `did_fill_order()` is called
- Strategy detects if fill is Level 1 or Level 2-5
- Based on configuration:
  - Level 1 fills: Refresh if `refresh_on_level1_fill: true`
  - Level 2-5 fills: Refresh if `refresh_on_level2_5_fill: true`
- Sets `refresh_pending = True` and records `last_fill_timestamp`
- Every tick, checks: `if refresh_pending and current_time >= last_fill_timestamp + delay`
- When true, cancels ALL orders and places new ones

**Why 30 seconds (balanced):**
- Gives other orders time to fill before cancelling everything
- Reduces unnecessary churn when only one order fills
- Still responsive enough to refresh after meaningful activity
- Allows multiple fills to accumulate before refresh

#### 4. Bitget Price Shift Update (NEW: Triggers Refresh)

**Parameter:** `price_shift_update_interval = 60 seconds`
**New Parameter:** `price_shift_change_threshold = 0.1%`

**How it works:**
- Every tick, checks: `if current_time >= last_shift_update_timestamp + 60`
- When true, fetches BTC/USDT change24h from Bitget API
- **NEW:** Calculates shift change: `abs(new_shift - previous_shift)`
- **NEW:** If change >= threshold (0.1%), triggers refresh
- Updates `current_price_shift` and `previous_price_shift`

**Benefits:**
- Responds to real market conditions (BTC price movement)
- Not triggered by self-trades
- Keeps orders aligned with external market
- More meaningful refresh trigger than just fills

---

## Price Movement and Drift Analysis

### How Price Moves

With your intention to move market price through Level 1 self-trades:

1. **Level 1 self-trade executes** → Updates `last_trade_price` in exchange-core
2. **After 30s delay, refresh triggered** → Uses new `last_trade_price` as reference
3. **New orders placed** → Relative to the moved price
4. **Price continues moving** → Following Bitget trend direction

### Drift Calculation

**Base Parameters:**
- Starting price: $0.23 (CNX)
- Level 1 buy offset: +0.05% (0.0005)
- Level 1 sell offset: -0.05% (-0.0005)
- `filled_order_delay: 30s`
- Bitget check: every 60s
- Bitget threshold: 0.1%

**Drift per Cycle:**
```
Cycle 1:
  Reference: $0.2300
  Sell price: $0.2300 × 0.9995 = $0.2299
  Fill at: $0.2299

Cycle 2:
  Reference: $0.2299 (from previous fill)
  Sell price: $0.2299 × 0.9995 = $0.2298
  Fill at: $0.2298

Drift per cycle = -0.0001 per cycle ≈ -0.0435% per cycle
```

### Price Drift Scenarios

#### Best Case (Minimal Drift)

**Conditions:**
- Bitget shift changes by ≥0.1% every 60 seconds
- Refresh triggered on each Bitget change
- Frequent corrections keep price aligned

**Maximum drift before correction:**
- Maximum time between corrections: 60 seconds
- Maximum self-trades in 60s: 60s / 30s = 2 cycles
- Maximum drift: 2 cycles × 0.0435% = **0.087%**

**Result:** Price range: $0.2298 - $0.2300 (drift stays under 0.1%)

#### Realistic Case (Moderate Drift)

**Conditions:**
- Bitget shift changes occasionally (not every 60s)
- Level 1 self-trades every 30-60s
- Some Bitget corrections, but not constant

**Drift accumulation:**
- Time between corrections: ~120-180 seconds
- Cycles in 180s: 180s / 30s = 6 cycles
- Drift before correction: 6 × 0.0435% = **0.261%**

**Result:** Price at correction: $0.2294 (drift of $0.0006)

#### Worst Case (Maximum Drift)

**Conditions:**
- Bitget shift stable (no significant change for long period)
- Level 1 self-trades happen every 30s
- No Bitget-triggered refreshes
- Only periodic refresh at 300s corrects

**Drift accumulation:**
- Self-trades per 300s period: 300s / 30s = 10 cycles
- Drift per cycle: -0.0435%
- Maximum drift: 10 cycles × 0.0435% = **-0.435%**

**Result:** Price after 300s: $0.2290 (maximum drift of $0.0010)

### Summary Table

| Scenario | Max Time Between Corrections | Max Cycles | Maximum Drift | Price Range (from $0.23) |
|----------|------------------------------|------------|---------------|--------------------------|
| **Best Case** | 60 seconds | 2 cycles | **0.087%** | $0.2298 - $0.2300 |
| **Realistic** | 120-180 seconds | 4-6 cycles | **0.17% - 0.26%** | $0.2294 - $0.2296 |
| **Worst Case** | 300 seconds | 10 cycles | **0.435%** | $0.2290 - $0.2300 |

---

## Refresh Triggers

The strategy has **three types of refresh triggers**, checked in priority order:

### 1. Fill-Based Refresh (Conditional)

**Trigger:** Order fill detected

**Logic:**
- Level 1 fills: Refresh if `refresh_on_level1_fill: true`
- Level 2-5 fills: Refresh if `refresh_on_level2_5_fill: true`
- Wait `filled_order_delay` seconds before refreshing

**Priority:** Highest (checked first)

**Example:**
```
T=10s:   Level 1 self-trade @ $0.2299
         → refresh_on_level1_fill: true
         → refresh_pending = True
         → last_fill_timestamp = 10s
T=40s:   Delay expires (10 + 30 = 40)
         → Refresh triggered!
         → New orders at $0.2299 base
```

### 2. Bitget Shift Change Refresh (NEW)

**Trigger:** Bitget shift changes significantly

**Logic:**
- Bitget check every 60 seconds
- Calculate: `abs(new_shift - previous_shift)`
- If change >= `price_shift_change_threshold` (0.1%): Trigger refresh
- Wait `filled_order_delay` seconds before refreshing

**Priority:** Medium (checked after fill-based)

**Example:**
```
T=60s:   Bitget check: Shift = -0.72%
T=120s:  Bitget check: Shift = -0.85%
         → Change = 0.13% >= 0.1% threshold
         → Refresh triggered!
         → Orders realigned with BTC trend
```

### 3. Periodic Refresh (Backup)

**Trigger:** Time elapsed since last refresh

**Logic:**
- Check every tick: `if current_timestamp >= create_timestamp`
- When true, refresh immediately
- Sets `create_timestamp = now + 300s`

**Priority:** Lowest (checked last, as backup)

**Purpose:**
- Ensures maximum drift is capped at 0.435%
- Provides safety net if no fills or Bitget changes occur
- Guarantees refresh at least every 5 minutes

**Example:**
```
T=0s:    Orders placed, create_timestamp = 300s
T=300s:  Periodic refresh triggered (backup)
         → Orders refreshed regardless of other conditions
```

---

## Complete Timing Example (Balanced Configuration)

Here's a realistic scenario with the balanced configuration:

```
T=0s:    Strategy starts
T=2s:    Initial orders placed (Level 1-5)
         create_timestamp = 302s
         previous_price_shift = -0.72%
         refresh_pending = False

T=10s:   Level 1 buy order FILLS! (self-trade) @ $0.2299
         → Level 1 fill detected
         → refresh_on_level1_fill = true
         → refresh_pending = True
         → last_fill_timestamp = 10s

T=40s:   Fill delay expires (10 + 30 = 40)
         → Refresh triggered!
         → Cancel all orders
         → Place new orders (with base = $0.2299)
         → refresh_pending = False
         → create_timestamp = 340s (40 + 300)

T=60s:   Bitget update: shift = -0.80%
         Change = 0.08% < 0.1% threshold → No refresh
         previous_price_shift = -0.80%

T=70s:   Level 1 self-trade @ $0.2298
         → refresh_pending = True
         → last_fill_timestamp = 70s

T=100s:  Fill delay expires (70 + 30 = 100)
         → Refresh triggered!
         → New orders at $0.2298 base
         → create_timestamp = 400s

T=120s:  Bitget update: shift = -0.95%
         Change = 0.15% >= 0.1% threshold → REFRESH TRIGGERED!
         → refresh_pending = True
         → last_fill_timestamp = 120s

T=150s:  Fill delay expires (120 + 30 = 150)
         → Refresh triggered!
         → Price resets to: Real market + New Bitget shift (-0.95%)
         → Drift corrected, realigned with BTC trend
         → create_timestamp = 450s

T=250s:  Level 2 sell order FILLS! (real market activity)
         → Level 2-5 fill detected
         → refresh_on_level2_5_fill = true
         → refresh_pending = True
         → last_fill_timestamp = 250s

T=280s:  Fill delay expires (250 + 30 = 280)
         → Refresh triggered!
         → Orders refreshed
         → create_timestamp = 580s
```

---

## Configuration Guide

### Balanced Configuration (Recommended)

```yaml
# Strategy Settings (BALANCED)
order_refresh_time: 300         # Periodic refresh every 5 minutes (backup)
filled_order_delay: 30          # Wait 30s after fill (balanced)
price_type: "last"              # Use self-trade price to move market
enable_self_trading: true

# Refresh Control
refresh_on_level1_fill: true    # Refresh after Level 1 (move price)
refresh_on_level2_5_fill: true  # Refresh after real market activity

# Bitget Shift Change Detection
price_shift_update_interval: 60 # Check every 60 seconds
price_shift_change_threshold: 0.1  # Refresh if shift changes by >= 0.1%
```

### Configuration for Faster Price Movement

```yaml
filled_order_delay: 10          # Faster cycles = more drift
price_shift_change_threshold: 0.2   # Higher threshold (less corrections)
price_type: "last"              # Direct use of self-trade price
```

**Result:** Maximum drift ~0.435% over 5 minutes, faster movement

### Configuration for Slower, More Stable Movement

```yaml
filled_order_delay: 60          # Slower cycles = less drift
price_shift_change_threshold: 0.05  # Lower threshold (more corrections)
price_type: "mid"               # More stable reference
```

**Result:** Maximum drift ~0.087% typical, more stable

### Configuration Parameters Explained

**`filled_order_delay: 30`**
- Wait time after fill before refreshing
- Balanced: Allows market interaction while maintaining responsiveness
- Range: 10-120 seconds recommended

**`price_shift_change_threshold: 0.1`**
- Minimum Bitget shift change (in percentage) to trigger refresh
- Lower = more sensitive (more refreshes)
- Higher = less sensitive (fewer refreshes)
- Recommended range: 0.05-0.2%

**`refresh_on_level1_fill: true`**
- Refresh after Level 1 self-trades
- `true`: Price moves with each self-trade (your goal)
- `false`: Prevents price contamination, only refresh on real market activity

**`refresh_on_level2_5_fill: true`**
- Refresh after Levels 2-5 fills (real market activity)
- `true`: Responds to external market participants
- `false`: Reduces order churn, only refresh on Level 1 or Bitget changes

**`price_type: "last"`**
- Uses `last_trade_price` directly (your self-trade price)
- Best for moving market price intentionally
- Alternative: `"mid"` for more stable reference

---

## Paper Trading vs Live Trading Behavior

### Critical Difference: Price Source Behavior

**Paper Trading Mode (`cofinex_paper_trade`):**
- Order book comes from **real Cofinex exchange** (WebSocket feed)
- Your self-trades execute in simulation but **do NOT** update the real exchange order book
- `last_trade_price` comes from the **real exchange**, not your paper trades
- `mid_price` comes from the **real exchange** order book

**Live Trading Mode (`cofinex` with exchange-core):**
- Order book is **your own exchange-core** order book
- Self-trades execute and **DO** update the order book
- `last_trade_price` = **your self-trade price** (if using `price_type: "last"`)
- `mid_price` = your own order book (includes your orders)

### How Self-Trades Work in Paper Trading

In paper trading, Level 1 self-trades work differently:

```
Your Orders (Paper Trading):
├─ Level 1 Buy: 0.2290 (stored in _bid_limit_orders)
└─ Level 1 Sell: 0.2287 (stored in _ask_limit_orders)

Real Exchange Order Book (Cofinex WebSocket):
├─ Best Bid: 0.2300
├─ Best Ask: 0.2310
└─ Last Trade: 0.2305 (from real exchange)

Self-Trade Logic:
├─ Every tick, checks: Has real exchange price crossed your limit order?
├─ Buy order fills when: real_best_ask <= your_buy_price (0.2290)
├─ Sell order fills when: real_best_bid >= your_sell_price (0.2287)
└─ Both can fill simultaneously if real exchange price is between them
```

**Key Point:** The self-trade happens, but `last_trade_price` remains 0.2305 (from real exchange), not 0.2287 (your self-trade).

### Impact on Price Reference

#### Using `price_type: "last"` in Paper Trading

```yaml
price_type: "last"  # Uses last_trade_price
```

**Behavior:**
- `get_price_by_type("last")` returns **real exchange's last trade price** (0.2305)
- Your Level 1 self-trade at 0.2287 **does NOT** affect this
- Reference price stays at 0.2305 (or whatever real exchange price is)
- Levels 2-5 calculated relative to **real exchange price**, not your self-trade price
- **Result:** Price does NOT move with your self-trades in paper trading

**Example:**
```
T=0s:    Reference = $0.2305 (real exchange last trade)
         Level 1 orders placed: Buy @ 0.2290, Sell @ 0.2287

T=10s:   Level 1 self-trade executes @ 0.2287 (paper trading)
         → Order fills, balance updates
         → But last_trade_price still = 0.2305 (from real exchange!)

T=40s:   Refresh triggered
         → get_price_by_type("last") = 0.2305 (still real exchange price!)
         → New orders placed relative to 0.2305 (NOT 0.2287)
         → Price does NOT move with your self-trade
```

#### Using `price_type: "mid"` in Paper Trading (Recommended)

```yaml
price_type: "mid"  # Uses (best_bid + best_ask) / 2
```

**Behavior:**
- `get_price_by_type("mid")` returns **real exchange's mid-price**
- Mid-price = (real_best_bid + real_best_ask) / 2
- Your self-trades **do NOT** affect this (order book is from real exchange)
- Reference price stays aligned with **real market conditions**
- **Result:** More stable, tracks real market, but doesn't move with your self-trades

**Example:**
```
T=0s:    Real exchange: Bid=0.2300, Ask=0.2310, Mid=0.2305
         Reference = $0.2305 (real exchange mid)
         Level 1 orders placed

T=10s:   Level 1 self-trade executes (paper trading)
         → Order fills
         → But mid-price still = 0.2305 (from real exchange order book)

T=40s:   Refresh triggered
         → Reference = 0.2305 (still real exchange mid)
         → Orders refreshed at same price level
```

### Recommended Configuration for Paper Trading

For paper trading, use **`price_type: "mid"`** because:

1. ✅ More stable reference (real market conditions)
2. ✅ Not affected by your self-trades (which don't update real exchange order book)
3. ✅ Better reflects external market conditions
4. ✅ Allows you to test strategy logic without price contamination

```yaml
# Paper Trading Configuration
exchange: cofinex_paper_trade
price_type: "mid"              # ⭐ Use mid-price (real exchange order book)
filled_order_delay: 30          # Still balanced
refresh_on_level1_fill: true    # Still refresh (to replenish orders)
refresh_on_level2_5_fill: true  # Still refresh
price_shift_change_threshold: 0.1
```

**Expected Behavior in Paper Trading:**
- Level 1 self-trades execute (orders fill)
- Reference price stays aligned with **real Cofinex market** (via mid-price)
- Bitget shift adjustments still work (adds/subtracts from real market price)
- Orders refresh every 30s after fills, or when Bitget shift changes significantly
- **Price movement:** Driven by Bitget shift changes, not by self-trades

### Recommended Configuration for Live Trading

For live trading with exchange-core, use **`price_type: "last"`** because:

1. ✅ Self-trades update `last_trade_price` (your goal)
2. ✅ Price moves with each Level 1 self-trade
3. ✅ Levels 2-5 follow the moving price
4. ✅ Creates the price movement effect you want

```yaml
# Live Trading Configuration
exchange: cofinex              # Actual connector (not paper_trade)
price_type: "last"             # ⭐ Use last-trade (self-trade price)
filled_order_delay: 30          # Balanced delay
refresh_on_level1_fill: true    # Refresh after Level 1 (move price)
refresh_on_level2_5_fill: true  # Refresh after real market activity
price_shift_change_threshold: 0.1
```

**Expected Behavior in Live Trading:**
- Level 1 self-trade executes → Updates `last_trade_price` = 0.2287
- Reference price = 0.2287 (your self-trade price) + Bitget shift
- New orders placed relative to moved price
- Price continues moving with each self-trade
- **Price movement:** Driven by self-trades AND Bitget shift changes

### Comparison Table

| Aspect | Paper Trading | Live Trading (exchange-core) |
|--------|---------------|------------------------------|
| **Order Book Source** | Real Cofinex exchange (WebSocket) | Your exchange-core |
| **Last Trade Price** | Real exchange trades only | Your self-trades update it |
| **Mid Price** | Real exchange order book | Your order book (includes your orders) |
| **Self-Trade Impact** | Executes but doesn't update order book | Executes AND updates order book |
| **Recommended `price_type`** | `"mid"` (stable, tracks real market) | `"last"` (moves with self-trades) |
| **Price Movement** | Via Bitget shift changes only | Via self-trades + Bitget shifts |
| **Refresh Triggers** | Same (fill-based, Bitget, periodic) | Same (fill-based, Bitget, periodic) |

### Current Config Analysis

Your current config has:
```yaml
exchange: cofinex_paper_trade
price_type: "last"  # ⚠️ This won't work as intended for paper trading!
```

**Issue:** In paper trading, `price_type: "last"` will use the real exchange's last trade price, not your self-trade price. So your Level 1 self-trades won't move the reference price.

**Solution for Paper Trading:**
```yaml
price_type: "mid"  # Better for paper trading - tracks real market
```

**Or keep `"last"` but understand:** It will track real Cofinex exchange trades, not your self-trades. Price movement will be driven by external market activity and Bitget shifts, not by your Level 1 self-trades.

## Troubleshooting

### Issue: Price Drifting Too Much

**Symptoms:** Price moves far from expected range

**Causes:**
- `price_shift_change_threshold` too high (not catching Bitget changes)
- `filled_order_delay` too short (too frequent refreshes)
- Bitget API not updating

**Solution:**
```yaml
price_shift_change_threshold: 0.05  # Lower threshold (more sensitive)
filled_order_delay: 60              # Longer delay (slower movement)
```

### Issue: Not Refreshing After Level 1 Fills

**Check:**
- `refresh_on_level1_fill` should be `true`
- Check logs for "Level 1 fill detected" messages
- Verify `filled_order_delay` is not too long

**Solution:**
```yaml
refresh_on_level1_fill: true    # Enable Level 1 refresh
filled_order_delay: 30          # Reasonable delay
```

### Issue: Too Many Refreshes

**Causes:**
- `price_shift_change_threshold` too low
- `filled_order_delay` too short
- Frequent Level 1 fills

**Solution:**
```yaml
price_shift_change_threshold: 0.2   # Higher threshold (less sensitive)
filled_order_delay: 60              # Longer delay
```

### Issue: Orders Not Aligned with BTC Trend

**Causes:**
- Bitget API not updating
- `price_shift_change_threshold` too high
- Periodic refresh not happening

**Solution:**
```yaml
price_shift_change_threshold: 0.05  # Lower threshold
order_refresh_time: 300             # Ensure periodic refresh
```

---

## Summary

### Key Takeaways

1. **Price Movement Goal Achieved**: Level 1 self-trades move market price, Levels 2-5 follow
2. **Balanced Configuration**: 30s delay provides controlled movement with market interaction
3. **Drift Control**: Bitget corrections (every 2-3 minutes) keep drift at 0.17-0.26% typically
4. **Safe Maximum**: Periodic refresh (5 minutes) caps maximum drift at 0.435%
5. **Intelligent Refresh**: Three trigger types ensure optimal refresh timing

### Current vs Balanced Behavior

| Aspect | Current (Old) | Balanced (New) |
|--------|---------------|----------------|
| **Fill delay** | 10 seconds | 30 seconds |
| **Level 1 refresh** | Always | Configurable (`refresh_on_level1_fill`) |
| **Bitget trigger** | No refresh | Refresh on significant change (≥0.1%) |
| **Price source** | "mid" | "last" (uses self-trade price) |
| **Drift control** | Periodic only | Multiple triggers (fills, Bitget, periodic) |

### Expected Behavior

With balanced configuration:
- ✅ Price moves via Level 1 self-trades (0.0435% per cycle)
- ✅ Movement is controlled (0.17-0.26% drift typically)
- ✅ Realigns with BTC trend (Bitget corrections every 2-3 minutes)
- ✅ Allows market interaction (30s delay)
- ✅ Safe maximum drift (0.435% cap over 5 minutes)

---

**Document Version:** 2.0
**Last Updated:** 2026-01-10
**Strategy Version:** multi_level_self_trading.py
**Configuration:** Balanced (30s delay, 0.1% threshold, conditional refresh)
