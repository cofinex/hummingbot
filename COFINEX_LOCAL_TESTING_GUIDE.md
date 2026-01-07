# Testing Cofinex Connector Locally on macOS

This guide will help you test the Cofinex connector on your MacBook Air.

## Prerequisites

### 1. Install Required Software

```bash
# Install Homebrew (if not already installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Python 3.12 (or the version Hummingbot requires)
brew install python@3.12

# Install Conda (Miniconda or Anaconda)
# Download from: https://docs.conda.io/en/latest/miniconda.html
# Or use Homebrew:
brew install --cask miniconda

# Install Git (if not already installed)
brew install git
```

### 2. Set Up Conda Environment

```bash
# Navigate to your Hummingbot directory
cd ~/hummingbot  # or wherever you cloned it

# Create Conda environment (if not already created)
conda env create -f setup/environment.yml

# Activate the environment
conda activate hummingbot

# Install additional dependencies
pip install -r setup/pip_packages.txt
```

### 3. Build Cython Extensions

```bash
# Make sure you're in the hummingbot directory
cd ~/hummingbot

# Build Cython extensions (required for macOS)
python setup.py build_ext --inplace

# Or use the compile script
./compile
```

## Running Hummingbot Locally

### Option 1: Run from Source (Recommended for Development)

```bash
# Activate Conda environment
conda activate hummingbot

# Navigate to project root
cd ~/hummingbot

# Run Hummingbot
python bin/hummingbot.py
```

### Option 2: Use Quick Start Script

```bash
# Activate Conda environment
conda activate hummingbot

# Run quick start
python bin/hummingbot_quickstart.py
```

### Option 3: Use Makefile

```bash
# Run tests
make test

# Run v2 quickstart
make run-v2
```

## Testing the Cofinex Connector

### Step 1: Register the Connector

Before testing, you need to register the connector in Hummingbot's settings. We'll need to:

1. Create a configuration map file
2. Register it in `AllConnectorSettings`

**For now, let's test if the code compiles:**

```bash
# Check for syntax errors
python -m py_compile hummingbot/connector/exchange/cofinex/*.py

# Check imports
python -c "from hummingbot.connector.exchange.cofinex.cofinex_auth import CofinexAuth; print('Import successful')"
```

### Step 2: Test with Paper Trading (Safest)

Paper trading allows you to test without real money:

```bash
# Start Hummingbot
python bin/hummingbot.py

# In Hummingbot CLI:
# 1. Type: create
# 2. Select a strategy (e.g., "pure_market_making")
# 3. When asked for exchange, try: cofinex_paper_trade
# 4. Set paper trade balances
```

### Step 3: Test API Connection (Without Trading)

Create a simple test script to verify API connectivity:

```python
# test_cofinex_connection.py
import asyncio
from hummingbot.connector.exchange.cofinex import cofinex_web_utils as web_utils

async def test_connection():
    """Test basic API connection"""
    try:
        # Test server time endpoint
        server_time = await web_utils.get_current_server_time()
        print(f"✅ Server time: {server_time}")

        # Test order book endpoint (public, no auth needed)
        from hummingbot.core.web_assistant.connections.data_types import RESTMethod
        from hummingbot.core.api_throttler.async_throttler import AsyncThrottler

        throttler = web_utils.create_throttler()
        api_factory = web_utils.build_api_factory_without_time_synchronizer_pre_processor(throttler)
        rest_assistant = await api_factory.get_rest_assistant()

        # Try to get symbols (adjust endpoint based on actual Cofinex API)
        response = await rest_assistant.execute_request(
            url=web_utils.public_rest_url("/api/v1/symbols"),
            method=RESTMethod.GET,
            throttler_limit_id="/api/v1/symbols",
        )
        print(f"✅ Symbols response: {response}")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_connection())
```

Run the test:

```bash
python test_cofinex_connection.py
```

### Step 4: Test OAuth Authentication

```python
# test_cofinex_auth.py
import asyncio
from hummingbot.connector.exchange.cofinex.cofinex_auth import CofinexAuth
from hummingbot.connector.exchange.cofinex import cofinex_web_utils as web_utils

async def test_auth():
    """Test OAuth 2.0 authentication"""
    # Use test credentials (don't use real credentials in test scripts!)
    username = "test@example.com"
    password = "test_password"

    # Create auth instance
    auth = CofinexAuth(username=username, password=password)

    # Set API factory for token requests
    throttler = web_utils.create_throttler()
    api_factory = web_utils.build_api_factory_without_time_synchronizer_pre_processor(throttler)
    auth.set_api_factory(api_factory)

    # Test token request
    try:
        access_token = await auth.get_access_token()
        print(f"✅ Access token obtained: {access_token[:20]}...")

        # Test REST authentication
        from hummingbot.core.web_assistant.connections.data_types import RESTRequest
        request = RESTRequest(method="GET", url="https://api.cofinex.com/api/v1/account")
        authenticated_request = await auth.rest_authenticate(request)
        print(f"✅ Authenticated request headers: {authenticated_request.headers}")

    except Exception as e:
        print(f"❌ Authentication error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_auth())
```

