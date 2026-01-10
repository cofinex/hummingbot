#!/usr/bin/env python3
"""
Cleanup script to remove old cancelled/expired orders from Hummingbot database.

This helps reduce database size by removing unnecessary order records.

Usage:
    python scripts/cleanup_old_orders.py --db data/conf_multi_level_self_trading.sqlite --days 7 --execute

Options:
    --db: Database file path (required)
    --days: Keep orders newer than N days (default: 7)
    --status: Only remove orders with specific status (default: CANCELLED,EXPIRED)
    --execute: Actually delete (default is dry-run)
"""

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path


def cleanup_old_orders(db_path: str, days: int = 7, statuses: list = None, execute: bool = False):
    """
    Clean up old orders from database.

    Args:
        db_path: Path to SQLite database
        days: Keep orders newer than N days
        statuses: List of statuses to remove (e.g., ['CANCELLED', 'EXPIRED'])
        execute: If False, only show what would be deleted (dry-run)
    """
    if statuses is None:
        statuses = ['CANCELLED', 'EXPIRED']

    db_path_obj = Path(db_path)

    # If path is a directory, look for .sqlite files
    if db_path_obj.is_dir():
        sqlite_files = list(db_path_obj.glob("*.sqlite"))
        if not sqlite_files:
            print(f"Error: No .sqlite files found in directory: {db_path}")
            return
        if len(sqlite_files) == 1:
            db_path = str(sqlite_files[0])
            print(f"Found database: {db_path}")
        else:
            print(f"Error: Multiple .sqlite files found in {db_path}:")
            for f in sqlite_files:
                print(f"  - {f}")
            print("Please specify the exact file path.")
            return
    elif not db_path_obj.exists():
        print(f"Error: Database not found: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Calculate cutoff timestamp (milliseconds)
    cutoff_date = datetime.now() - timedelta(days=days)
    cutoff_timestamp = int(cutoff_date.timestamp() * 1000)

    # Build status filter
    status_filter = "', '".join(statuses)

    # Find orders to delete
    query = f"""
        SELECT id, last_status, creation_timestamp, symbol, amount, price
        FROM 'Order'
        WHERE last_status IN ('{status_filter}')
        AND creation_timestamp < {cutoff_timestamp}
        ORDER BY creation_timestamp DESC
    """

    cursor.execute(query)
    orders_to_delete = cursor.fetchall()

    if not orders_to_delete:
        print(f"No orders found to delete (older than {days} days with status: {statuses})")
        conn.close()
        return

    print("=" * 80)
    print(f"ORDERS TO DELETE (older than {days} days, status: {statuses})")
    print("=" * 80)
    print(f"Total: {len(orders_to_delete):,} orders")
    print()

    # Show sample
    print("Sample (first 10):")
    print("-" * 80)
    for order_id, status, timestamp, symbol, amount, price in orders_to_delete[:10]:
        date_str = datetime.fromtimestamp(timestamp / 1000).strftime("%Y-%m-%d %H:%M:%S")
        print(f"  {order_id[:20]:20} {status:15} {date_str:20} {symbol:15} {amount:>10} @ {price}")

    if len(orders_to_delete) > 10:
        print(f"  ... and {len(orders_to_delete) - 10} more")

    print()

    if not execute:
        print("DRY RUN - No changes made. Use --execute to actually delete.")
        conn.close()
        return

    # Delete order statuses first (foreign key constraint)
    order_ids = [order[0] for order in orders_to_delete]
    placeholders = ','.join(['?' for _ in order_ids])

    # Count order statuses to delete
    cursor.execute(f"SELECT COUNT(*) FROM 'OrderStatus' WHERE order_id IN ({placeholders})", order_ids)
    status_count = cursor.fetchone()[0]

    # Count trade fills to delete (if any)
    cursor.execute(f"SELECT COUNT(*) FROM 'TradeFill' WHERE order_id IN ({placeholders})", order_ids)
    fill_count = cursor.fetchone()[0]

    print("Deleting:")
    print(f"  - {len(orders_to_delete):,} orders")
    print(f"  - {status_count:,} order status events")
    print(f"  - {fill_count:,} trade fills")
    print()

    # Delete in transaction
    try:
        # Delete order statuses
        if status_count > 0:
            cursor.execute(f"DELETE FROM 'OrderStatus' WHERE order_id IN ({placeholders})", order_ids)

        # Delete trade fills
        if fill_count > 0:
            cursor.execute(f"DELETE FROM 'TradeFill' WHERE order_id IN ({placeholders})", order_ids)

        # Delete orders
        cursor.execute(f"DELETE FROM 'Order' WHERE id IN ({placeholders})", order_ids)

        conn.commit()

        # Vacuum to reclaim space
        print("Vacuuming database to reclaim space...")
        cursor.execute("VACUUM")
        conn.commit()

        # Get new size
        import os
        new_size = os.path.getsize(db_path) / (1024 * 1024)

        print()
        print("=" * 80)
        print("CLEANUP COMPLETE")
        print("=" * 80)
        print(f"Deleted {len(orders_to_delete):,} orders")
        print(f"Database size after cleanup: {new_size:.2f} MB")

    except Exception as e:
        conn.rollback()
        print(f"Error during cleanup: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clean up old orders from Hummingbot database")
    parser.add_argument("--db", required=True, help="Database file path")
    parser.add_argument("--days", type=int, default=7, help="Keep orders newer than N days (default: 7)")
    parser.add_argument("--status", help="Comma-separated list of statuses to remove (default: CANCELLED,EXPIRED)")
    parser.add_argument("--execute", action="store_true", help="Actually delete (default is dry-run)")

    args = parser.parse_args()

    statuses = None
    if args.status:
        statuses = [s.strip() for s in args.status.split(",")]

    cleanup_old_orders(args.db, args.days, statuses, args.execute)
