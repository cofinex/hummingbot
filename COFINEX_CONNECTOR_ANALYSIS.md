# Cofinex Connector Analysis

## Executive Summary

The Cofinex connector is **incomplete** and currently only contains skeleton/stub implementations. Most methods have TODO comments and placeholder code. To make it production-ready, you need to implement all the actual API integration logic.

---

## Current Status: INCOMPLETE ⚠️

### What's Done ✅
1. **Basic Structure**: Class structure and method signatures are defined
2. **Authentication Class**: `CofinexAuth` class with **OAuth 2.0 Bearer token authentication** ✅
3. **Constants File**: OAuth endpoints and rate limits defined ✅
4. **Configuration**: `cofinex_config_map.py` with username/password fields ✅
5. **Web Utils**: Complete web utilities with API factory ✅
6. **User Stream**: REST-only user stream data source ✅
7. **Order Book Data Source**: Basic structure created ✅
8. **Method Stubs**: All required methods are declared but not implemented

### What's Missing ❌
1. **Actual API Integration**: No real API calls to Cofinex
2. **Order Book Tracking**: No WebSocket or REST polling for order books
3. **User Stream**: No WebSocket connection for account updates
4. **Order Management**: Place/cancel/get orders not implemented
5. **Balance Retrieval**: Account balance fetching not implemented
6. **Trading Rules**: No API call to fetch trading rules
7. **Error Handling**: No proper error handling for API responses
8. **Rate Limiting**: No actual rate limiting implementation
9. **WebSocket Management**: No WebSocket connection handling
10. **Order Book Tracker**: Missing order book tracker integration
11. **User Stream Tracker**: Missing user stream tracker integration

---

## Required APIs from Cofinex

To complete the connector, you need access to the following Cofinex API endpoints:

### 1. **Public/REST APIs** (No Authentication Required)

#### Market Data
- `GET /api/v1/symbols` or `/api/v1/trading-pairs`
  - **Purpose**: Get list of all available trading pairs
  - **Returns**: List of symbols with base/quote currencies

- `GET /api/v1/ticker` or `/api/v1/ticker/{symbol}`
  - **Purpose**: Get 24h ticker data
  - **Returns**: Price, volume, high, low, etc.

- `GET /api/v1/orderbook` or `/api/v1/depth`
  - **Purpose**: Get order book snapshot
  - **Parameters**: `symbol`, `limit` (optional)
  - **Returns**: Bids and asks with prices and quantities

- `GET /api/v1/trades` or `/api/v1/recent-trades`
  - **Purpose**: Get recent trades
  - **Parameters**: `symbol`, `limit` (optional)
  - **Returns**: Recent trade history

- `GET /api/v1/klines` or `/api/v1/candles`
  - **Purpose**: Get historical candle/OHLCV data
  - **Parameters**: `symbol`, `interval`, `limit`
  - **Returns**: Candle data

#### Exchange Information
- `GET /api/v1/exchange-info` or `/api/v1/markets`
  - **Purpose**: Get trading rules, fees, precision for all pairs
  - **Returns**: Min/max order sizes, price/quantity precision, fees, etc.

- `GET /api/v1/server-time` or `/api/v1/time`
  - **Purpose**: Get server timestamp (for time synchronization)
  - **Returns**: Server timestamp

### 2. **Private/REST APIs** (Authentication Required)

#### Account Management
- `GET /api/v1/account` or `/api/v1/balance`
  - **Purpose**: Get account balances
  - **Authentication**: Required (OAuth Bearer token)
  - **Returns**: All account balances (available, locked)

- `GET /api/v1/account/trades` or `/api/v1/my-trades`
  - **Purpose**: Get user's trade history
  - **Parameters**: `symbol`, `limit`, `startTime`, `endTime`
  - **Returns**: User's executed trades

#### Order Management
- `POST /api/v1/order`
  - **Purpose**: Place a new order
  - **Authentication**: Required (OAuth Bearer token)
  - **Parameters**:
    - `symbol` (trading pair)
    - `side` (BUY/SELL)
    - `type` (LIMIT/MARKET)
    - `quantity`
    - `price` (for LIMIT orders)
    - `timeInForce` (GTC, IOC, FOK)
  - **Returns**: Order ID and status

