# Cofinex Connector - Pending REST API Implementations

This document lists all REST API methods that need to be implemented for the Cofinex exchange connector.

## Status
- ✅ **Implemented**: Paper trading mode working
- ⚠️ **Partially Implemented**: Has paper trading stub, needs live trading REST API
- ❌ **Not Implemented**: Needs full implementation

---

## 1. Order Management APIs

### 1.1. Place Order (Live Trading)
**Method**: `_place_order()`
**Status**: ⚠️ Partially Implemented (paper trading only)
**Location**: `cofinex_exchange.py:1020-1120`
**Current**: Returns `NotImplementedError` for live trading
**Required API Endpoint**: `POST /spot/v1/order` (or similar)
**Parameters Needed**:
- Trading pair (symbol)
- Side (BUY/SELL)
- Order type (LIMIT/MARKET)
- Quantity
- Price (for LIMIT orders)
- Time in force

**Expected Response Format**:
```json
{
  "code": "200",
  "msg": "success",
  "data": {
    "orderId": "...",
    "symbol": "...",
    "status": "...",
    ...
  }
}
```

---

### 1.2. Cancel Order (Live Trading)
**Method**: `_place_cancel()`
**Status**: ⚠️ Partially Implemented (paper trading only)
**Location**: `cofinex_exchange.py:1122-1188`
**Current**: Returns `NotImplementedError` for live trading
**Required API Endpoint**: `DELETE /spot/v1/order/{orderId}` (or similar)
**Parameters Needed**:
- Exchange order ID
- Trading pair (symbol)

**Expected Response Format**:
```json
{
  "code": "200",
  "msg": "success",
  "data": {
    "orderId": "...",
    "status": "CANCELED",
    ...
  }
}
```

---

### 1.3. Request Order Status
**Method**: `_request_order_status()`
**Status**: ❌ Not Implemented
**Location**: `cofinex_exchange.py:312-316`
**Current**: Raises `NotImplementedError`
**Required API Endpoint**: `GET /spot/v1/order/{orderId}` or `GET /spot/v1/order/status`
**Parameters Needed**:
- Exchange order ID (or client order ID)
- Trading pair (symbol)

**Expected Response Format**:
```json
{
  "code": "200",
  "msg": "success",
  "data": {
    "orderId": "...",
    "symbol": "...",
    "status": "NEW|PARTIALLY_FILLED|FILLED|CANCELED|REJECTED",
    "side": "BUY|SELL",
    "type": "LIMIT|MARKET",
    "price": "...",
    "quantity": "...",
    "filledQuantity": "...",
    "timestamp": "...",
    ...
  }
}
```

**Returns**: `OrderUpdate` object with:
- `client_order_id`
- `exchange_order_id`
- `trading_pair`
- `update_timestamp`
- `new_state` (OrderState enum)

---

### 1.4. Get All Trade Updates for Order
**Method**: `_all_trade_updates_for_order()`
**Status**: ❌ Not Implemented
**Location**: `cofinex_exchange.py:318-322`
**Current**: Returns empty list `[]`
**Required API Endpoint**: `GET /spot/v1/order/{orderId}/trades` or `GET /spot/v1/trades`
**Parameters Needed**:
- Exchange order ID
- Trading pair (symbol)

**Expected Response Format**:
```json
{
  "code": "200",
  "msg": "success",
  "data": [
    {
      "tradeId": "...",
      "orderId": "...",
      "symbol": "...",
      "price": "...",
      "quantity": "...",
      "fee": "...",
      "feeCurrency": "...",
      "timestamp": "...",
      "side": "BUY|SELL",
      ...
    },
    ...
  ]
}
```

**Returns**: List of `TradeUpdate` objects with:
- `trade_id`
- `client_order_id`
- `exchange_order_id`
- `trading_pair`
- `fill_timestamp`
- `fill_price`
- `fill_base_amount`
- `fill_quote_amount`
- `fee`

---