## Debugging Tips

### 1. Enable Debug Logging

```python
# In your test script or Hummingbot config
import logging
logging.basicConfig(level=logging.DEBUG)
```

### 2. Check Logs

```bash
# View Hummingbot logs
tail -f logs/logs_hummingbot.log

# Or in Python
import logging
logger = logging.getLogger("hummingbot.connector.exchange.cofinex")
logger.setLevel(logging.DEBUG)
```

### 3. Use Python Debugger

```python
# Add breakpoints in your code
import pdb; pdb.set_trace()

# Or use ipdb (better)
# pip install ipdb
import ipdb; ipdb.set_trace()
```

### 4. Test Individual Components

```python
# test_components.py
import asyncio
from hummingbot.connector.exchange.cofinex import (
    cofinex_constants as CONSTANTS,
    cofinex_web_utils as web_utils,
    cofinex_auth
)

async def test_components():
    print("Testing constants...")
    print(f"Exchange name: {CONSTANTS.EXCHANGE_NAME}")
    print(f"Base URL: {CONSTANTS.BASE_PATH_URL}")

    print("\nTesting web utils...")
    throttler = web_utils.create_throttler()
    print(f"Throttler created: {throttler}")

    print("\nTesting auth...")
    auth = cofinex_auth.CofinexAuth("test", "test")
    print(f"Auth object created: {auth}")

if __name__ == "__main__":
    asyncio.run(test_components())
```

## Common Issues on macOS

### Issue 1: Cython Build Errors

```bash
# Install Xcode Command Line Tools
xcode-select --install

# If you get C++ errors, try:
export CFLAGS="-stdlib=libc++ -std=c++11"
python setup.py build_ext --inplace
```

### Issue 2: Python Path Issues

```bash
# Add to your ~/.zshrc or ~/.bash_profile
export PYTHONPATH="${PYTHONPATH}:${PWD}"

# Or create .env file in project root
echo "PYTHONPATH=${PYTHONPATH}:${PWD}" > .env
```

### Issue 3: Import Errors

```bash
# Make sure you're in the project root
cd ~/hummingbot

# Install in development mode
pip install -e .

# Or add to PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
```

### Issue 4: SSL Certificate Errors

```bash
# Install certificates (if needed)
# /Applications/Python\ 3.12/Install\ Certificates.command

# Or update certificates
conda update certifi
```

## Testing Checklist

- [ ] Code compiles without errors
- [ ] All imports work
- [ ] Constants are properly defined
- [ ] Web utils can create API factory
- [ ] Authentication generates valid signatures
- [ ] Can connect to public API endpoints
- [ ] Can fetch order book (if API available)
- [ ] Can authenticate with OAuth (if username/password available)
- [ ] Paper trading works (once connector is registered)
- [ ] Real trading works (with test amounts only!)

## Next Steps

1. **Get Cofinex Trade Engine API Documentation**
   - Find the actual Trade Engine API base URL
   - Get endpoint paths for orders, balances, etc.
   - Get response formats
   - OAuth 2.0 authentication is already implemented

2. **Update Constants**
   - Replace placeholder Trade Engine API base URL with real one
   - Update endpoint paths with actual Cofinex paths
   - Update rate limits if needed
   - Fix trading pair formats

3. **Complete Implementation**
   - Finish exchange class refactoring
   - Implement order placement
   - Implement balance fetching
   - Add WebSocket support

4. **Test Incrementally**
   - Test each component separately
   - Use paper trading first
   - Test with small amounts if using real API

## Quick Test Commands

```bash
# Quick syntax check
python -m py_compile hummingbot/connector/exchange/cofinex/*.py

# Quick import test
python -c "from hummingbot.connector.exchange.cofinex import cofinex_constants; print('OK')"

# Run all tests
make test

# Start Hummingbot
python bin/hummingbot.py
```

## Using VS Code/Cursor for Debugging

1. **Install Python Extension**
2. **Create `.vscode/launch.json`**:
```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Python: Hummingbot",
            "type": "debugpy",
            "request": "launch",
            "program": "${workspaceFolder}/bin/hummingbot.py",
            "console": "integratedTerminal",
            "env": {
                "PYTHONPATH": "${workspaceFolder}"
            }
        },
        {
            "name": "Python: Test Cofinex",
            "type": "debugpy",
            "request": "launch",
            "program": "${workspaceFolder}/test_cofinex_connection.py",
            "console": "integratedTerminal",
            "env": {
                "PYTHONPATH": "${workspaceFolder}"
            }
        }
    ]
}
```

3. **Set Breakpoints** and debug!

## Resources

- [Hummingbot Installation Docs](https://hummingbot.org/installation/source/)
- [Hummingbot Discord](https://discord.gg/hummingbot)
- [Python Debugging Guide](https://docs.python.org/3/library/pdb.html)

Good luck testing! 🚀
