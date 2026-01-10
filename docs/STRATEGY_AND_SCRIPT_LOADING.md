# Strategy and Script Loading in Hummingbot

This document explains where strategies and scripts are defined in the Hummingbot codebase and how they are discovered and loaded into the CLI.

## Overview

Hummingbot supports **two types of trading strategies**:

1. **Regular Strategies** - Built-in strategies in `hummingbot/strategy/`
2. **Script Strategies** - User-defined Python scripts in `scripts/`

---

## 1. Regular Strategies

### Location

**Directory**: `hummingbot/strategy/`

**Structure**:
```
hummingbot/strategy/
├── pure_market_making/      # Pure Market Making strategy
├── cross_exchange_market_making/
├── avellaneda_market_making/
├── liquidity_mining/
├── spot_perpetual_arbitrage/
└── ...
```

Each strategy is a **directory** containing:
- `start.py` - Strategy initialization function
- `*_config_map.py` - Configuration map (Pydantic model)
- Strategy implementation files

### Discovery

**Function**: `get_strategy_list()` in `hummingbot/__init__.py`

```python
def get_strategy_list() -> List[str]:
    """
    Search `hummingbot.strategy` folder for all available strategies
    Automatically hide all strategies that starts with "dev" if on master branch
    """
    folder = path.realpath(path.join(__file__, "../strategy"))
    # Only include valid directories
    strategies = [d for d in listdir(folder)
                  if path.isdir(path.join(folder, d)) and not d.startswith("__")]
    # Hide dev strategies in production
    if not on_dev_mode:
        strategies = [s for s in strategies if not s.startswith("dev")]
    return sorted(strategies)
```

**How it works**:
1. Scans `hummingbot/strategy/` directory
2. Finds all subdirectories (excluding `__pycache__`, `__utils__`, etc.)
3. Filters out "dev" strategies in production mode
4. Returns sorted list of strategy names

### Loading Process

**Entry Point**: `get_strategy_starter_file()` in `hummingbot/client/config/config_helpers.py`

```python
def get_strategy_starter_file(strategy: str) -> Callable:
    """
    Given the name of a strategy, find and load the `start` function in
    `hummingbot/strategy/{STRATEGY_NAME}/start.py` file.
    """
    strategy_module = __import__(f"hummingbot.strategy.{strategy}.start",
                                 fromlist=[f"hummingbot.strategy.{strategy}"])
    return getattr(strategy_module, "start")
```

**Flow**:
1. User selects strategy (e.g., `pure_market_making`)
2. CLI calls `get_strategy_starter_file("pure_market_making")`
3. Dynamically imports `hummingbot.strategy.pure_market_making.start`
4. Returns the `start()` function
5. `start()` function initializes the strategy

**Example Strategy Structure**:
```
hummingbot/strategy/pure_market_making/
├── __init__.py
├── start.py                    # Contains start(hb_app) function
├── pure_market_making_config_map.py  # Configuration
└── pure_market_making.pyx      # Strategy implementation
```

---

## 2. Script Strategies

### Location

**Directory**: `scripts/` (root level)

**Structure**:
```
scripts/
├── simple_pmm.py              # Simple Pure Market Making script
├── simple_vwap.py
├── simple_xemm.py
├── basic/
│   ├── buy_only_three_times_example.py
│   └── log_price_example.py
├── community/
│   ├── buy_dip_example.py
│   └── triangular_arbitrage.py
└── ...
```

### Discovery

**Settings** (in `hummingbot/client/settings.py`):
```python
SCRIPT_STRATEGIES_MODULE = "scripts"
SCRIPT_STRATEGIES_PATH = root_path() / SCRIPT_STRATEGIES_MODULE
SCRIPT_STRATEGY_CONF_DIR_PATH = CONF_DIR_PATH / "scripts"
```

**Discovery in CLI** (in `hummingbot/client/ui/completer.py`):
```python
def get_strategies_v2_with_config(self):
    file_names = file_name_list(str(SCRIPT_STRATEGIES_PATH), "py")
    strategies_with_config = []

    for script_name in file_names:
        script_name = script_name.replace(".py", "")
        # Dynamically import and inspect the module
        script_module = importlib.import_module(f".{script_name}",
                                                package=SCRIPT_STRATEGIES_MODULE)
        # Find config class (BaseClientModel subclass)
        config_class = next((member for member_name, member in inspect.getmembers(script_module)
                            if issubclass(member, BaseClientModel)))
        if config_class:
            strategies_with_config.append(script_name)

    return WordCompleter(strategies_with_config, ignore_case=True)
```