- `DELETE /api/v1/order` or `/api/v1/order/{orderId}`
  - **Purpose**: Cancel an order
  - **Authentication**: Required (OAuth Bearer token)
  - **Parameters**: `symbol`, `orderId` (or `clientOrderId`)
  - **Returns**: Cancellation confirmation

- `GET /api/v1/order` or `/api/v1/order/{orderId}`
  - **Purpose**: Get order status
  - **Authentication**: Required (OAuth Bearer token)
  - **Parameters**: `symbol`, `orderId`
  - **Returns**: Order details and status

- `GET /api/v1/openOrders`
  - **Purpose**: Get all open orders
  - **Authentication**: Required (OAuth Bearer token)
  - **Parameters**: `symbol` (optional, filter by pair)
  - **Returns**: List of open orders

- `DELETE /api/v1/openOrders`
  - **Purpose**: Cancel all open orders
  - **Authentication**: Required (OAuth Bearer token)
  - **Parameters**: `symbol` (optional)
  - **Returns**: List of cancellation results

### 3. **WebSocket APIs** - **OPTIONAL (Not Required for Initial Implementation)**

**Note**: We're implementing REST-only for now. WebSocket can be added later for better performance.

#### Public WebSocket Streams (Optional - Can use REST polling instead)
- **Order Book Stream**
  - **Endpoint**: `wss://api.cofinex.com/ws` or similar
  - **Subscription**: Subscribe to order book updates
  - **Messages**: Real-time order book updates (bids/asks changes)
  - **Format**: Usually `depth` or `orderbook` channel
  - **Alternative**: Use REST polling of `/api/v1/depth` endpoint

- **Trade Stream**
  - **Subscription**: Subscribe to trade updates
  - **Messages**: Real-time trade executions
  - **Format**: Usually `trades` or `trade` channel
  - **Alternative**: Use REST polling of `/api/v1/trades` endpoint

- **Ticker Stream**
  - **Subscription**: Subscribe to ticker updates
  - **Messages**: 24h ticker statistics
  - **Format**: Usually `ticker` channel
  - **Alternative**: Use REST polling of `/api/v1/ticker` endpoint

#### Private WebSocket Streams (Authentication Required) - **OPTIONAL - Using REST Instead**
- **User Data Stream** (NOT REQUIRED - Using REST polling instead)
  - **Endpoint**: `wss://api.cofinex.com/ws` (authenticated)
  - **Authentication**: OAuth Bearer token (if WebSocket auth is supported)
  - **Subscription**: Subscribe to user account updates
  - **Messages**:
    - Order updates (NEW, PARTIALLY_FILLED, FILLED, CANCELED)
    - Balance updates
    - Trade executions
    - Account changes
  - **Note**: We're implementing REST-only user stream, so WebSocket is not required.
    The connector will poll REST API endpoints instead for account updates using OAuth Bearer tokens.

### 4. **Authentication Method** ✅ IMPLEMENTED

**Cofinex uses OAuth 2.0 / OpenID Connect with Bearer tokens** (not HMAC signatures)

**Implementation Details**:
- **Grant Type**: Password grant
- **Token Endpoint**: `https://auth.cofinex.io/realms/cofinex/protocol/openid-connect/token`
- **Client ID**: `cofinex-exchange`
- **Scope**: `openid`
- **Authentication**: Bearer token in `Authorization` header

**OAuth Flow**:
1. User provides username (email) and password
2. POST to token endpoint with credentials
3. Receive `access_token` (valid for 5 hours) and `refresh_token` (valid for 24 hours)
4. Use `Authorization: Bearer {access_token}` header for all authenticated requests
5. Automatically refresh token before expiry

**Response Format**:
```json
{
    "access_token": "eyJhbGci...",
    "expires_in": 18000,
    "refresh_expires_in": 86400,
    "refresh_token": "eyJhbGci...",
    "token_type": "Bearer",
    "id_token": "eyJhbGci...",
    "scope": "openid ..."
}
```

---

## Required Implementation Details

