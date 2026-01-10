#!/usr/bin/env python3
"""Test script to debug Cofinex connector discovery"""

import importlib
import sys
import traceback

print("=" * 60)
print("Testing Cofinex Connector Discovery")
print("=" * 60)

# Test 1: Direct import of cofinex_utils
print("\n1. Testing direct import of cofinex_utils...")
try:
    util_module = importlib.import_module('hummingbot.connector.exchange.cofinex.cofinex_utils')
    print("   ✅ Import successful!")
    print(f"   CENTRALIZED: {getattr(util_module, 'CENTRALIZED', 'NOT FOUND')}")
    print(f"   EXAMPLE_PAIR: {getattr(util_module, 'EXAMPLE_PAIR', 'NOT FOUND')}")
    print(f"   KEYS: {type(getattr(util_module, 'KEYS', None))}")
except Exception as e:
    print(f"   ❌ Import failed: {type(e).__name__}: {e}")
    traceback.print_exc()
    sys.exit(1)

# Test 2: Full connector discovery
print("\n2. Testing full connector discovery...")
try:
    from hummingbot.client.settings import AllConnectorSettings
    AllConnectorSettings.create_connector_settings()

    print(f"   Total connectors found: {len(AllConnectorSettings.all_connector_settings)}")
    print(f"   Cofinex found: {'cofinex' in AllConnectorSettings.all_connector_settings}")

    if 'cofinex' in AllConnectorSettings.all_connector_settings:
        setting = AllConnectorSettings.all_connector_settings['cofinex']
        print("   ✅ Cofinex connector registered!")
        print(f"      Type: {setting.type}")
        print(f"      Example pair: {setting.example_pair}")
        print(f"      Config keys: {setting.config_keys}")
    else:
        print("   ❌ Cofinex connector NOT found in settings")
        print("   Available connectors (first 10):")
        for name in list(AllConnectorSettings.all_connector_settings.keys())[:10]:
            print(f"      - {name}")

    # Check paper trade
    # Note: Paper trade connectors are created when Hummingbot starts via initialize_paper_trade_settings()
    # They're not created during discovery, so we need to simulate that
    print(f"\n   Paper trade connectors (before init): {len(AllConnectorSettings.paper_trade_connectors_names)}")

    # Simulate what Hummingbot does on startup
    from hummingbot.client.config.config_helpers import load_client_config_map_from_file
    try:
        client_config = load_client_config_map_from_file()
        paper_trade_exchanges = client_config.paper_trade.paper_trade_exchanges
        print(f"   Paper trade exchanges from config: {paper_trade_exchanges}")

        # Initialize paper trade settings (this is what Hummingbot does on startup)
        AllConnectorSettings.initialize_paper_trade_settings(paper_trade_exchanges)

        print(f"   Paper trade connectors (after init): {len(AllConnectorSettings.paper_trade_connectors_names)}")
        print(f"   cofinex_paper_trade available: {'cofinex_paper_trade' in AllConnectorSettings.all_connector_settings}")

        if 'cofinex_paper_trade' in AllConnectorSettings.all_connector_settings:
            print("   ✅ cofinex_paper_trade connector is available!")
        else:
            print("   ⚠️  cofinex_paper_trade not in paper_trade_exchanges list")
            print("   💡 Add 'cofinex' to paper_trade_exchanges in client config to enable paper trading")
    except Exception as e:
        print(f"   ⚠️  Could not load client config: {e}")
        print("   💡 Paper trade will be available when you start Hummingbot")

except Exception as e:
    print(f"   ❌ Discovery failed: {type(e).__name__}: {e}")
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 60)
print("Test completed!")
print("=" * 60)