**How it works**:
1. Scans `scripts/` directory for `.py` files
2. Dynamically imports each script module
3. Inspects for classes that inherit from `ScriptStrategyBase`
4. Finds associated config classes (inherit from `BaseClientModel`)
5. Adds to CLI autocomplete list

### Loading Process

**Entry Point**: `load_script_class()` in `hummingbot/core/trading_core.py`

```python
def load_script_class(self, script_name: str) -> Tuple[Type, Optional[BaseClientModel]]:
    """
    Load script strategy class following Hummingbot's pattern.

    Args:
        script_name: Name of the script strategy (e.g., "simple_pmm")

    Returns:
        Tuple of (strategy_class, config_object)
    """
    # Import the script module
    script_module = importlib.import_module(f".{script_name}",
                                            package=SCRIPT_STRATEGIES_MODULE)

    # Find strategy class (subclass of ScriptStrategyBase)
    script_class = next((member for member_name, member in inspect.getmembers(script_module)
                        if inspect.isclass(member) and
                        issubclass(member, ScriptStrategyBase)))

    # Find config class (subclass of BaseClientModel)
    config_class = next((member for member_name, member in inspect.getmembers(script_module)
                        if issubclass(member, BaseClientModel)))

    # Load config from file if provided
    config_data = self._load_strategy_config()
    config = config_class(**config_data)

    return script_class, config
```

**Flow**:
1. User selects script (e.g., `simple_pmm.py`)
2. CLI calls `load_script_class("simple_pmm")`
3. Dynamically imports `scripts.simple_pmm` module
4. Finds `SimplePMM` class (inherits from `ScriptStrategyBase`)
5. Finds `SimplePMMConfig` class (inherits from `BaseClientModel`)
6. Loads config from YAML file (if exists) or uses defaults
7. Returns strategy class and config instance

### Script Strategy Requirements

A valid script strategy must have:

1. **Strategy Class** - Inherits from `ScriptStrategyBase`:
```python
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase

class MyStrategy(ScriptStrategyBase):
    def __init__(self, connectors: Dict[str, ConnectorBase], config: MyConfig):
        super().__init__(connectors)
        self.config = config

    def on_tick(self):
        # Strategy logic here
        pass
```

2. **Config Class** (Optional) - Inherits from `BaseClientModel`:
```python
from hummingbot.client.config.config_data_types import BaseClientModel

class MyConfig(BaseClientModel):
    exchange: str = "binance"
    trading_pair: str = "BTC-USDT"
    order_amount: Decimal = Decimal("0.01")
```

3. **Markets Declaration** - Class method `init_markets()`:
```python
@classmethod
def init_markets(cls, config: MyConfig):
    cls.markets = {config.exchange: {config.trading_pair}}
```

---

## 3. How Strategies Are Loaded in CLI

### CLI Command Flow

**Command**: `start` or `create`

**Entry Point**: `StartCommand.start()` in `hummingbot/client/command/start_command.py`

### Step-by-Step Loading Process

**Note:** For script strategies (`.py` files), you must use the `--script` parameter: `start --script <filename.py> --conf <config.yml>`. The interactive prompt shown below is for regular strategies only.

#### Step 1: User Input

For regular strategies:
```
>>> start
What is your strategy file name? >>> simple_pmm.py
```

For script strategies:
```
>>> start --script multi_level_self_trading.py --conf conf_multi_level_self_trading.yml
```

#### Step 2: Strategy Type Detection
```python
# In trading_core.py
def detect_strategy_type(self, strategy_name: str) -> StrategyType:
    if strategy_name.endswith(".py") or self.is_script_strategy(strategy_name):
        return StrategyType.SCRIPT
    else:
        return StrategyType.REGULAR
```

#### Step 3: Strategy Initialization

**For Regular Strategies**:
```python
async def _initialize_regular_strategy(self):
    # Get starter function
    start_strategy_func = get_strategy_starter_file(self.strategy_name)

    # Call start function (passes TradingCore instance)
    if asyncio.iscoroutinefunction(start_strategy_func):
        await start_strategy_func(self)
    else:
        start_strategy_func(self)
```

**For Script Strategies**:
```python
async def _initialize_script_strategy(self):
    # Load script class and config
    script_strategy_class, config = self.load_script_class(self.strategy_name)

    # Get markets from script class
    markets_list = []
    for conn, pairs in script_strategy_class.markets.items():
        markets_list.append((conn, list(pairs)))

    # Initialize markets
    await self.initialize_markets(markets_list)

    # Create strategy instance
    if config:
        self.strategy = script_strategy_class(self.markets, config)
    else:
        self.strategy = script_strategy_class(self.markets)
```

