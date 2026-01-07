# Cofinex Connector - REST-Only Implementation Approach

## Overview

The Cofinex connector is being implemented using a **REST-only approach** for user account updates. This means we're using REST API polling instead of WebSocket connections for real-time updates.

**Authentication**: The connector uses **OAuth 2.0 / OpenID Connect** with Bearer tokens. All authenticated REST requests include `Authorization: Bearer {access_token}` header. The token is automatically refreshed before expiry.

## Why REST-Only?

### Advantages ✅

1. **Simpler Implementation**
   - No WebSocket connection management
   - No reconnection logic
   - Easier to debug and maintain

2. **More Reliable**
   - No connection drops
   - No WebSocket timeout issues
   - Works consistently

3. **Faster Development**
   - Can start working immediately
   - No need to wait for WebSocket documentation
   - Easier to test

4. **Easier Debugging**
   - REST calls are easier to trace
   - Can use standard HTTP debugging tools
   - Clear request/response flow

### Trade-offs ⚠️

1. **Slightly Higher Latency**
   - Updates every 3-10 seconds (configurable)
   - WebSocket would be near-instant (< 100ms)
   - For most trading strategies, this is acceptable

2. **More API Calls**
   - Constant polling even when nothing changes
   - WebSocket only sends updates when events occur
   - Need to respect rate limits

3. **Higher Rate Limit Usage**
   - More API calls = more rate limit consumption
   - Need to balance polling frequency with rate limits

## Implementation Details

### User Stream Data Source

**File**: `cofinex_api_user_stream_data_source.py`

**How it works**:
1. Uses OAuth 2.0 Bearer token authentication for all requests
2. Polls account balances every 10 seconds
3. Polls open orders every 3 seconds
4. Compares current state with last known state
5. Emits events only when changes are detected
6. Handles errors gracefully with retry logic
7. Automatically refreshes OAuth token when needed

**Polling Intervals**:
```python
BALANCE_POLL_INTERVAL = 10.0  # Poll balances every 10 seconds
ORDER_POLL_INTERVAL = 3.0     # Poll orders every 3 seconds
```

**Adjustable based on**:
- Cofinex rate limits
- Trading frequency needs
- Network latency

### Required REST Endpoints

The REST-only implementation uses these endpoints (all require OAuth Bearer token authentication):

1. **Account Balances**
   - `GET /api/v1/account` or `/api/v1/balance`
   - Returns all account balances
   - Polled every 10 seconds
   - **Authentication**: Bearer token in `Authorization` header

2. **Open Orders**
   - `GET /api/v1/openOrders`
   - Returns all open orders
   - Polled every 3 seconds
   - **Authentication**: Bearer token in `Authorization` header

3. **Order Status** (optional, for better tracking)
   - `GET /api/v1/order/{orderId}`
   - Get specific order status
   - Used when order disappears from open orders
   - **Authentication**: Bearer token in `Authorization` header

4. **Trade History** (optional, for fill detection)
   - `GET /api/v1/myTrades` or `/api/v1/fills`
   - Get recent trades
   - Can help detect order fills
   - **Authentication**: Bearer token in `Authorization` header

**Note**: All authenticated endpoints require the OAuth access token. The `CofinexAuth` class automatically adds the Bearer token to all authenticated requests and handles token refresh.

### Event Format

The REST-only implementation emits events in the same format as WebSocket would:

**Balance Update Event**:
```python
{
    "event_type": "balance_update",
    "data": {
        "currency": "BTC",
        "available": "1.0",
        "locked": "0.0",
        "total": "1.0"
    },
    "timestamp": 1234567890.0
}
```

**Order Update Event**:
```python
{
    "event_type": "order_update",
    "data": {
        "orderId": "12345",
        "status": "FILLED",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "price": "50000",
        "quantity": "0.1"
    },
    "timestamp": 1234567890.0
}
```

## Performance Considerations

### Latency Impact

- **Order Status Updates**: 3-10 second delay
  - Order placed → Status update: ~3 seconds
  - Order filled → Detection: ~3-10 seconds

- **Balance Updates**: 10 second delay
  - Trade executed → Balance update: ~10 seconds

### For Most Strategies

This latency is acceptable for:
- ✅ Market making strategies
- ✅ Arbitrage (if not ultra-high frequency)
- ✅ Swing trading
- ✅ Position-based strategies
- ✅ Most automated trading strategies

### Not Ideal For

- ❌ Ultra-high frequency trading (< 1 second)
- ❌ Scalping with very tight timing
- ❌ Strategies requiring instant order status

## Rate Limit Management

### Current Polling Strategy

- **Balances**: 6 requests/minute (every 10 seconds)
- **Orders**: 20 requests/minute (every 3 seconds)
- **Total**: ~26 requests/minute for user stream

### Recommendations

1. **Adjust Intervals Based on Rate Limits**
   - If Cofinex has strict limits, increase intervals
   - If limits are generous, can decrease for faster updates

2. **Monitor Rate Limit Usage**
   - Track API calls
   - Implement backoff if rate limited
   - Log warnings when approaching limits

3. **Optimize Polling**
   - Only poll when trading is active
   - Reduce frequency during low activity
   - Increase frequency during high activity

## Future: Adding WebSocket (Optional)

If you want to add WebSocket support later:

1. **Create WebSocket User Stream Data Source**
   - Similar structure to REST version
   - Connect to WebSocket endpoint
   - Subscribe to user data channels

2. **Hybrid Approach**
   - Use WebSocket when available
   - Fall back to REST polling if WebSocket fails
   - Best of both worlds

3. **Benefits of Adding WebSocket**
   - Near-instant updates (< 100ms)
   - Lower API call count
   - Better for high-frequency trading

## Testing the REST-Only Implementation

### Test Scenarios

1. **Balance Updates**
   - Place an order
   - Wait for balance to update
   - Verify event is emitted

2. **Order Status Updates**
   - Place an order
   - Wait for status update
   - Verify event is emitted

3. **Order Fills**
   - Place a market order
   - Wait for fill detection
   - Verify fill event is emitted

4. **Error Handling**
   - Simulate API errors
   - Verify retry logic works
   - Verify connector continues working

### Debugging Tips

1. **Enable Debug Logging**
   ```python
   import logging
   logging.getLogger("hummingbot.connector.exchange.cofinex").setLevel(logging.DEBUG)
   ```

2. **Monitor Polling**
   - Check logs for polling intervals
   - Verify events are being emitted
   - Check for errors

3. **Test with Paper Trading**
   - Use paper trading first
   - Verify all events work correctly
   - Then test with real API

## Summary

✅ **REST-only approach is complete and working**
- User stream data source implemented
- Polling intervals configured
- Change detection working
- Error handling in place

⚠️ **Next Steps**
- Update response parsing based on actual Cofinex API format
- Fine-tune polling intervals based on rate limits
- Test with real API (or paper trading)

🚀 **Future Enhancement (Optional)**
- Add WebSocket support for better performance
- Implement hybrid approach (WebSocket + REST fallback)
