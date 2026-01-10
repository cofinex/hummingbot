# Cofinex Connector - Quick Start Guide

## Overview

This guide shows you how to run Hummingbot with the Cofinex connector for both paper trading and live trading.

## Prerequisites

- Hummingbot installed and configured
- Python environment set up
- (For live trading) Cofinex account credentials

---

## Option 1: Paper Trading (Recommended for Testing)

Paper trading uses simulated orders with real market data. **No credentials needed!**

### Step 1: Start Hummingbot

```bash
cd /Users/santoshpadhi/hummingbot
python bin/hummingbot.py
```

### Step 2: Connect to Paper Trading

Once Hummingbot starts, you'll see a prompt `>>>`. Type:

```
connect cofinex_paper_trade
```

**Note**: Paper trading doesn't require credentials, so you won't be prompted for username/password.

### Step 3: Verify Connection

You should see messages like:
- `"Initialized trading pair symbol map with X pairs"`
- `"Updated trading rules for X trading pairs"`
- `"Started order book tracking for X trading pairs"`
- `"You are now connected to cofinex_paper_trade."`

### Step 4: (Optional) Configure for Local Testing with exchange-core

If you're testing against a local exchange-core instance, configure both WebSocket prefix and REST API base URL:

1. **Option A: Via Config File** (Recommended for persistent setup)
   - Edit `conf/connectors/cofinex.yml`
   - Add these lines:
     ```yaml
     cofinex_ws_prefix: "dev:santosh"
     cofinex_rest_api_base_url: "http://localhost:8001"
     ```
   - Restart Hummingbot and reconnect

2. **Option B: Via Environment Variables** (Quick, temporary)
   ```bash
   export COFINEX_WS_PREFIX="dev:santosh"
   export COFINEX_REST_API_BASE_URL="http://localhost:8001"
   # or
   export DEV_NAMESPACE="dev:santosh"
   ```
   - Then start Hummingbot

**What these do:**
- `cofinex_ws_prefix`: Adds namespace to WebSocket subscriptions (Books, Trade, Ticker channels)
- `cofinex_rest_api_base_url`: Routes REST API calls (orders, accounts) to local exchange-core instead of production

---

## Option 2: Live Trading (Production)

Live trading uses your actual Cofinex account and real money!

### Step 1: Configure Credentials (Already Done!)

Your credentials are already encrypted in `conf/connectors/cofinex.yml`. The config file contains:
- `cofinex_username`: Your encrypted email/username
- `cofinex_password`: Your encrypted password
- `domain`: "main" (for production)

**Note**: The credentials are encrypted and secure.

### Step 2: Start Hummingbot

```bash
cd /Users/santoshpadhi/hummingbot
python bin/hummingbot.py
```

When prompted, enter your Hummingbot password to decrypt credentials.

### Step 3: Connect to Live Trading

Type:

```
connect cofinex
```

You should see:
- `"You are now connected to cofinex."`
- Balance information (if implemented)
- Trading pair list

### Step 4: For Local Testing with exchange-core

If you're running against a local exchange-core instance instead of the real Cofinex exchange:

1. **Configure Local Endpoints**:
   - Edit `conf/connectors/cofinex.yml`
   - Add:
     ```yaml
     cofinex_ws_prefix: "dev:santosh"
     cofinex_rest_api_base_url: "http://localhost:8001"
     ```

2. **Verify exchange-core is running**:
   - Exchange Core (Java) on port 8000
   - FastAPI Trading API on port 8001 (this is where REST API calls will go)
   - FastAPI Admin API on port 8002
   - Background jobs running

---

## Using with Multi-Level Self-Trading Strategy

### Step 1: Create or Load Strategy Configuration

Your strategy config should be at:
`conf/scripts/conf_multi_level_self_trading.yml`

### Step 2: Set Exchange in Strategy Config

Open the config file and ensure:
```yaml
exchange: cofinex_paper_trade  # For paper trading
# OR
exchange: cofinex              # For live trading
```

### Step 3: Start Strategy

In Hummingbot, type:
```
start
```

Select your strategy:
```
1 - multi_level_self_trading
```

### Step 4: Monitor Strategy

Watch for:
- Order placement logs
- Fill notifications
- Price updates from Bitget
- Order refresh cycles

---

## Configuration Options

### WebSocket Prefix (for Local Testing)

The `cofinex_ws_prefix` field allows you to namespace WebSocket subscriptions when testing locally:

**Production** (leave empty):
```yaml
cofinex_ws_prefix: ""  # or omit entirely
```

**Local Testing**:
```yaml
cofinex_ws_prefix: "dev:santosh"  # Your namespace
```

**Environment Variable Alternative**:
```bash
export COFINEX_WS_PREFIX="dev:santosh"
# or
export DEV_NAMESPACE="dev:santosh"
```

**Priority Order**:
1. Parameter passed to connector (programmatic)
2. Config file value (`cofinex_ws_prefix` in `cofinex.yml`)
3. Environment variable (`COFINEX_WS_PREFIX` or `DEV_NAMESPACE`)

### REST API Base URL (for Local Testing)

The `cofinex_rest_api_base_url` field allows you to route REST API calls to a local exchange-core instance instead of production:

**Production** (leave empty):
```yaml
cofinex_rest_api_base_url: ""  # or omit entirely
# Uses default: https://tradeapi1.cofinex.io
```

**Local Testing**:
```yaml
cofinex_rest_api_base_url: "http://localhost:8001"  # Local FastAPI Trading API
```

**Environment Variable Alternative**:
```bash
export COFINEX_REST_API_BASE_URL="http://localhost:8001"
```

**Priority Order**:
1. Config file value (`cofinex_rest_api_base_url` in `cofinex.yml`)
2. Environment variable (`COFINEX_REST_API_BASE_URL`)
3. Default production URL (`https://tradeapi1.cofinex.io`)