### 1.5. Get Open Orders
**Method**: `get_open_orders()`
**Status**: ❌ Not Implemented
**Location**: `cofinex_exchange.py:1229-1263`
**Current**: Returns locally tracked orders only
**Required API Endpoint**: `GET /spot/v1/openOrders` or `GET /spot/v1/orders`
**Parameters Needed**:
- Trading pair (symbol) - optional filter

**Expected Response Format**:
```json
{
  "code": "200",
  "msg": "success",
  "data": [
    {
      "orderId": "...",
      "symbol": "...",
      "status": "NEW|PARTIALLY_FILLED",
      "side": "BUY|SELL",
      "type": "LIMIT|MARKET",
      "price": "...",
      "quantity": "...",
      "filledQuantity": "...",
      "timestamp": "...",
      ...
    },
    ...
  ]
}
```

**Returns**: List of `LimitOrder` objects

---

## 2. Account Management APIs

### 2.1. Update Balances
**Method**: `_update_balances()`
**Status**: ❌ Not Implemented
**Location**: `cofinex_exchange.py:324-327`
**Current**: Empty implementation (`pass`)
**Required API Endpoint**: `GET /spot/v1/account/balance` or `GET /spot/v1/wallet/balance`
**Parameters Needed**: None (uses authenticated request)

**Expected Response Format**:
```json
{
  "code": "200",
  "msg": "success",
  "data": {
    "balances": [
      {
        "currency": "BTC",
        "available": "1.5",
        "locked": "0.5",
        "total": "2.0",
        ...
      },
      {
        "currency": "USDT",
        "available": "10000.0",
        "locked": "500.0",
        "total": "10500.0",
        ...
      },
      ...
    ]
  }
}
```

**Action**: Update `self._account_balances` dictionary with currency balances

---

### 2.2. Get Balance (Single Currency)
**Method**: `get_balance()`
**Status**: ❌ Not Implemented
**Location**: `cofinex_exchange.py:892-922`
**Current**: Returns cached balance or `Decimal("0")`
**Required**: Should call `_update_balances()` or use cached data
**Returns**: `Decimal` balance for the specified currency

---

### 2.3. Get All Balances
**Method**: `get_all_balances()`
**Status**: ❌ Not Implemented
**Location**: `cofinex_exchange.py:924-932`
**Current**: Returns cached balances copy
**Required**: Should call `_update_balances()` or use cached data
**Returns**: `Dict[str, Decimal]` of all currency balances

---

## 3. Trading Fees APIs

### 3.1. Update Trading Fees
**Method**: `_update_trading_fees()`
**Status**: ❌ Not Implemented
**Location**: `cofinex_exchange.py:329-332`
**Current**: Empty implementation (`pass`)
**Required API Endpoint**: `GET /spot/v1/fee` or `GET /spot/v1/account/fee`
**Parameters Needed**: None (uses authenticated request)

**Expected Response Format**:
```json
{
  "code": "200",
  "msg": "success",
  "data": {
    "makerFeeRate": "0.001",
    "takerFeeRate": "0.001",
    "tradingPair": "BTC-USDT",
    ...
  }
}
```

**Action**: Update fee rates for maker/taker orders (used by `_get_fee()`)

---

### 3.2. Get Fee
**Method**: `_get_fee()`
**Status**: ⚠️ Partially Implemented
**Location**: `cofinex_exchange.py:282-293`
**Current**: Uses hardcoded fee rate (0.1%)
**Required**: Should use fee rates from `_update_trading_fees()`
**Returns**: `TradeFeeBase` object with calculated fee

---

## 4. Error Handling APIs

### 4.1. Check Time Synchronizer Exception
**Method**: `_is_request_exception_related_to_time_synchronizer()`
**Status**: ❌ Not Implemented
**Location**: `cofinex_exchange.py:267-270`
**Current**: Returns `False` (stub)
**Required**: Check if exception is due to timestamp/synchronization issues
**Returns**: `bool` - True if exception is time-related

**Cofinex Error Codes to Check**:
- Timestamp too old
- Timestamp too new
- Invalid timestamp format
- Clock skew errors

---

