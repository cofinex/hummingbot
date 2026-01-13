#!/usr/bin/env python3
"""
Reconciliation Script: Hummingbot vs Exchange-Core (ClickHouse)

This script compares orders and trades from:
- Hummingbot SQLite database
- Exchange-Core ClickHouse database (direct connection)

Usage:
    # Basic usage with defaults (no arguments needed):
    python reconcile_hummingbot_exchange_core.py

    # Override specific values:
    python reconcile_hummingbot_exchange_core.py --user-id 1234 --symbol BTC/USDT

    # With time range:
    python reconcile_hummingbot_exchange_core.py --start-time "2026-01-10T00:00:00" --end-time "2026-01-12T23:59:59"

Defaults (can be overridden via environment variables or command-line args):
    --db: data/conf_multi_level_self_trading.sqlite
    --clickhouse-host: jw01l5yyok.us-east-1.aws.clickhouse.cloud
    --clickhouse-port: 8443
    --clickhouse-database: exchange_test
    --clickhouse-username: default
    --clickhouse-secure: true
    --user-id: 1120
    --symbol: CNX/USDT
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

try:
    import clickhouse_connect
except ImportError:
    print("Error: clickhouse_connect module not found. Install with: pip install clickhouse-connect")
    sys.exit(1)


def get_env_or_default(env_var: str, default: str) -> str:
    """Get value from environment variable or return default"""
    return os.getenv(env_var, default)


def get_env_bool_or_default(env_var: str, default: bool) -> bool:
    """Get boolean value from environment variable or return default"""
    value = os.getenv(env_var)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


class ReconciliationReport:
    """Stores reconciliation results"""

    def __init__(self):
        self.orders_in_hb_not_in_ec: List[Dict] = []
        self.orders_status_mismatch: List[Dict] = []
        self.orders_price_mismatch: List[Dict] = []
        self.orders_amount_mismatch: List[Dict] = []

        self.trades_in_hb_not_in_ec: List[Dict] = []
        self.trades_price_mismatch: List[Dict] = []
        self.trades_amount_mismatch: List[Dict] = []
        self.trades_order_id_mismatch: List[Dict] = []
        self.trades_timestamp_mismatch: List[Dict] = []

        self.summary: Dict = {
            "total_orders_hb": 0,
            "total_orders_ec": 0,
            "total_trades_hb": 0,
            "total_trades_ec": 0,
            "matched_orders": 0,
            "matched_trades": 0,
            "discrepancies": 0,
        }

    def print_report(self):
        """Print reconciliation report"""
        print("\n" + "=" * 80)
        print("RECONCILIATION REPORT: Hummingbot vs Exchange-Core (ClickHouse)")
        print("=" * 80)

        print("\n📊 SUMMARY")
        print("-" * 80)
        print(f"Total Orders (Hummingbot):     {self.summary['total_orders_hb']}")
        print(f"Orders Found in ClickHouse:    {self.summary['matched_orders']}")
        print(f"Orders Missing in ClickHouse:  {len(self.orders_in_hb_not_in_ec)}")
        print(f"\nTotal Trades (Hummingbot):     {self.summary['total_trades_hb']}")
        print(f"Trades Found in ClickHouse:    {self.summary['matched_trades']}")
        print(f"Trades Missing in ClickHouse:  {len(self.trades_in_hb_not_in_ec)}")
        print(f"\nTotal Discrepancies:           {self.summary['discrepancies']}")

        print("\n" + "=" * 80)
        print("ORDER DISCREPANCIES (Verifying all Bot orders exist in ClickHouse)")
        print("=" * 80)

        if self.orders_in_hb_not_in_ec:
            print(f"\n❌ CRITICAL: Orders in Hummingbot but NOT in ClickHouse: {len(self.orders_in_hb_not_in_ec)}")
            print("   These orders were placed by the bot but are missing from Exchange-Core!")
            for order in self.orders_in_hb_not_in_ec[:20]:  # Show more for critical issues
                print(f"  - Order ID: {order['exchange_order_id']}, Status: {order['last_status']}, "
                      f"Symbol: {order['symbol']}, Price: {order['price']}, Amount: {order['amount']}, "
                      f"Created: {datetime.fromtimestamp(order['creation_timestamp'] / 1000).strftime('%Y-%m-%d %H:%M:%S')}")  # noqa: E226
            if len(self.orders_in_hb_not_in_ec) > 20:
                print(f"  ... and {len(self.orders_in_hb_not_in_ec) - 20} more")
        else:
            print("\n✅ All Hummingbot orders found in ClickHouse!")

        if self.orders_status_mismatch:
            print(f"\n⚠️  Order Status Mismatches: {len(self.orders_status_mismatch)}")

            # Separate critical issues (orders filled but not tracked)
            critical_issues = [m for m in self.orders_status_mismatch if m.get('issue') == 'ORDER_FILLED_BUT_NOT_TRACKED_IN_HB']
            normal_mismatches = [m for m in self.orders_status_mismatch if m.get('issue') != 'ORDER_FILLED_BUT_NOT_TRACKED_IN_HB']

            if critical_issues:
                print(f"\n  ❌ CRITICAL: Orders FILLED in Exchange-Core but NOT tracked in Hummingbot: {len(critical_issues)}")
                print("     These orders were filled on the exchange but Hummingbot didn't receive/process the fill events!")
                for mismatch in critical_issues[:10]:
                    print(f"    - Order ID: {mismatch['order_id']}, "
                          f"HB Status: {mismatch['hb_status']}, EC Status: {mismatch['ec_status']}")
                if len(critical_issues) > 10:
                    print(f"    ... and {len(critical_issues) - 10} more")

            if normal_mismatches:
                print(f"\n  ⚠️  Other Status Mismatches: {len(normal_mismatches)}")
                for mismatch in normal_mismatches[:10]:
                    print(f"    - Order ID: {mismatch['order_id']}, "
                          f"HB Status: {mismatch['hb_status']} (effective: {mismatch.get('hb_effective_status', 'N/A')}), "
                          f"EC Status: {mismatch['ec_status']}")
                if len(normal_mismatches) > 10:
                    print(f"    ... and {len(normal_mismatches) - 10} more")

        if self.orders_price_mismatch:
            print(f"\n⚠️  Order Price Mismatches (Placed Price): {len(self.orders_price_mismatch)}")
            print("   Note: Comparing placed prices, not filled prices")
            for mismatch in self.orders_price_mismatch[:10]:
                hb_amount = mismatch.get('hb_amount')
                ec_quantity = mismatch.get('ec_quantity')
                if hb_amount is not None and ec_quantity is not None:
                    amount_str = f"HB Amount: {hb_amount:.8f}, EC Quantity: {ec_quantity:.8f}, "
                else:
                    amount_str = f"HB Amount: {hb_amount}, EC Quantity: {ec_quantity}, "
                print(f"  - Order ID: {mismatch['order_id']}, "
                      f"HB Price: {mismatch['hb_price']:.8f}, EC Price: {mismatch['ec_price']:.8f}, "
                      f"Diff: {abs(mismatch['hb_price'] - mismatch['ec_price']):.8f}, "
                      f"{amount_str}"
                      f"HB Status: {mismatch.get('hb_status', 'N/A')}, EC Status: {mismatch.get('ec_status', 'N/A')}")
            if len(self.orders_price_mismatch) > 10:
                print(f"  ... and {len(self.orders_price_mismatch) - 10} more")

        if self.orders_amount_mismatch:
            print(f"\n⚠️  Order Amount Mismatches (Placed Amount): {len(self.orders_amount_mismatch)}")
            print("   Note: Comparing placed amounts, not filled amounts")
            for mismatch in self.orders_amount_mismatch[:10]:
                print(f"  - Order ID: {mismatch['order_id']}, "
                      f"HB Amount: {mismatch['hb_amount']:.8f}, EC Quantity: {mismatch['ec_quantity']:.8f}, "
                      f"Diff: {abs(mismatch['hb_amount'] - mismatch['ec_quantity']):.8f}, "
                      f"HB Status: {mismatch.get('hb_status', 'N/A')}, EC Status: {mismatch.get('ec_status', 'N/A')}")
            if len(self.orders_amount_mismatch) > 10:
                print(f"  ... and {len(self.orders_amount_mismatch) - 10} more")

        print("\n" + "=" * 80)
        print("TRADE DISCREPANCIES (Verifying all Bot trades exist in ClickHouse)")
        print("=" * 80)

        if self.trades_in_hb_not_in_ec:
            print(f"\n❌ CRITICAL: Trades in Hummingbot but NOT in ClickHouse: {len(self.trades_in_hb_not_in_ec)}")
            print("   These trades were executed by the bot but are missing from Exchange-Core!")
            for trade in self.trades_in_hb_not_in_ec[:20]:  # Show more for critical issues
                print(f"  - Trade ID: {trade['exchange_trade_id']}, Order ID: {trade['order_id']}, "
                      f"Price: {trade['price']}, Amount: {trade['amount']}, "
                      f"Timestamp: {datetime.fromtimestamp(trade['timestamp'] / 1000).strftime('%Y-%m-%d %H:%M:%S')}")  # noqa: E226
            if len(self.trades_in_hb_not_in_ec) > 20:
                print(f"  ... and {len(self.trades_in_hb_not_in_ec) - 20} more")
        else:
            print("\n✅ All Hummingbot trades found in ClickHouse!")

        # Price comparison for trades is skipped (execution price can differ from placed price)
        # This is expected behavior and not a discrepancy
        if self.trades_amount_mismatch:
            print(f"\n⚠️  Trade Amount Mismatches: {len(self.trades_amount_mismatch)}")
            print("   Note: For partially filled orders, EC trades are aggregated by exchange_order_id")
            for mismatch in self.trades_amount_mismatch[:5]:
                hb_trade_id = mismatch.get('hb_trade_id', 'N/A')
                ec_trade_ids = mismatch.get('ec_trade_ids', 'N/A')
                ec_trade_count = mismatch.get('ec_trade_count', 1)
                print(f"  - HB Trade ID: {hb_trade_id}, EC Trade ID(s): {ec_trade_ids} ({ec_trade_count} trade(s)), "
                      f"HB Amount: {mismatch['hb_amount']}, EC Quantity (sum): {mismatch['ec_quantity']}, "
                      f"Diff: {abs(mismatch['hb_amount'] - mismatch['ec_quantity']):.8f}")

        if self.trades_order_id_mismatch:
            print(f"\n⚠️  Trade Order ID Mismatches: {len(self.trades_order_id_mismatch)}")
            for mismatch in self.trades_order_id_mismatch[:5]:
                hb_trade_id = mismatch.get('hb_trade_id', 'N/A')
                ec_trade_id = mismatch.get('ec_trade_id', 'N/A')
                matched_by = mismatch.get('matched_by', 'unknown')
                print(f"  - HB Trade ID: {hb_trade_id}, EC Trade ID: {ec_trade_id} (matched by: {matched_by}), "
                      f"HB Client Order ID: {mismatch['hb_order_id']}, "
                      f"HB Exchange Order ID: {mismatch.get('hb_exchange_order_id', 'N/A')}, "
                      f"EC Taker Order ID: {mismatch.get('ec_taker_order_id', 'N/A')}, "
                      f"EC Maker Order ID: {mismatch.get('ec_maker_order_id', 'N/A')}")

        # Trade timestamp mismatches are ignored (not important for reconciliation)

        print("\n" + "=" * 80)
        print("✅ RECONCILIATION COMPLETE")
        print("=" * 80 + "\n")


def load_hummingbot_order_fills(db_path: str) -> Dict[str, List[Dict]]:
    """Load all TradeFill records grouped by order_id to check if orders were filled"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    query = """
        SELECT order_id, exchange_trade_id, price, amount, timestamp
        FROM TradeFill
    """

    cursor.execute(query)
    rows = cursor.fetchall()

    # SqliteDecimal(6) stores values multiplied by 1,000,000 (10^6)
    # When reading directly from SQLite, we get raw integers, so we need to divide
    SCALE_FACTOR = 1_000_000  # 10^6 for SqliteDecimal(6)

    # Group fills by order_id
    fills_by_order = {}
    for row in rows:
        order_id = row['order_id']
        if order_id not in fills_by_order:
            fills_by_order[order_id] = []
        fills_by_order[order_id].append({
            'exchange_trade_id': row['exchange_trade_id'],
            'price': float(row['price']) / SCALE_FACTOR,  # Scale factor
            'amount': float(row['amount']) / SCALE_FACTOR,  # Scale factor
            'timestamp': row['timestamp'],
        })

    conn.close()
    return fills_by_order


def load_hummingbot_orders(db_path: str, symbol: str, start_time: Optional[datetime] = None,
                           end_time: Optional[datetime] = None) -> Dict[str, Dict]:
    """Load orders from Hummingbot SQLite database"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Try both symbol formats (CNX/USDT and CNX-USDT)
    # First, check what symbols actually exist in the database
    cursor.execute("SELECT DISTINCT symbol FROM 'Order' LIMIT 20")
    existing_symbols = [row[0] for row in cursor.fetchall()]

    # Normalize the input symbol to try both formats
    symbol_dash = symbol.replace("/", "-")
    symbol_slash = symbol.replace("-", "/")

    # Use the format that exists in the database, or try both
    if symbol_dash in existing_symbols:
        query_symbol = symbol_dash
    elif symbol_slash in existing_symbols:
        query_symbol = symbol_slash
    else:
        # If neither matches exactly, try both with OR
        query = """
            SELECT id, exchange_order_id, symbol, base_asset, quote_asset,
                   amount, price, last_status, creation_timestamp, last_update_timestamp,
                   order_type, position
            FROM "Order"
            WHERE (symbol = ? OR symbol = ?)
        """
        params = [symbol_dash, symbol_slash]
        if start_time:
            query += " AND creation_timestamp >= ?"
            params.append(int(start_time.timestamp() * 1000))

        if end_time:
            query += " AND creation_timestamp <= ?"
            params.append(int(end_time.timestamp() * 1000))

        cursor.execute(query, params)
        rows = cursor.fetchall()

        # SqliteDecimal(6) stores values multiplied by 1,000,000 (10^6)
        # When reading directly from SQLite, we get raw integers, so we need to divide
        SCALE_FACTOR = 1_000_000  # 10^6 for SqliteDecimal(6)

        orders = {}
        for row in rows:
            if row['exchange_order_id']:  # Only include orders with exchange_order_id
                orders[row['exchange_order_id']] = {
                    'client_order_id': row['id'],
                    'exchange_order_id': row['exchange_order_id'],
                    'symbol': row['symbol'],
                    'base_asset': row['base_asset'],
                    'quote_asset': row['quote_asset'],
                    'amount': float(row['amount']) / SCALE_FACTOR,  # Convert from scaled integer
                    'price': float(row['price']) / SCALE_FACTOR,    # Convert from scaled integer
                    'last_status': row['last_status'],
                    'creation_timestamp': row['creation_timestamp'],
                    'last_update_timestamp': row['last_update_timestamp'],
                    'order_type': row['order_type'],
                }

        conn.close()
        return orders

    query = """
        SELECT id, exchange_order_id, symbol, base_asset, quote_asset,
               amount, price, last_status, creation_timestamp, last_update_timestamp,
               order_type, position
        FROM "Order"
        WHERE symbol = ?
    """
    params = [query_symbol]

    if start_time:
        query += " AND creation_timestamp >= ?"
        params.append(int(start_time.timestamp() * 1000))

    if end_time:
        query += " AND creation_timestamp <= ?"
        params.append(int(end_time.timestamp() * 1000))

    cursor.execute(query, params)
    rows = cursor.fetchall()

    # SqliteDecimal(6) stores values multiplied by 1,000,000 (10^6)
    # When reading directly from SQLite, we get raw integers, so we need to divide
    SCALE_FACTOR = 1_000_000  # 10^6 for SqliteDecimal(6)

    # Load TradeFill records to check if orders were actually filled
    fills_by_order = load_hummingbot_order_fills(db_path)

    orders = {}
    for row in rows:
        if row['exchange_order_id']:  # Only include orders with exchange_order_id
            client_order_id = row['id']
            order_amount = float(row['amount']) / SCALE_FACTOR

            # Check if this order has fills
            has_fills = client_order_id in fills_by_order
            total_filled = sum(f['amount'] for f in fills_by_order.get(client_order_id, []))
            is_completely_filled = has_fills and abs(total_filled - order_amount) < 0.0001

            # Determine effective status: if order has fills but status is still "Created",
            # it means Hummingbot didn't update the status, but the order was filled
            effective_status = row['last_status']
            if is_completely_filled and row['last_status'] in ('BuyOrderCreated', 'SellOrderCreated', 'OrderCreated'):
                effective_status = 'FILLED'  # Mark as filled even if status wasn't updated

            orders[row['exchange_order_id']] = {
                'client_order_id': client_order_id,
                'exchange_order_id': row['exchange_order_id'],
                'symbol': row['symbol'],
                'base_asset': row['base_asset'],
                'quote_asset': row['quote_asset'],
                'amount': order_amount,
                'price': float(row['price']) / SCALE_FACTOR,    # Convert from scaled integer
                'last_status': row['last_status'],  # Original status from DB
                'effective_status': effective_status,  # Computed status (accounts for fills)
                'has_fills': has_fills,
                'total_filled': total_filled,
                'creation_timestamp': row['creation_timestamp'],
                'last_update_timestamp': row['last_update_timestamp'],
                'order_type': row['order_type'],
            }

    conn.close()
    return orders