**What Gets Routed to This URL:**
- `/api/v1/account` - Balance queries
- `/api/v1/orders` - Order management
- `/api/v1/order` - Place/cancel orders
- `/api/v1/openOrders` - Open orders
- `/api/v1/myTrades` - Trade history

**Note:** Public market data endpoints (order book, trading pairs) continue using the production market data API (`https://marketdata.cofinex.io`) regardless of this setting.

### Domain Configuration

Available domains:
- `main`: Production Cofinex exchange (default)
- `testnet`: Testnet (if available)

Change in `conf/connectors/cofinex.yml`:
```yaml
domain: main  # or testnet
```

---

## Troubleshooting

### Connection Fails

**Check**:
1. Internet connection
2. Cofinex API accessibility: `https://marketdata.cofinex.io/spot/v1/tradepair`
3. Credentials are correct (for live trading)
4. Check logs: `logs/logs_conf_multi_level_self_trading.log`

### Paper Trading Not Available

**Check**:
1. `cofinex` is in `conf/conf_client.yml` under `paper_trade_exchanges`:
   ```yaml
   paper_trade_exchanges:
     - binance
     - cofinex  # Make sure this is here
   ```
2. Restart Hummingbot after adding

### WebSocket Prefix Not Working

**Check**:
1. Config file syntax is correct (no extra spaces)
2. Environment variable is set before starting Hummingbot
3. Check logs for subscription payloads:
   ```
   grep "Subscribing to" logs/logs_conf_multi_level_self_trading.log
   ```
   You should see `"prefix": "dev:santosh"` in the payload

### Order Books Don't Load

**Check**:
1. Trading pairs are valid (e.g., "CNX-USDT", "BTC-USDT")
2. Cofinex has these pairs available
3. WebSocket connection is established (check logs)
4. No rate limit errors

### Exchange-Core Not Receiving Subscriptions

**For Local Testing**:
1. Verify exchange-core websocket server is running
2. Check that prefix matches your exchange-core namespace
3. Verify WebSocket subscription payload includes `"prefix": "dev:santosh"`
4. Check exchange-core logs for incoming subscriptions

### REST API Calls Not Reaching Local exchange-core

**For Local Testing**:
1. Verify FastAPI Trading API is running on port 8001:
   ```bash
   lsof -i :8001
   ```
2. Check that `cofinex_rest_api_base_url` is set correctly:
   ```yaml
   cofinex_rest_api_base_url: "http://localhost:8001"
   ```
3. Verify the URL format (must include `http://` or `https://`)
4. Check logs for REST API call URLs - they should show `http://localhost:8001/api/v1/...`
5. Ensure exchange-core FastAPI service is accepting connections

---

## Example Workflows

### Workflow 1: Local Testing with exchange-core

```bash
# Terminal 1: Start exchange-core
cd /Users/santoshpadhi/IdeaProjects/exchange-core
./start-local-mac.sh

# Terminal 2: Start background jobs
./start-jobs-mac.sh

# Terminal 3: Start Hummingbot with local configuration
export COFINEX_WS_PREFIX="dev:santosh"
export COFINEX_REST_API_BASE_URL="http://localhost:8001"
cd /Users/santoshpadhi/hummingbot
python bin/hummingbot.py
```

**Or configure via config file** (`conf/connectors/cofinex.yml`):
```yaml
cofinex_ws_prefix: "dev:santosh"
cofinex_rest_api_base_url: "http://localhost:8001"
```

Then in Hummingbot:
```
connect cofinex_paper_trade
start
```

**What this does:**
- WebSocket subscriptions go to exchange-core with `"prefix": "dev:santosh"`
- REST API calls (orders, accounts) go to `http://localhost:8001`
- Market data (order book) still comes from production Cofinex API

### Workflow 2: Production Trading

```bash
# Start Hummingbot
cd /Users/santoshpadhi/hummingbot
python bin/hummingbot.py
# Enter password when prompted
```

Then in Hummingbot:
```
connect cofinex
start
```

---

## Quick Reference Commands

| Command | Description |
|---------|-------------|
| `connect cofinex_paper_trade` | Connect to paper trading (no credentials) |
| `connect cofinex` | Connect to live trading (needs credentials) |
| `start` | Start a strategy |
| `stop` | Stop current strategy |
| `status` | Show current status |
| `balance` | Show account balance |
| `help` | Show available commands |

---

## Configuration Summary

### Complete Local Testing Configuration

For full local testing with exchange-core, your `conf/connectors/cofinex.yml` should look like:

```yaml
##########################
###   cofinex config   ###
##########################

connector: cofinex

# Credentials (encrypted - for live trading only)
cofinex_username: <encrypted>
cofinex_password: <encrypted>

domain: main

# Local testing configuration
cofinex_ws_prefix: "dev:santosh"                    # WebSocket namespace
cofinex_rest_api_base_url: "http://localhost:8001"  # REST API base URL
```

### Production Configuration

For production, simply omit or leave empty the local testing fields:

```yaml
##########################
###   cofinex config   ###
##########################

connector: cofinex

cofinex_username: <encrypted>
cofinex_password: <encrypted>

domain: main

# Leave empty or omit for production
cofinex_ws_prefix: ""
cofinex_rest_api_base_url: ""
```

---

## Next Steps

After successfully connecting:

1. ✅ Test order book data retrieval
2. ✅ Test trading pair discovery
3. ✅ Start your multi-level self-trading strategy
4. ✅ Monitor logs for any issues
5. ✅ Adjust strategy parameters as needed

For more details, see:
- `docs/cofinex/COFINEX_TESTING_GUIDE.md`
- `docs/STRATEGY_OPERATION_AND_OPTIMIZATION.md`
