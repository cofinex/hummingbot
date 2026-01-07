#!/usr/bin/env python3
"""
Quick test script to verify Cofinex connector components work locally.

Run this from the project root:
    python test_cofinex_connection.py
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from hummingbot.connector.exchange.cofinex import (
    cofinex_auth,
    cofinex_constants as CONSTANTS,
    cofinex_web_utils as web_utils,
)


async def test_constants():
    """Test that constants are properly defined"""
    print("=" * 60)
    print("Testing Constants")
    print("=" * 60)

    try:
        print(f"✅ Exchange name: {CONSTANTS.EXCHANGE_NAME}")
        print(f"✅ Default domain: {CONSTANTS.DEFAULT_DOMAIN}")
        print(f"✅ Base URL: {CONSTANTS.BASE_PATH_URL}")
        print(f"✅ Rate limits defined: {len(CONSTANTS.RATE_LIMITS)} limits")
        return True
    except Exception as e:
        print(f"❌ Constants error: {e}")
        return False


async def test_web_utils():
    """Test web utilities"""
    print("\n" + "=" * 60)
    print("Testing Web Utils")
    print("=" * 60)

    try:
        # Test URL building
        public_url = web_utils.public_rest_url("/api/v1/test")
        print(f"✅ Public URL builder works: {public_url}")

        # Test throttler creation
        throttler = web_utils.create_throttler()
        print(f"✅ Throttler created: {type(throttler).__name__}")

        # Test API factory (without auth)
        api_factory = web_utils.build_api_factory_without_time_synchronizer_pre_processor(throttler)
        print(f"✅ API factory created: {type(api_factory).__name__}")

        return True
    except Exception as e:
        print(f"❌ Web utils error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_auth():
    """Test authentication"""
    print("\n" + "=" * 60)
    print("Testing Authentication")
    print("=" * 60)

    try:
        # Test auth object creation
        auth = cofinex_auth.CofinexAuth(
            api_key="test_key",
            secret_key="test_secret"
        )
        print(f"✅ Auth object created: {type(auth).__name__}")

        # Test signature generation
        timestamp = "1234567890"
        method = "GET"
        path = "/api/v1/account"
        body = ""

        signature = auth.generate_signature(timestamp, method, path, body)
        print(f"✅ Signature generated: {signature[:20]}...")

        # Test headers
        headers = auth.get_auth_headers(method, path, body)
        print(f"✅ Auth headers: {list(headers.keys())}")

        return True
    except Exception as e:
        print(f"❌ Auth error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_api_connection():
    """Test actual API connection (if endpoints are correct)"""
    print("\n" + "=" * 60)
    print("Testing API Connection")
    print("=" * 60)

    try:
        # Try to get server time (this is a common public endpoint)
        print("Attempting to fetch server time...")
        print("⚠️  Note: This will fail if Cofinex API endpoints are not correct yet")

        server_time = await web_utils.get_current_server_time()
        print(f"✅ Server time retrieved: {server_time}")
        return True
    except Exception as e:
        print(f"⚠️  API connection test failed (expected if endpoints not configured): {e}")
        print("   This is OK - you need to update endpoints in cofinex_constants.py")
        return False


async def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("Cofinex Connector Local Test")
    print("=" * 60)
    print()

    results = []

    # Test constants
    results.append(await test_constants())

    # Test web utils
    results.append(await test_web_utils())

    # Test auth
    results.append(await test_auth())

    # Test API connection (may fail if endpoints not configured)
    api_result = await test_api_connection()
    # Don't count API connection failure as a test failure since endpoints may not be configured

    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)

    component_tests = sum(results)
    total_tests = len(results)

    print(f"Component tests passed: {component_tests}/{total_tests}")

    if component_tests == total_tests:
        print("✅ All component tests passed!")
        print("\nNext steps:")
        print("1. Update cofinex_constants.py with actual Cofinex API endpoints")
        print("2. Complete the exchange class implementation")
        print("3. Register the connector in AllConnectorSettings")
        print("4. Test with paper trading")
    else:
        print("❌ Some component tests failed")
        print("Please check the errors above and fix them")

    print()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