#### Step 4: Strategy Execution
```python
async def _start_strategy_execution(self):
    # Start clock (tick system)
    if self.clock is None:
        await self.start_clock()

    # Add strategy to clock (calls on_tick() periodically)
    if self.strategy and self.clock:
        self.clock.add_iterator(self.strategy)

    # Restore market states if needed
    if self.markets_recorder:
        for market in self.markets.values():
            self.markets_recorder.restore_market_states(...)
```

---

## 4. Configuration Files

### Regular Strategies

**Location**: `conf/strategies/`

**Format**: YAML files (e.g., `conf_pure_market_making_strategy.yml`)

**Example**:
```yaml
strategy: pure_market_making
exchange: binance
trading_pair: BTC-USDT
bid_spread: 0.001
ask_spread: 0.001
order_amount: 0.01
```

### Script Strategies

**Location**: `conf/scripts/` (optional)

**Format**: YAML files (e.g., `conf_simple_pmm.yml`)

**Example**:
```yaml
exchange: binance_paper_trade
trading_pair: ETH-USDT
order_amount: 0.01
bid_spread: 0.001
ask_spread: 0.001
```

**Note**: Scripts can also define config inline (using Pydantic defaults) without a YAML file.

---

## 5. CLI Integration

### Autocomplete

**File**: `hummingbot/client/ui/completer.py`

**Regular Strategies**:
```python
def get_strategies(self):
    strategies = get_strategy_list()  # From hummingbot/__init__.py
    return WordCompleter(strategies, ignore_case=True)
```

**Script Strategies**:
```python
def get_strategies_v2_with_config(self):
    file_names = file_name_list(str(SCRIPT_STRATEGIES_PATH), "py")
    # Filter and return script names
    return WordCompleter(strategies_with_config, ignore_case=True)
```

### Command Parsing

**File**: `hummingbot/client/ui/parser.py`

The parser loads command definitions and integrates with autocomplete to provide:
- Strategy name suggestions
- Parameter autocomplete
- Command validation

---

## 6. Quick Reference

### Regular Strategy Structure
```
hummingbot/strategy/{strategy_name}/
├── __init__.py
├── start.py                    # Required: start(hb_app) function
├── {strategy_name}_config_map.py  # Required: Config map
└── {strategy_name}.pyx         # Strategy implementation
```

### Script Strategy Structure
```
scripts/{script_name}.py
├── Config class (BaseClientModel)  # Optional
└── Strategy class (ScriptStrategyBase)  # Required
```

### Configuration Files
```
conf/strategies/conf_{strategy_name}_strategy.yml  # Regular strategies
conf/scripts/conf_{script_name}.yml                # Script strategies (optional)
```

---

## 7. Example: Creating a New Script Strategy

### Step 1: Create Script File
```python
# scripts/my_custom_strategy.py
from decimal import Decimal
from typing import Dict
from hummingbot.client.config.config_data_types import BaseClientModel
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase
from hummingbot.connector.connector_base import ConnectorBase

class MyCustomConfig(BaseClientModel):
    exchange: str = "binance_paper_trade"
    trading_pair: str = "BTC-USDT"
    order_amount: Decimal = Decimal("0.001")

class MyCustomStrategy(ScriptStrategyBase):
    @classmethod
    def init_markets(cls, config: MyCustomConfig):
        cls.markets = {config.exchange: {config.trading_pair}}

    def __init__(self, connectors: Dict[str, ConnectorBase], config: MyCustomConfig):
        super().__init__(connectors)
        self.config = config

    def on_tick(self):
        # Your trading logic here
        pass
```

### Step 2: Use in CLI
```
>>> start
What is your strategy file name? >>> my_custom_strategy.py
```

The CLI will:
1. Discover `my_custom_strategy.py` in `scripts/`
2. Load `MyCustomStrategy` class
3. Load `MyCustomConfig` class
4. Create strategy instance
5. Start execution

---

## 8. Multi-Level Self-Trading Strategy Guide

### Overview

The **Multi-Level Self-Trading Strategy** (`multi_level_self_trading.py`) is a script strategy designed for exchanges that support self-trading (like exchange-core). It places multiple levels of buy and sell orders with Level 1 orders overlapping to enable self-trading.