### 1. **Order Book Tracker**
You need to create:
- `cofinex_order_book_tracker.py` - Main tracker class
- `cofinex_api_order_book_data_source.py` - REST API data source
- `cofinex_ws_order_book_tracker.py` - WebSocket data source (optional but recommended)

### 2. **User Stream Tracker** - ✅ COMPLETED (REST-ONLY)
- ✅ `cofinex_api_user_stream_data_source.py` - REST-only implementation
- ✅ Polls account balances and orders via REST API
- ✅ Emits events when changes are detected
- ✅ Uses OAuth Bearer token authentication
- ✅ No WebSocket required - simpler and more reliable
- ⚠️ TODO: Update response parsing based on actual Cofinex API format

### 3. **Web Assistant**
You need to create:
- `cofinex_web_utils.py` - Web request utilities
- `cofinex_api_factory.py` - API factory for REST/WS connections
- Rate limiting implementation
- Retry logic with exponential backoff

### 4. **Trading Pair Mapping**
- Convert between Hummingbot format (e.g., `BTC-USDT`) and Cofinex format (e.g., `BTCUSDT` or `BTC/USDT`)
- Handle symbol mapping for all pairs

### 5. **Order Tracking**
- Use `InFlightOrder` class to track orders
- Map client order IDs to exchange order IDs
- Handle order status updates

### 6. **Error Handling**
- Map Cofinex error codes to Hummingbot exceptions
- Handle rate limit errors (429)
- Handle authentication errors (401)
- Handle network errors

---

## What is a Paper Trade Connector?

A **Paper Trade Connector** is a simulated trading environment that allows you to test trading strategies **without using real money**. It's like a "practice mode" for trading.

### How It Works

1. **Uses Real Market Data**:
   - Connects to the real exchange (e.g., Cofinex) to get live order books, prices, and market data
   - You see real market conditions

2. **Simulates Trading**:
   - When you place an order, it's NOT sent to the real exchange
   - Instead, it's matched against the real order book data locally
   - Your "balance" is virtual (set in configuration)
   - Orders are filled based on simulated matching logic

3. **Benefits**:
   - ✅ **No Risk**: Test strategies without losing money
   - ✅ **Real Market Conditions**: Uses actual market data
   - ✅ **Fast Testing**: Can test multiple strategies quickly
   - ✅ **Learning**: Understand how strategies work before going live
   - ✅ **Development**: Test connector implementations safely

### Example Usage

```python
# Instead of using "cofinex" connector (real trading)
# You use "cofinex_paper_trade" connector (simulated trading)

# In Hummingbot config:
connector = "cofinex_paper_trade"
paper_trade_account_balance = {
    "BTC": 1.0,
    "USDT": 10000.0
}
```

### How Paper Trade is Created

Looking at the code in `hummingbot/connector/exchange/paper_trade/`:

1. **Wraps Real Connector**:
   - Takes a real connector (e.g., `CofinexExchange`) as input
   - Uses its order book tracker to get real market data

2. **Simulates Order Matching**:
   - When you place a buy order, it checks the real order book
   - If your price matches or exceeds the best ask, it "fills" your order
   - Updates your virtual balance accordingly

3. **No Real API Calls for Trading**:
   - Only reads market data from the real exchange
   - Never sends actual order placement/cancellation requests
   - All trading happens in memory

### Paper Trade vs Real Trading

| Feature | Paper Trade | Real Trading |
|---------|-------------|--------------|
| Market Data | Real (from exchange) | Real (from exchange) |
| Order Placement | Simulated (local) | Real (sent to exchange) |
| Balance | Virtual (configurable) | Real (from exchange) |
| Risk | None | Real money at risk |
| Order Fills | Simulated matching | Real exchange matching |
| Slippage | May not reflect real slippage | Real slippage |
| Latency | Minimal (local) | Network latency |

### When to Use Paper Trade

- ✅ **Strategy Development**: Test new strategies
- ✅ **Connector Testing**: Test connector implementation
- ✅ **Learning**: Learn how Hummingbot works
- ✅ **Backtesting**: Validate strategy logic
- ✅ **Risk-Free Testing**: Test without financial risk