### 4.2. Check Order Not Found (Status Update)
**Method**: `_is_order_not_found_during_status_update_error()`
**Status**: ❌ Not Implemented
**Location**: `cofinex_exchange.py:272-275`
**Current**: Returns `False` (stub)
**Required**: Check if exception indicates order not found during status update
**Returns**: `bool` - True if order not found

**Cofinex Error Codes to Check**:
- Order not found (404)
- Invalid order ID
- Order does not exist

---

### 4.3. Check Order Not Found (Cancellation)
**Method**: `_is_order_not_found_during_cancelation_error()`
**Status**: ❌ Not Implemented
**Location**: `cofinex_exchange.py:277-280`
**Current**: Returns `False` (stub)
**Required**: Check if exception indicates order not found during cancellation
**Returns**: `bool` - True if order not found (already canceled)

**Cofinex Error Codes to Check**:
- Order not found (404)
- Order already canceled
- Invalid order ID

---

## 5. User Stream Event Processing

### 5.1. User Stream Event Listener
**Method**: `_user_stream_event_listener()`
**Status**: ⚠️ Partially Implemented (stub)
**Location**: `cofinex_exchange.py:334-345`
**Current**: Empty loop (just passes)
**Required**: Process WebSocket user stream events
**Note**: User mentioned WebSocket user stream is not built yet, so this will use REST polling instead

**Events to Handle**:
- Order updates (NEW, PARTIALLY_FILLED, FILLED, CANCELED, REJECTED)
- Trade fills
- Balance updates
- Account updates

**Implementation Strategy**: Since WebSocket user stream is not available, use REST polling:
- Poll order status periodically
- Poll account balances periodically
- Poll trade history for active orders

---

## 6. Utility Methods

### 6.1. Parse Order Data
**Method**: `_parse_order_data()`
**Status**: ❌ Not Implemented
**Location**: `cofinex_exchange.py:1723-1754`
**Current**: Returns stub `LimitOrder` with hardcoded values
**Required**: Parse Cofinex API order response into `LimitOrder` object
**Input**: `Dict[str, Any]` - Raw order data from API
**Returns**: `LimitOrder` object

**Fields to Map**:
- `client_order_id` / `orderId`
- `trading_pair` / `symbol`
- `is_buy` / `side` (BUY/SELL)
- `base_currency` / `baseCoin`
- `quote_currency` / `quoteCoin`
- `price` / `price`
- `quantity` / `quantity` or `origQty`
- `filled_quantity` / `filledQuantity` or `executedQty`
- `status` / `status`
- `order_type` / `type` (LIMIT/MARKET)
- `time_in_force` / `timeInForce`

---

## Summary

### Priority 1 (Critical for Live Trading):
1. ✅ `_place_order()` - Place orders (live trading)
2. ✅ `_place_cancel()` - Cancel orders (live trading)
3. ✅ `_request_order_status()` - Check order status
4. ✅ `_update_balances()` - Get account balances
5. ✅ `_all_trade_updates_for_order()` - Get trade fills

### Priority 2 (Important for Full Functionality):
6. ✅ `_update_trading_fees()` - Get fee rates
7. ✅ `_get_fee()` - Calculate fees (use real rates)
8. ✅ `_is_order_not_found_during_status_update_error()` - Error handling
9. ✅ `_is_order_not_found_during_cancelation_error()` - Error handling
10. ✅ `_is_request_exception_related_to_time_synchronizer()` - Error handling

### Priority 3 (Nice to Have):
11. ✅ `get_open_orders()` - List open orders
12. ✅ `_parse_order_data()` - Parse order responses
13. ✅ `_user_stream_event_listener()` - Process user events (REST polling fallback)

---

## Next Steps

Please provide the Cofinex API documentation or endpoints for:
1. **Order Placement** - POST endpoint with request/response format
2. **Order Cancellation** - DELETE endpoint with request/response format
3. **Order Status** - GET endpoint with response format
4. **Trade History** - GET endpoint for order fills
5. **Account Balances** - GET endpoint with response format
6. **Trading Fees** - GET endpoint with fee rates
7. **Error Codes** - List of error codes and their meanings

Once you provide the API details, I'll implement each method accordingly.