**Key Features:**
- **7 Order Levels**: Places 7 levels of buy and sell orders
- **Self-Trading**: Level 1 orders overlap, allowing exchange-core to match them automatically
- **Dynamic Price Shift**: Automatically adjusts price shift based on Bitget's 24h price change
- **Auto-Refresh**: Refreshes orders after fills or periodically

### Location

**File**: `scripts/multi_level_self_trading.py`

### Using with Cofinex Paper Trade

#### Step 1: Verify Cofinex Connector

Ensure you have the Cofinex connector configured:

```bash
>>> connect cofinex_paper_trade
```

#### Step 2: Create Configuration File (Optional)

Create a configuration file for easier setup:

**File**: `conf/scripts/conf_multi_level_self_trading.yml`

```yaml
# Multi-Level Self-Trading Strategy Configuration for Cofinex Paper Trade

# Exchange and Trading Pair
exchange: cofinex_paper_trade
trading_pair: CNX-USDT

# Order Settings
order_amount: 0.01              # Order amount per level (in CNX)
order_levels: 7                 # Number of order levels
level_spread: 0.001             # 0.1% spread between levels

# Level 1 Self-Trading Settings
level1_buy_offset: 0.0002       # Buy offset: 0.02% above reference
level1_sell_offset: -0.0002     # Sell offset: 0.02% below reference

# Dynamic Price Shift from Bitget
price_shift_enabled: true
bitget_api_url: "https://api.bitget.com/api/v2/spot/market/tickers"
bitget_symbol: "BTCUSDT"        # Bitget symbol for BTC/USDT (used for price shift calculation)
price_shift_update_interval: 60 # Update every 60 seconds
price_shift_multiplier: 1.0     # Use change24h as-is (can adjust)

# Strategy Settings
order_refresh_time: 30          # Refresh orders every 30s if no fills
filled_order_delay: 2           # Wait 2s after fill before refresh
price_type: "mid"               # Use mid-price as reference
enable_self_trading: true       # Enable Level 1 self-trading
```

#### Step 3: Start the Strategy

There are two ways to start the strategy:

**Method 1: Start Hummingbot First, Then Start Strategy (Recommended for Testing)**

1. Start Hummingbot:
```bash
cd /Users/santoshpadhi/hummingbot
conda activate hummingbot
python bin/hummingbot_quickstart.py
```

2. Once in the Hummingbot CLI, start the strategy:

**Option A: With Configuration File**
```bash
>>> start --script multi_level_self_trading.py --conf conf_multi_level_self_trading.yml
```

**Option B: Without Configuration File (Uses Defaults)**
```bash
>>> start --script multi_level_self_trading.py
```

**Method 2: Start Hummingbot with Strategy Directly (Quick Start)**

Start Hummingbot and the strategy in one command:

**With Configuration File:**
```bash
cd /Users/santoshpadhi/hummingbot
conda activate hummingbot
python bin/hummingbot_quickstart.py -f multi_level_self_trading.py -c conf_multi_level_self_trading.yml
```

**Without Configuration File (Uses Defaults):**
```bash
cd /Users/santoshpadhi/hummingbot
conda activate hummingbot
python bin/hummingbot_quickstart.py -f multi_level_self_trading.py
```

**Note:** If you see the error "Please import or create a strategy" when running `start` without parameters, you need to use the `--script` parameter as shown above.

#### Step 4: Monitor Strategy

Once started, you can monitor the strategy:

```bash
>>> status
```

This will show:
- Active orders (buy and sell orders across 7 levels)
- Current price shift from Bitget
- Fill statistics (total fills, Level 1 fills)
- Order overlap status

### How It Works

#### Order Placement

The strategy places orders in this structure (example with CNX-USDT):

```
Level 1: Buy @ $1.0020, Sell @ $0.9980  (OVERLAP - self-trades)
Level 2: Buy @ $0.9900, Sell @ $1.0100  (0.1% from Level 1)
Level 3: Buy @ $0.9800, Sell @ $1.0200  (0.2% from Level 1)
... (Levels 4-7 continue with 0.1% increments)
```

#### Self-Trading Flow

1. **Order Placement**: Strategy places Level 1 buy and sell orders that overlap
2. **Exchange-Core Matching**: Exchange-core detects overlap and matches orders (self-trade)
3. **Fill Detection**: Strategy detects fill and triggers refresh
4. **Order Refresh**: After 2-second delay, cancels all orders and places new ones
5. **Price Update**: New orders use updated prices based on current market + Bitget shift

#### Dynamic Price Shift

The strategy fetches `change24h` from Bitget API every 60 seconds:

```json
{
  "change24h": 0.00309  // From Bitget API
}
```

**Calculation:**
- `change24h` = 0.00309
- Percentage = 0.00309 × 100 = 0.309%
- Price shift = 0.309% (positive = shift UP, negative = shift DOWN)

**Example:**
- Market mid-price: $1.00 (CNX-USDT)
- Bitget change24h: 0.00309 (0.309% up for BTC)
- Shifted reference: $1.00 × 1.00309 = $1.00309
- All orders placed relative to $1.00309

### Configuration Parameters Explained

#### Order Settings

- **`order_amount`**: Amount per level (e.g., 0.01 CNX)
- **`order_levels`**: Number of levels (default: 7)
- **`level_spread`**: Spread between levels (0.001 = 0.1%)

#### Level 1 Self-Trading

- **`level1_buy_offset`**: Buy price offset (positive = above reference)
- **`level1_sell_offset`**: Sell price offset (negative = below reference)
- **`enable_self_trading`**: Enable/disable Level 1 overlap

#### Dynamic Price Shift

- **`price_shift_enabled`**: Enable dynamic shift from Bitget
- **`bitget_symbol`**: Symbol to fetch from Bitget for price shift (e.g., "BTCUSDT" - note: this is for shift calculation, trading pair is CNX-USDT)
- **`price_shift_update_interval`**: How often to fetch from Bitget (seconds)
- **`price_shift_multiplier`**: Multiplier for shift (1.0 = use as-is, 2.0 = double it)

#### Strategy Timers

- **`order_refresh_time`**: Periodic refresh interval (seconds)
- **`filled_order_delay`**: Delay after fill before refresh (seconds)

### Troubleshooting

#### Issue: Orders Not Placing

**Check:**
1. Verify connector is connected: `>>> status`
2. Check balances: Ensure sufficient balance for orders
3. Check logs: Look for error messages in logs

#### Issue: Self-Trading Not Working

**Check:**
1. Verify `enable_self_trading: true` in config
2. Check Level 1 overlap: Use `status` command to see if orders overlap
3. Verify exchange supports self-trading (exchange-core does)

#### Issue: Bitget API Not Updating

**Check:**
1. Internet connection: Strategy needs to reach Bitget API
2. API URL: Verify `bitget_api_url` is correct
3. Symbol: Verify `bitget_symbol` matches Bitget format (e.g., "BTCUSDT")
4. Check logs: Look for API error messages

#### Issue: Orders Refreshing Too Frequently

**Adjust:**
- Increase `order_refresh_time` (e.g., 60 seconds)
- Increase `filled_order_delay` (e.g., 5 seconds)

### Example Session

```bash
# Start Hummingbot
>>> start

# Connect to Cofinex Paper Trade
>>> connect cofinex_paper_trade
# Follow prompts to configure

# Start strategy (use --script parameter for script strategies)
>>> start --script multi_level_self_trading.py --conf conf_multi_level_self_trading.yml

# Monitor strategy
>>> status

# Check active orders
>>> active-orders

# View logs
>>> logs
```

### Expected Behavior

1. **Initial Placement**: Strategy places 14 orders (7 buy + 7 sell)
2. **Level 1 Self-Trade**: Exchange-core matches Level 1 orders (if overlap)
3. **Fill Detection**: Strategy detects fill and logs it
4. **Refresh**: After 2 seconds, cancels all and places new orders
5. **Price Update**: New orders use updated prices (market + Bitget shift)
6. **Periodic Refresh**: If no fills, refreshes every 30 seconds

### Performance Tips

1. **Start Small**: Use small `order_amount` (0.01) for testing
2. **Monitor Fills**: Watch Level 1 fills to verify self-trading
3. **Adjust Spread**: Increase `level_spread` if orders fill too quickly
4. **Bitget Updates**: Adjust `price_shift_update_interval` based on needs
5. **Refresh Timing**: Balance `order_refresh_time` and `filled_order_delay`

---

## Summary

| Type | Location | Discovery | Loading |
|------|----------|-----------|---------|
| **Regular Strategy** | `hummingbot/strategy/{name}/` | `get_strategy_list()` | `get_strategy_starter_file()` → `start()` |
| **Script Strategy** | `scripts/{name}.py` | File scan + import | `load_script_class()` → Dynamic import |

Both types are automatically discovered and made available in the CLI through:
- **Autocomplete**: Strategy names appear in CLI suggestions
- **Dynamic Loading**: Strategies are imported at runtime
- **Configuration**: YAML config files or inline Pydantic models