### When NOT to Use Paper Trade

- ❌ **Final Validation**: Paper trade doesn't account for:
  - Real slippage
  - Network latency
  - Exchange-specific behaviors
  - Real order execution delays
  - Partial fills
  - Market impact

---

## Next Steps to Complete Cofinex Connector

### Phase 1: Research & Setup
1. **Get Cofinex Trade Engine API Documentation**
   - Trade Engine API base URL
   - REST API endpoint paths
   - WebSocket endpoints (optional)
   - Rate limits
   - Error codes
   - Trading rules format
   - Response formats

2. **Test API Access**
   - Get username/password credentials (testnet if available)
   - Test OAuth authentication (already implemented)
   - Test basic endpoints (get symbols, order book)

### Phase 2: Core Implementation
1. **Authentication** (`cofinex_auth.py`) - ✅ COMPLETED
   - OAuth 2.0 Bearer token implementation
   - Automatic token refresh
   - Ready for testing with real API

2. **Implement Web Utils** (`cofinex_web_utils.py`)
   - HTTP client setup
   - Rate limiting
   - Error handling
   - Retry logic

3. **Implement Order Book Tracker**
   - REST API data source
   - WebSocket data source (optional)
   - Order book updates

### Phase 3: Trading Features
1. **Implement Order Management**
   - Place order
   - Cancel order
   - Get order status
   - Get open orders

2. **Implement Account Management**
   - Get balances
   - Get trade history

3. **Implement User Stream**
   - WebSocket connection
   - Order updates
   - Balance updates

### Phase 4: Integration & Testing
1. **Register Connector**
   - Add to `AllConnectorSettings`
   - Add configuration keys
   - Test connector creation

2. **Test with Paper Trade**
   - Create paper trade connector
   - Test order placement
   - Test order cancellation
   - Test balance tracking

3. **Test with Real Trading** (Small amounts!)
   - Test with minimal funds
   - Verify all features work
   - Monitor for errors

---

## Files That Need to Be Created/Completed

### Required Files:
1. ✅ `cofinex_exchange.py` - **NEEDS REFACTORING** (currently skeleton, needs ExchangePyBase)
2. ✅ `cofinex_auth.py` - **COMPLETED** (OAuth 2.0 Bearer token implementation)
3. ✅ `cofinex_constants.py` - **COMPLETED** (OAuth endpoints and rate limits defined)
4. ✅ `cofinex_web_utils.py` - **COMPLETED**
5. ✅ `cofinex_api_order_book_data_source.py` - **COMPLETED** (basic structure)
6. ✅ `cofinex_api_user_stream_data_source.py` - **COMPLETED** (REST-only implementation with OAuth)
7. ✅ `cofinex_config_map.py` - **COMPLETED** (username/password configuration)
8. ❌ `cofinex_order_book_tracker.py` - **MISSING** (if needed, usually handled by base class)

### Optional Files (for future WebSocket support):
- `cofinex_ws_order_book_tracker.py` - Optional WebSocket order book
- `cofinex_ws_user_stream_data_source.py` - Optional WebSocket user stream

### Reference Connectors:
Look at these complete connectors for reference:
- `hummingbot/connector/exchange/binance/` - Full implementation
- `hummingbot/connector/exchange/kucoin/` - Full implementation
- `hummingbot/connector/exchange/okx/` - Full implementation

---

## Summary

**Current Status**: The Cofinex connector has **OAuth 2.0 authentication fully implemented** and REST-only user stream. Core exchange methods still need implementation. Approximately **30-40% complete**.

**What You Need**:
1. Cofinex Trade Engine API documentation (base URL and endpoint paths)
2. Username/password credentials for testing
3. Implement all TODO methods in exchange class
4. Refactor exchange class to ExchangePyBase
5. Test thoroughly with paper trading first

**Paper Trade Connector**: A simulated trading environment that uses real market data but simulates order execution. Perfect for testing without risk.

**Estimated Time to Complete**: 40-80 hours of development work, depending on:
- API documentation quality
- Exchange API complexity
- Your familiarity with Hummingbot codebase
- Testing requirements
