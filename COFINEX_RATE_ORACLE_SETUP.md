# Cofinex Rate Oracle and Server Time Setup Guide

## Overview

I've created a Cofinex rate source to replace Binance for the rate oracle. This will eliminate the "Error calculating fee paid in CNX: Could not find the exchange rate" errors.

**Note:** Cofinex connector already uses its own server time endpoint (`/time`), but you may need to verify the endpoint path is correct.

## What Was Created

1. **`hummingbot/core/rate_oracle/sources/cofinex_rate_source.py`** - Cofinex rate source implementation
2. **Updated `hummingbot/core/rate_oracle/rate_oracle.py`** - Registered Cofinex as a rate source

## Required Endpoint

The Cofinex rate source uses the **market endpoint** to get price data for trading pairs.

### Endpoint Details

**URL:** `GET https://marketdata.cofinex.io/spot/v1/market/{SYMBOL}`

**Example:** `GET https://marketdata.cofinex.io/spot/v1/market/CNX_USDT`

**Note:** This is a per-pair endpoint. The code will fetch prices for each trading pair individually.

### Actual Response Format

Based on the [Cofinex API](https://marketdata.cofinex.io/spot/v1/market/CNX_USDT), the response format is:

```json
{
    "code": "200",
    "msg": "success",
    "data": {
        "trading_pairs": "CNX_USDT",
        "base_currency": "CNX",
        "quote_currency": "USDT",
        "price_change_percent_24h": -10.371319,
        "last_price": 0.21,
        "highest_bid": 0.3144,
        "lowest_ask": 0.21,
        "highest_price_24h": 0.3144,
        "lowest_price_24h": 0.21,
        "base_volume": 22666.27,
        "quote_volume": 4759.9167,
        "listed_at": 1768905109,
        "updated_at": 1768905109
    }
}
```

### Required Fields

The endpoint must return at least one of these price fields:

1. **`last_price`** - Last traded price (preferred)
2. **`highest_bid`** - Best bid price
3. **`lowest_ask`** - Best ask price

**If both `highest_bid` and `lowest_ask` are provided, the code calculates mid price: `(highest_bid + lowest_ask) / 2`**

**If only `last_price` is provided, it uses that directly.**

### Symbol Format

- **API format:** `CNX_USDT` (underscore separator, uppercase)
- **Hummingbot format:** The code converts to `CNX-USDT` (hyphen separator)

## How to Use

### Step 1: Update Config

Edit `conf/conf_client.yml`:

```yaml
rate_oracle_source:
  name: cofinex  # Changed from "binance"
```

### Step 2: Verify Endpoint

Test your market endpoint:

```bash
curl https://marketdata.cofinex.io/spot/v1/market/CNX_USDT
```

Expected response:
```json
{
    "code": "200",
    "msg": "success",
    "data": {
        "trading_pairs": "CNX_USDT",
        "last_price": 0.21,
        "highest_bid": 0.3144,
        "lowest_ask": 0.21,
        ...
    }
}
```

### Step 3: Update Code (if needed)

If your endpoint format differs from the expected formats, update the `_get_prices_from_api()` method in:
`hummingbot/core/rate_oracle/sources/cofinex_rate_source.py`

Look for the section that parses the response and adjust it to match your API format.

## Current Implementation

The rate source supports two methods:

1. **Via Exchange Connector** (if `get_all_pairs_prices()` is implemented in `CofinexExchange`)
2. **Direct API Call** (uses `aiohttp` to call the ticker endpoint directly)

The code will automatically try the exchange connector first, then fall back to direct API calls.

## Testing

After setting up the endpoint, test it:

```python
# In Hummingbot CLI
rate CNX-USDT
```

This should show:
```
Source: cofinex
1 CNX = 0.25 USDT
```

## Troubleshooting

### Error: "Could not find the exchange rate"

1. Check that the ticker endpoint is accessible
2. Verify the response format matches one of the expected formats
3. Check logs for API errors

### Error: "ImportError: No module named 'cofinex_rate_source'"

The file should be at:
`hummingbot/core/rate_oracle/sources/cofinex_rate_source.py`

If it's missing, the rate oracle will fall back to Binance (with a warning).

## Alternative: Use Order Book

If you don't have a ticker endpoint, you can use the order book to calculate mid prices:

1. Get order book: `GET /spot/v1/orderbook/{SYMBOL}?depth=1`
2. Extract best bid and ask
3. Calculate mid price: `(best_bid + best_ask) / 2`

This would require modifying `_get_prices_from_api()` to call the order book endpoint instead.

## Server Time Endpoint

The Cofinex connector already uses its own server time endpoint for time synchronization. However, you should verify the endpoint is correct.

### Current Configuration

**Endpoint Path:** `/time` (defined in `cofinex_constants.py`)

**Current URL Construction:**
- If path starts with `/spot/v1/` → Uses `MARKET_DATA_BASE_URL` (`https://marketdata.cofinex.io`)
- Otherwise → Uses `BASE_PATH_URL` (`http://localhost:8001` for local, or `https://tradeapi1.cofinex.io` for production)

**Current Issue:** Since `/time` doesn't start with `/spot/v1/`, it's using the trade engine API base URL.

### Recommended Fix

If your server time endpoint is on the market data API, update `cofinex_constants.py`:

```python
SERVER_TIME_PATH_URL = "/spot/v1/time"  # Changed from "/time"
```

**OR** if it's on the trade engine API, ensure `BASE_PATH_URL` is correct:

```python
BASE_PATH_URL = {
    "main": "https://tradeapi1.cofinex.io",  # Production URL
}
```

### Expected Response Format

The server time endpoint should return:

```json
{
    "serverTime": 1736559585000
}
```

Where `serverTime` is in **milliseconds** (Unix timestamp).

The code converts this to seconds automatically.

### Verify Endpoint

Test your server time endpoint:

```bash
# If on market data API:
curl https://marketdata.cofinex.io/spot/v1/time

# OR if on trade engine API:
curl https://tradeapi1.cofinex.io/time
```

## Questions?

If your endpoint format is different, share:
1. The actual endpoint URL
2. A sample response
3. Any authentication requirements

I can help adapt the code to match your API format.