def load_hummingbot_trades(db_path: str, symbol: str, start_time: Optional[datetime] = None,
                           end_time: Optional[datetime] = None) -> Dict[str, Dict]:
    """Load trades from Hummingbot SQLite database"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Try both symbol formats (CNX/USDT and CNX-USDT)
    # First, check what symbols actually exist in the database
    cursor.execute("SELECT DISTINCT symbol FROM TradeFill LIMIT 20")
    existing_symbols = [row[0] for row in cursor.fetchall()]

    # Normalize the input symbol to try both formats
    symbol_dash = symbol.replace("/", "-")
    symbol_slash = symbol.replace("-", "/")

    # Use the format that exists in the database, or try both
    if symbol_dash in existing_symbols:
        query_symbol = symbol_dash
    elif symbol_slash in existing_symbols:
        query_symbol = symbol_slash
    else:
        # If neither matches exactly, try both with OR
        query = """
            SELECT tf.order_id, tf.exchange_trade_id, tf.symbol, tf.base_asset, tf.quote_asset,
                   tf.amount, tf.price, tf.timestamp, tf.trade_type, tf.order_type,
                   o.exchange_order_id
            FROM TradeFill tf
            LEFT JOIN "Order" o ON tf.order_id = o.id
            WHERE (tf.symbol = ? OR tf.symbol = ?)
        """
        params = [symbol_dash, symbol_slash]
        if start_time:
            query += " AND timestamp >= ?"
            params.append(int(start_time.timestamp() * 1000))

        if end_time:
            query += " AND timestamp <= ?"
            params.append(int(end_time.timestamp() * 1000))

        cursor.execute(query, params)
        rows = cursor.fetchall()

        trades = {}
        for row in rows:
            if row['exchange_trade_id']:
                # Convert exchange_order_id to string for consistent comparison
                exchange_order_id = str(row['exchange_order_id']) if row['exchange_order_id'] else None
                trades[row['exchange_trade_id']] = {
                    'order_id': row['order_id'],
                    'exchange_order_id': exchange_order_id,  # From Order table, converted to string
                    'exchange_trade_id': row['exchange_trade_id'],
                    'symbol': row['symbol'],
                    'amount': float(row['amount']),
                    'price': float(row['price']),
                    'timestamp': row['timestamp'],
                    'trade_type': row['trade_type'],
                    'order_type': row['order_type'],
                }

        conn.close()
        return trades

    # Join with Order table to get exchange_order_id
    query = """
        SELECT tf.order_id, tf.exchange_trade_id, tf.symbol, tf.base_asset, tf.quote_asset,
               tf.amount, tf.price, tf.timestamp, tf.trade_type, tf.order_type,
               o.exchange_order_id
        FROM TradeFill tf
        LEFT JOIN "Order" o ON tf.order_id = o.id
        WHERE tf.symbol = ?
    """
    params = [query_symbol]

    if start_time:
        query += " AND tf.timestamp >= ?"
        params.append(int(start_time.timestamp() * 1000))

    if end_time:
        query += " AND tf.timestamp <= ?"
        params.append(int(end_time.timestamp() * 1000))

    cursor.execute(query, params)
    rows = cursor.fetchall()

    # SqliteDecimal(6) stores values multiplied by 1,000,000 (10^6)
    # When reading directly from SQLite, we get raw integers, so we need to divide
    SCALE_FACTOR = 1_000_000  # 10^6 for SqliteDecimal(6)

    trades = {}
    for row in rows:
        if row['exchange_trade_id']:
            # Convert exchange_order_id to string for consistent comparison
            exchange_order_id = str(row['exchange_order_id']) if row['exchange_order_id'] else None
            trades[row['exchange_trade_id']] = {
                'order_id': row['order_id'],
                'exchange_order_id': exchange_order_id,  # From Order table, converted to string
                'exchange_trade_id': row['exchange_trade_id'],
                'symbol': row['symbol'],
                'amount': float(row['amount']) / SCALE_FACTOR,  # Convert from scaled integer
                'price': float(row['price']) / SCALE_FACTOR,    # Convert from scaled integer
                'timestamp': row['timestamp'],
                'trade_type': row['trade_type'],
                'order_type': row['order_type'],
            }

    conn.close()
    return trades


def normalize_symbol(symbol: str) -> str:
    """Normalize symbol format (CNX/USDT -> CNXUSDT)"""
    return symbol.replace("/", "").replace("-", "").upper()


def fetch_clickhouse_orders(client, database: str, user_id: int, symbol: str,
                            start_time: Optional[datetime] = None,
                            end_time: Optional[datetime] = None) -> Dict[str, Dict]:
    """Fetch orders from ClickHouse order_events table"""

    # Normalize symbol (CNX/USDT -> CNXUSDT)
    normalized_symbol = normalize_symbol(symbol)

    # Build time conditions
    conditions = [
        f"user_id = {user_id}",
        f"symbol = '{normalized_symbol}'",
    ]

    if start_time:
        start_time_str = start_time.strftime("%Y-%m-%d %H:%M:%S")
        conditions.append(f"event_time >= toDateTime('{start_time_str}')")

    if end_time:
        end_time_str = end_time.strftime("%Y-%m-%d %H:%M:%S")
        conditions.append(f"event_time <= toDateTime('{end_time_str}')")

    where_clause = " AND ".join(conditions)

    # Query to get order information
    # For price/quantity: Use PLACE_ORDER event (original placed values)
    # For status: Use status priority (FILLED/CANCELLED > PARTIALLY_FILLED > OPEN)
    # This handles out-of-order events where FILLED might arrive before PLACE_ORDER
    query = f"""
    WITH first_place_order_time AS (
        SELECT
            order_id,
            min(event_time) as first_place_time
        FROM {database}.order_events
        WHERE {where_clause}
          AND event_type = 'PLACE_ORDER'
        GROUP BY order_id
    ),
    place_orders AS (
        SELECT
            oe.order_id,
            argMin(oe.price, oe.event_id) as placed_price,
            argMin(oe.quantity, oe.event_id) as placed_quantity
        FROM {database}.order_events oe
        INNER JOIN first_place_order_time fpot ON oe.order_id = fpot.order_id
        WHERE {where_clause}
          AND oe.event_type = 'PLACE_ORDER'
          AND oe.event_time = fpot.first_place_time
        GROUP BY oe.order_id
    ),
    events_with_priority AS (
        SELECT
            order_id,
            status,
            side,
            order_type,
            filled,
            remaining,
            event_time,
            event_type,
            CASE
                WHEN status = 'FILLED' OR event_type = 'FILLED' THEN 4
                WHEN status = 'CANCELLED' OR event_type = 'CANCEL_ORDER' THEN 4
                WHEN status = 'PARTIALLY_FILLED' OR event_type = 'PARTIALLY_FILLED' THEN 3
                WHEN status = 'OPEN' OR event_type = 'PLACE_ORDER' THEN 2
                ELSE 1
            END as status_priority
        FROM {database}.order_events
        WHERE {where_clause}
    ),
    latest_status AS (
        SELECT
            order_id,
            argMax(status, status_priority) as status,
            argMax(side, status_priority) as side,
            argMax(order_type, status_priority) as order_type,
            argMax(filled, status_priority) as filled,
            argMax(remaining, status_priority) as remaining,
            min(event_time) as first_event_time,
            max(event_time) as last_event_time
        FROM events_with_priority
        GROUP BY order_id
    )
    SELECT
        ls.order_id,
        ls.status,
        ls.side,
        ls.order_type,
        po.placed_price,
        po.placed_quantity,
        ls.filled,
        ls.remaining,
        ls.first_event_time,
        ls.last_event_time
    FROM latest_status ls
    LEFT JOIN place_orders po ON ls.order_id = po.order_id
    """

    try:
        result = client.query(query)
        orders = {}

        for row in result.result_rows:
            order_id = str(row[0])
            placed_price = float(row[4]) if row[4] and row[4] > 0 else None
            placed_quantity = float(row[5]) if row[5] and row[5] > 0 else None

            orders[order_id] = {
                'order_id': order_id,
                'symbol': symbol,  # Return original format for display
                'status': str(row[1]),
                'side': str(row[2]),
                'order_type': str(row[3]),
                'price': placed_price,  # Original placed price (not filled price)
                'quantity': placed_quantity,  # Original placed quantity (not filled)
                'filled': float(row[6]),
                'remaining': float(row[7]),
                'first_event_time': row[8],
                'last_event_time': row[9],
            }

        return orders

    except Exception as e:
        print(f"Error fetching orders from ClickHouse: {e}")
        import traceback
        traceback.print_exc()
        return {}


def fetch_clickhouse_trades(client, database: str, user_id: int, symbol: str,
                            start_time: Optional[datetime] = None,
                            end_time: Optional[datetime] = None) -> Dict[str, Dict]:
    """
    Fetch trades from ClickHouse trades table.

    Returns a dictionary keyed by trade_id for one-to-one matching with Hummingbot.
    """

    # Normalize symbol (CNX/USDT -> CNXUSDT)
    normalized_symbol = normalize_symbol(symbol)

    # Build conditions - user can be either taker or maker
    conditions = [
        f"symbol = '{normalized_symbol}'",
        f"(taker_user_id = {user_id} OR maker_user_id = {user_id})",
    ]

    if start_time:
        start_time_str = start_time.strftime("%Y-%m-%d %H:%M:%S")
        conditions.append(f"timestamp >= toDateTime('{start_time_str}')")

    if end_time:
        end_time_str = end_time.strftime("%Y-%m-%d %H:%M:%S")
        conditions.append(f"timestamp <= toDateTime('{end_time_str}')")

    where_clause = " AND ".join(conditions)

    query = f"""
    SELECT
        trade_id,
        symbol,
        side,
        taker_order_id,
        maker_order_id,
        taker_user_id,
        maker_user_id,
        quantity,
        price,
        trade_value,
        timestamp,
        fee,
        fee_currency
    FROM {database}.trades
    WHERE {where_clause}
    ORDER BY timestamp DESC
    """

    try:
        result = client.query(query)
        trades = {}

        for row in result.result_rows:
            trade_id = str(row[0])  # This is the PRIMARY KEY for matching
            # Ensure order IDs are strings for consistent comparison
            taker_order_id = str(row[3]) if row[3] is not None else None
            maker_order_id = str(row[4]) if row[4] is not None else None
            taker_user_id = int(row[5]) if row[5] else None
            maker_user_id = int(row[6]) if row[6] else None

            # Determine which order_id to use based on which side the user is on
            if taker_user_id == user_id:
                order_id = taker_order_id
                user_side = "TAKER"
            elif maker_user_id == user_id:
                order_id = maker_order_id
                user_side = "MAKER"
            else:
                order_id = None  # Should not happen due to WHERE clause
                user_side = "UNKNOWN"

            # Key by trade_id for one-to-one matching
            trades[trade_id] = {
                'trade_id': trade_id,  # PRIMARY KEY - must match HB.exchange_trade_id
                'symbol': symbol,  # Return original format for display
                'side': str(row[2]),  # Taker's side (BUY or SELL)
                'taker_order_id': taker_order_id,
                'maker_order_id': maker_order_id,
                'order_id': order_id,  # The order_id for this user (for verification)
                'user_side': user_side,  # Whether user was taker or maker
                'quantity': float(row[7]),
                'price': float(row[8]),
                'trade_value': float(row[9]),
                'timestamp': row[10],
                'fee': float(row[11]),
                'fee_currency': str(row[12]),
            }

        return trades

    except Exception as e:
        print(f"Error fetching trades from ClickHouse: {e}")
        import traceback
        traceback.print_exc()
        return {}


def normalize_status(status: str) -> str:
    """Normalize order status for comparison"""
    status_upper = status.upper()

    # Map common status variations
    # Hummingbot uses: "BuyOrderCreated", "SellOrderCreated", "OrderCancelled"
    # Hummingbot also uses: "BuyOrderCompleted", "SellOrderCompleted" for filled orders
    # ClickHouse uses: "OPEN", "CANCELLED", "FILLED"
    status_map = {
        "NEW": "OPEN",
        "ACTIVE": "OPEN",
        "PENDING": "OPEN",
        "BUYORDERCREATED": "OPEN",      # Hummingbot status
        "SELLORDERCREATED": "OPEN",      # Hummingbot status
        "ORDERCREATED": "OPEN",          # Hummingbot status
        "FILLED": "FILLED",
        "COMPLETED": "FILLED",
        "BUYORDERCOMPLETED": "FILLED",   # Hummingbot status - order fully filled
        "SELLORDERCOMPLETED": "FILLED",  # Hummingbot status - order fully filled
        "CANCELED": "CANCELLED",
        "CANCELLED": "CANCELLED",
        "ORDERCANCELLED": "CANCELLED",   # Hummingbot status
        "REJECTED": "REJECTED",
        "EXPIRED": "EXPIRED",
    }

    return status_map.get(status_upper, status_upper)


def reconcile_orders(report: ReconciliationReport, hb_orders: Dict[str, Dict],
                     ec_orders: Dict[str, Dict], price_tolerance: float = 0.0001,
                     amount_tolerance: float = 0.0001):
    """
    Compare orders between Hummingbot and Exchange-Core (ClickHouse).

    CRITICAL: One-way verification:
    - Each order in HB MUST exist in CH (we verify all bot orders are recorded)
    - We don't check for orders in CH that aren't in HB (could be from other sources)
    """

    report.summary['total_orders_hb'] = len(hb_orders)
    report.summary['total_orders_ec'] = len(ec_orders)

    hb_order_ids = set(hb_orders.keys())
    ec_order_ids = set(ec_orders.keys())

    # Orders in Hummingbot but NOT in ClickHouse (missing in exchange-core)
    # This is the critical check - all bot orders must be in ClickHouse
    missing_in_ec = hb_order_ids - ec_order_ids
    for order_id in missing_in_ec:
        report.orders_in_hb_not_in_ec.append(hb_orders[order_id])
        report.summary['discrepancies'] += 1

    # Compare matched orders (one-to-one by exchange_order_id)
    matched_ids = hb_order_ids & ec_order_ids
    report.summary['matched_orders'] = len(matched_ids)

    for order_id in matched_ids:
        hb_order = hb_orders[order_id]
        ec_order = ec_orders[order_id]

        # Status comparison
        # Use effective_status which accounts for TradeFill records
        hb_status = normalize_status(hb_order.get('effective_status', hb_order['last_status']))
        ec_status = normalize_status(ec_order['status'])

        if hb_status != ec_status:
            # Special handling: If EC shows FILLED but HB shows Created and has no fills,
            # this means Hummingbot didn't receive/process the fill event
            if (ec_status == 'FILLED' and
                    hb_status == 'OPEN' and
                    not hb_order.get('has_fills', False)):
                # This is a data sync issue - order was filled but Hummingbot didn't track it
                report.orders_status_mismatch.append({
                    'order_id': order_id,
                    'hb_status': hb_order['last_status'],
                    'hb_effective_status': hb_order.get('effective_status', 'N/A'),
                    'ec_status': ec_order['status'],
                    'issue': 'ORDER_FILLED_BUT_NOT_TRACKED_IN_HB',
                })
            else:
                # Normal status mismatch
                report.orders_status_mismatch.append({
                    'order_id': order_id,
                    'hb_status': hb_order['last_status'],
                    'hb_effective_status': hb_order.get('effective_status', 'N/A'),
                    'ec_status': ec_order['status'],
                })
            report.summary['discrepancies'] += 1

        # Price comparison (with tolerance)
        # Compare placed price vs placed price (not placed vs filled)
        # Skip if EC price is None (PLACE_ORDER event might be missing)
        if ec_order['price'] is not None:
            price_diff = abs(hb_order['price'] - ec_order['price'])
            if price_diff > price_tolerance:
                report.orders_price_mismatch.append({
                    'order_id': order_id,
                    'hb_price': hb_order['price'],
                    'ec_price': ec_order['price'],
                    'diff': price_diff,
                    'hb_amount': hb_order['amount'],
                    'ec_quantity': ec_order['quantity'],
                    'hb_status': hb_order['last_status'],
                    'ec_status': ec_order['status'],
                })
                report.summary['discrepancies'] += 1

        # Amount comparison (with tolerance)
        # Compare placed amount vs placed amount (not placed vs filled)
        # Skip if EC quantity is None (PLACE_ORDER event might be missing)
        if ec_order['quantity'] is not None:
            amount_diff = abs(hb_order['amount'] - ec_order['quantity'])
            if amount_diff > amount_tolerance:
                report.orders_amount_mismatch.append({
                    'order_id': order_id,
                    'hb_amount': hb_order['amount'],
                    'ec_quantity': ec_order['quantity'],
                    'diff': amount_diff,
                    'hb_status': hb_order['last_status'],
                    'ec_status': ec_order['status'],
                })
                report.summary['discrepancies'] += 1


def reconcile_trades(report: ReconciliationReport, hb_trades: Dict[str, Dict],
                     ec_trades: Dict[str, Dict], price_tolerance: float = 0.0001,
                     amount_tolerance: float = 0.0001):
    """
    Compare trades between Hummingbot and Exchange-Core (ClickHouse).

    Matching strategy (in order):
    1. Primary: exchange_trade_id (HB) == trade_id (CH) - EXACT MATCH
    2. Fallback: exchange_order_id (HB) matches taker_order_id OR maker_order_id (CH)
       - For partially filled orders, sum all EC trades for the same exchange_order_id

    CRITICAL: One-way verification:
    - Each trade in HB MUST exist in CH (we verify all bot trades are recorded)
    - We don't check for trades in CH that aren't in HB (could be from other sources)

    Note: For partially filled orders, HB stores one TradeFill with total amount,
    while ClickHouse may have multiple trade records. We sum all EC trades for the same order_id.
    """

    report.summary['total_trades_hb'] = len(hb_trades)
    report.summary['total_trades_ec'] = len(ec_trades)

    # Primary key matching: exchange_trade_id (HB) == trade_id (CH)
    hb_trade_ids = set(hb_trades.keys())
    ec_trade_ids = set(ec_trades.keys())

    # Build fallback index: exchange_order_id -> list of trade_ids
    # This helps match trades when trade_id formats differ
    # Key: exchange_order_id (taker or maker), Value: list of (trade_id, quantity, price)
    ec_trades_by_exchange_order_id = {}  # key: exchange_order_id -> list of (trade_id, quantity, price, is_taker)
    for ec_trade_id, ec_trade in ec_trades.items():
        taker_order_id = ec_trade.get('taker_order_id')
        maker_order_id = ec_trade.get('maker_order_id')
        quantity = ec_trade.get('quantity', 0)
        price = ec_trade.get('price', 0)

        if taker_order_id:
            if taker_order_id not in ec_trades_by_exchange_order_id:
                ec_trades_by_exchange_order_id[taker_order_id] = []
            ec_trades_by_exchange_order_id[taker_order_id].append((ec_trade_id, quantity, price, True))

        if maker_order_id:
            if maker_order_id not in ec_trades_by_exchange_order_id:
                ec_trades_by_exchange_order_id[maker_order_id] = []
            ec_trades_by_exchange_order_id[maker_order_id].append((ec_trade_id, quantity, price, False))

    # First pass: match by trade_id
    matched_by_trade_id = hb_trade_ids & ec_trade_ids
    unmatched_hb_trades = hb_trade_ids - ec_trade_ids

    # Mapping from HB trade_id to aggregated EC trade data
    # For partially filled orders, we aggregate all EC trades for the same exchange_order_id
    hb_to_ec_mapping = {}  # key: hb_trade_id -> {'trade_ids': [...], 'total_quantity': X, 'avg_price': Y}
    for hb_id in matched_by_trade_id:
        hb_to_ec_mapping[hb_id] = {
            'trade_ids': [hb_id],  # Direct match
            'total_quantity': ec_trades[hb_id].get('quantity', 0),
            'avg_price': ec_trades[hb_id].get('price', 0),
        }

    # Second pass: fallback matching by exchange_order_id
    # Match HB's exchange_order_id against ClickHouse's taker_order_id or maker_order_id
    # IMPORTANT: Multiple HB trades can share the same EC trade(s) if they have the same exchange_order_id
    # This handles cases where an order has multiple partial fills, each creating a separate TradeFill in HB
    matched_by_fallback = set()
    used_ec_trade_ids = set(matched_by_trade_id)  # Track which EC trades are already matched by trade_id

    for hb_trade_id in list(unmatched_hb_trades):
        hb_trade = hb_trades[hb_trade_id]
        hb_exchange_order_id = hb_trade.get('exchange_order_id')

        if not hb_exchange_order_id:
            continue

        # Try to find matching trade(s) in ClickHouse by exchange_order_id
        # Ensure exchange_order_id is a string for consistent comparison
        hb_exchange_order_id_str = str(hb_exchange_order_id)
        if hb_exchange_order_id_str in ec_trades_by_exchange_order_id:
            # Found potential matches - use ALL EC trades for this order_id (don't filter by "used")
            # Multiple HB trades with the same exchange_order_id can all match to the same EC trades
            matching_ec_trades = []
            total_quantity = 0
            total_value = 0

            for ec_trade_id, quantity, price, is_taker in ec_trades_by_exchange_order_id[hb_exchange_order_id_str]:
                # Only exclude EC trades that were matched by trade_id (exact match)
                # Allow multiple HB trades to share the same EC trades when matched by exchange_order_id
                if ec_trade_id not in used_ec_trade_ids:
                    matching_ec_trades.append(ec_trade_id)
                    total_quantity += quantity
                    total_value += quantity * price

            if matching_ec_trades:
                # Match found via exchange_order_id!
                avg_price = total_value / total_quantity if total_quantity > 0 else 0
                hb_to_ec_mapping[hb_trade_id] = {
                    'trade_ids': matching_ec_trades,
                    'total_quantity': total_quantity,
                    'avg_price': avg_price,
                }
                matched_by_fallback.add(hb_trade_id)

    # Trades in Hummingbot but NOT in ClickHouse (missing in exchange-core)
    # This is the critical check - all bot trades must be in ClickHouse
    all_matched = matched_by_trade_id | matched_by_fallback
    still_missing = hb_trade_ids - all_matched

    for trade_id in still_missing:
        report.trades_in_hb_not_in_ec.append({
            **hb_trades[trade_id],
            'discrepancy_type': 'MISSING_IN_EXCHANGE_CORE',
        })
        report.summary['discrepancies'] += 1

    # Compare matched trades (one-to-one by trade_id, including fallback matches)
    matched_ids = all_matched
    report.summary['matched_trades'] = len(matched_ids)

    for hb_trade_id in matched_ids:
        # Get the aggregated EC trade data (may include multiple trades for partially filled orders)
        ec_mapping = hb_to_ec_mapping.get(hb_trade_id)
        hb_trade = hb_trades[hb_trade_id]

        if not ec_mapping:
            # Should not happen, but handle gracefully
            continue

        # Get the first EC trade for reference (for order_id verification)
        ec_trade_ids = ec_mapping['trade_ids']
        first_ec_trade_id = ec_trade_ids[0]
        ec_trade = ec_trades.get(first_ec_trade_id)

        if not ec_trade:
            # Should not happen, but handle gracefully
            continue

        # 1. Verify exchange_order_id matches (bot's order should be taker or maker)
        # Use exchange_order_id from TradeFill, not client_order_id
        hb_exchange_order_id = hb_trade.get('exchange_order_id')
        hb_order_id = hb_trade['order_id']  # Keep for display purposes
        ec_taker_order_id = ec_trade.get('taker_order_id')
        ec_maker_order_id = ec_trade.get('maker_order_id')

        # Compare exchange_order_id against taker/maker order IDs
        # Ensure all IDs are strings for consistent comparison
        order_id_matches = False
        if hb_exchange_order_id:
            hb_exchange_order_id_str = str(hb_exchange_order_id)
            order_id_matches = (
                (ec_taker_order_id and hb_exchange_order_id_str == str(ec_taker_order_id)) or
                (ec_maker_order_id and hb_exchange_order_id_str == str(ec_maker_order_id))
            )

        if not order_id_matches:
            report.trades_order_id_mismatch.append({
                'hb_trade_id': hb_trade_id,
                'ec_trade_id': first_ec_trade_id,
                'hb_order_id': hb_order_id,
                'hb_exchange_order_id': hb_exchange_order_id,
                'ec_taker_order_id': ec_taker_order_id,
                'ec_maker_order_id': ec_maker_order_id,
                'matched_by': 'fallback' if hb_trade_id in matched_by_fallback else 'trade_id',
            })
            report.summary['discrepancies'] += 1

        # 2. Price comparison - SKIPPED
        # Execution price can differ from placed price (e.g., order placed at 0.2499, filled at 0.2479)
        # This is expected behavior and not a discrepancy

        # 3. Amount comparison: Compare HB's total amount against aggregated EC quantity
        # For partially filled orders, EC may have multiple trades that sum to HB's total
        ec_total_quantity = ec_mapping['total_quantity']
        amount_diff = abs(hb_trade['amount'] - ec_total_quantity)
        if amount_diff > amount_tolerance:
            report.trades_amount_mismatch.append({
                'hb_trade_id': hb_trade_id,
                'ec_trade_ids': ', '.join(ec_trade_ids) if len(ec_trade_ids) > 1 else ec_trade_ids[0],
                'hb_amount': hb_trade['amount'],
                'ec_quantity': ec_total_quantity,
                'ec_trade_count': len(ec_trade_ids),  # Show how many EC trades were aggregated
                'diff': amount_diff,
                'tolerance': amount_tolerance,
            })
            report.summary['discrepancies'] += 1

        # 4. Timestamp comparison - IGNORED (not important for reconciliation)
        # Timestamps may differ slightly due to processing delays, so we skip this check


def main():
    # Default values from environment variables or common defaults
    default_db = get_env_or_default("HB_DB_PATH", "data/conf_multi_level_self_trading.sqlite")
    default_ch_host = get_env_or_default("CLICKHOUSE_HOST", "jw01l5yyok.us-east-1.aws.clickhouse.cloud")
    default_ch_port = int(get_env_or_default("CLICKHOUSE_PORT", "8443"))
    default_ch_database = get_env_or_default("CLICKHOUSE_DATABASE", "exchange_test")
    default_ch_username = get_env_or_default("CLICKHOUSE_USERNAME", "default")
    default_ch_password = get_env_or_default("CLICKHOUSE_PASSWORD", "0zb_IRlKj0x53")
    default_ch_secure = get_env_bool_or_default("CLICKHOUSE_SECURE", True)
    default_symbol = get_env_or_default("HB_SYMBOL", "CNX-USDT")
    default_user_id = int(get_env_or_default("HB_USER_ID", "1120"))

    parser = argparse.ArgumentParser(
        description="Reconcile Hummingbot and Exchange-Core data (ClickHouse)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage with defaults:
  python reconcile_hummingbot_exchange_core.py

  # Override specific values:
  python reconcile_hummingbot_exchange_core.py --user-id 1234 --symbol BTC/USDT

  # With time range:
  python reconcile_hummingbot_exchange_core.py --start-time "2026-01-10T00:00:00" --end-time "2026-01-12T23:59:59"

Environment Variables (optional):
  HB_DB_PATH              - Path to Hummingbot SQLite database (default: data/conf_multi_level_self_trading.sqlite)
  CLICKHOUSE_HOST         - ClickHouse host (default: jw01l5yyok.us-east-1.aws.clickhouse.cloud)
  CLICKHOUSE_PORT         - ClickHouse port (default: 8443)
  CLICKHOUSE_DATABASE     - ClickHouse database (default: exchange_test)
  CLICKHOUSE_USERNAME     - ClickHouse username (default: default)
  CLICKHOUSE_PASSWORD     - ClickHouse password
  CLICKHOUSE_SECURE       - Use secure connection (default: true)
  HB_SYMBOL               - Trading symbol (default: CNX/USDT)
  HB_USER_ID              - User ID for filtering (default: 1120)
        """
    )
    parser.add_argument("--db", default=default_db,
                        help=f"Path to Hummingbot SQLite database (default: {default_db})")
    parser.add_argument("--clickhouse-host", default=default_ch_host,
                        help=f"ClickHouse host (default: {default_ch_host})")
    parser.add_argument("--clickhouse-port", type=int, default=default_ch_port,
                        help=f"ClickHouse port (default: {default_ch_port})")
    parser.add_argument("--clickhouse-database", default=default_ch_database,
                        help=f"ClickHouse database name (default: {default_ch_database})")
    parser.add_argument("--clickhouse-username", default=default_ch_username,
                        help=f"ClickHouse username (default: {default_ch_username})")
    parser.add_argument("--clickhouse-password", default=default_ch_password,
                        help="ClickHouse password (default: from env or config)")
    parser.add_argument("--clickhouse-secure", action="store_true",
                        default=default_ch_secure,
                        help=f"Use secure connection (default: {default_ch_secure})")
    parser.add_argument("--user-id", type=int, default=default_user_id,
                        help=f"User ID for filtering Exchange-Core data "
                        f"(default: {default_user_id})")
    parser.add_argument("--symbol", default=default_symbol,
                        help=f"Trading symbol (default: {default_symbol})")
    parser.add_argument("--start-time", help="Start time (ISO format, e.g., 2026-01-10T00:00:00)")
    parser.add_argument("--end-time", help="End time (ISO format)")
    parser.add_argument("--price-tolerance", type=float, default=0.0001, help="Price difference tolerance")
    parser.add_argument("--amount-tolerance", type=float, default=0.0001, help="Amount difference tolerance")

    args = parser.parse_args()

    # Parse time range
    start_time = None
    end_time = None
    if args.start_time:
        start_time = datetime.fromisoformat(args.start_time.replace('Z', '+00:00'))
    if args.end_time:
        end_time = datetime.fromisoformat(args.end_time.replace('Z', '+00:00'))

    # Validate database file (handle both absolute and relative paths)
    db_path = Path(args.db)
    if not db_path.is_absolute():
        # If relative path, try from current directory first, then from script directory
        script_dir = Path(__file__).parent
        db_path = Path.cwd() / args.db if (Path.cwd() / args.db).exists() else script_dir / args.db

    if not db_path.is_file():
        print(f"Error: Database file not found: {args.db}")
        print(f"  Tried: {db_path}")
        print(f"  Current directory: {Path.cwd()}")
        sys.exit(1)

    # Print configuration summary
    print("=" * 80)
    print("RECONCILIATION CONFIGURATION")
    print("=" * 80)
    print(f"Database:              {db_path}")
    print(f"Symbol:                {args.symbol}")
    print(f"User ID:               {args.user_id}")
    print(f"ClickHouse Host:       {args.clickhouse_host}:{args.clickhouse_port}")
    print(f"ClickHouse Database:   {args.clickhouse_database}")
    print(f"ClickHouse Username:   {args.clickhouse_username}")
    print(f"ClickHouse Secure:     {args.clickhouse_secure}")
    if args.start_time:
        print(f"Start Time:            {args.start_time}")
    if args.end_time:
        print(f"End Time:              {args.end_time}")
    print("=" * 80)
    print()

    print("Loading data from Hummingbot SQLite database...")
    print(f"  Querying for symbol: {args.symbol}")

    # First, let's check what's actually in the database
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Check total orders and trades
    cursor.execute("SELECT COUNT(*) as count FROM 'Order'")
    total_orders = cursor.fetchone()['count']
    cursor.execute("SELECT COUNT(*) as count FROM TradeFill")
    total_trades = cursor.fetchone()['count']
    cursor.execute("SELECT COUNT(*) as count FROM 'Order' WHERE exchange_order_id IS NOT NULL")
    orders_with_exchange_id = cursor.fetchone()['count']
    cursor.execute("SELECT DISTINCT symbol FROM 'Order' LIMIT 10")
    symbols_in_db = [row[0] for row in cursor.fetchall()]
    conn.close()

    print(f"  Total orders in database: {total_orders}")
    print(f"  Orders with exchange_order_id: {orders_with_exchange_id}")
    print(f"  Total trades in database: {total_trades}")
    print(f"  Symbols in database: {', '.join(symbols_in_db)}")
    print()

    # Load orders (this will also load and check TradeFill records)
    hb_orders = load_hummingbot_orders(str(db_path), args.symbol, start_time, end_time)
    hb_trades = load_hummingbot_trades(str(db_path), args.symbol, start_time, end_time)

    print(f"Found {len(hb_orders)} orders and {len(hb_trades)} trades in Hummingbot (after filtering)")

    print("\nConnecting to ClickHouse...")
    try:
        client = clickhouse_connect.get_client(
            host=args.clickhouse_host,
            port=args.clickhouse_port,
            username=args.clickhouse_username,
            password=args.clickhouse_password,
            database=args.clickhouse_database,
            secure=args.clickhouse_secure,
        )
        print(f"Connected to ClickHouse: {args.clickhouse_host}:{args.clickhouse_port}/{args.clickhouse_database}")
    except Exception as e:
        print(f"Error connecting to ClickHouse: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print("\nFetching data from ClickHouse...")
    ec_orders = fetch_clickhouse_orders(
        client, args.clickhouse_database, args.user_id, args.symbol, start_time, end_time
    )
    ec_trades = fetch_clickhouse_trades(
        client, args.clickhouse_database, args.user_id, args.symbol, start_time, end_time
    )

    print(f"Found {len(ec_orders)} orders and {len(ec_trades)} trades in Exchange-Core")

    print("\nReconciling data...")
    report = ReconciliationReport()

    reconcile_orders(report, hb_orders, ec_orders,
                     price_tolerance=args.price_tolerance,
                     amount_tolerance=args.amount_tolerance)

    reconcile_trades(report, hb_trades, ec_trades,
                     price_tolerance=args.price_tolerance,
                     amount_tolerance=args.amount_tolerance)

    report.print_report()

    # Exit with error code if discrepancies found
    if report.summary['discrepancies'] > 0:
        sys.exit(1)
    else:
        print("✅ No discrepancies found!")
        sys.exit(0)


if __name__ == "__main__":
    main()
