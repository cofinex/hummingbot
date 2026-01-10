# Cofinex Connector Testing Guide

## Quick Test Steps

### 1. Start Hummingbot
```bash
cd /Users/santoshpadhi/hummingbot
python bin/hummingbot.py
```

### 2. Connect to Paper Trading
Once Hummingbot starts, type:
```
connect cofinex_paper_trade
```

**Note**: No credentials needed for paper trading!

### 3. Test Trading Pair Discovery
After connecting, the connector should:
- ✅ Fetch trading pairs from Cofinex API
- ✅ Build symbol mapping (e.g., "MASUSDT" → "MAS-USDT")
- ✅ Load trading rules for each pair

### 4. Test Order Book Data
The connector should automatically:
- ✅ Fetch order book snapshots for configured trading pairs
- ✅ Update order books with real market data

### 5. Check Logs
Watch for these log messages:
- `"Initialized trading pair symbol map with X pairs"`
- `"Updated trading rules for X trading pairs"`
- `"Started order book tracking for X trading pairs"`
- `"Cofinex connector started successfully"`

## What to Test

### ✅ Working Features (Implemented)
1. **Trading Pair Mapping**: Exchange symbols ↔ Hummingbot pairs
2. **Trading Rules**: Min order size, price precision, etc.
3. **Order Book Data**: Real-time market data fetching

### ⚠️ Not Yet Implemented (For Future)
- Order placement
- Order cancellation
- Balance fetching
- User stream updates

## Troubleshooting

### If connector doesn't appear in list:
- Check that `cofinex` is in `conf/conf_client.yml` under `paper_trade_exchanges`
- Restart Hummingbot

### If connection fails:
- Check internet connection
- Verify Cofinex API is accessible: `https://marketdata.cofinex.io/spot/v1/tradepair`
- Check logs for specific error messages

### If order books don't load:
- Verify trading pairs are valid (e.g., "BTC-USDT", "ETH-USDT")
- Check that Cofinex has these pairs available
- Look for API rate limit errors in logs

## Expected Behavior

When you run `connect cofinex_paper_trade`:
1. Connector initializes
2. Fetches ~725 trading pairs from Cofinex
3. Builds symbol mapping
4. Loads trading rules
5. Starts fetching order book data
6. Connector becomes "ready" for paper trading

## Next Steps After Testing

If everything works:
- ✅ Trading pair mapping is correct
- ✅ Trading rules are loaded
- ✅ Order books are fetching data

Then we can proceed to implement:
- Order placement methods
- Order cancellation
- Balance management
- User stream updates
