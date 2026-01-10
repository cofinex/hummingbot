# Hummingbot Documentation

This directory contains organized documentation for the Hummingbot project.

## Directory Structure

### `/cofinex/`
Cofinex exchange connector documentation:
- **COFINEX_CONNECTOR_ANALYSIS.md** - Analysis of the Cofinex connector implementation
- **COFINEX_IMPLEMENTATION_PROGRESS.md** - Current implementation status and progress
- **COFINEX_LOCAL_TESTING_GUIDE.md** - Guide for local testing of the Cofinex connector
- **COFINEX_OAUTH_IMPLEMENTATION.md** - OAuth 2.0 authentication implementation details
- **COFINEX_PENDING_REST_APIS.md** - List of pending REST API implementations
- **COFINEX_REST_ONLY_APPROACH.md** - REST-only implementation approach documentation
- **COFINEX_TESTING_GUIDE.md** - Testing guide for the Cofinex connector

### `/strategies/`
Trading strategy documentation:
- **SUI_MARKET_MAKING_README.md** - SUI market making strategy documentation

### `/setup/`
Setup and development guides:
- **CURSOR_VSCODE_SETUP.md** - Setup guide for Cursor/VSCode development environment

### `/transcripts/`
AI conversation transcripts:
- **cursor_humming_bot_v2_code.md** - Transcript of AI-assisted development session

## Core Documentation

### Strategy and Script Loading
- **STRATEGY_AND_SCRIPT_LOADING.md** - Comprehensive guide explaining:
  - Where strategies are defined (`hummingbot/strategy/`)
  - Where scripts are defined (`scripts/`)
  - How strategies/scripts are discovered
  - How they are loaded into the CLI
  - How to create custom script strategies

### Strategy Capabilities
- **CROSS_TRADE_STRATEGIES.md** - Guide explaining:
  - Whether strategies can match the bot's own orders
  - Limitations of Pure Market Making
  - Self-trading prevention mechanisms
  - Workarounds and custom solutions
  - Comparison of different strategy types
- **OPTION_4_INTERNAL_MATCHING.md** - Detailed guide for Option 4:
  - How exchange-core supports self-trading
  - Implementation and configuration
  - Fee handling and balance management
  - Best practices and troubleshooting
  - Using Hummingbot with exchange-core for self-trading
- **STRATEGY_OPERATION_AND_OPTIMIZATION.md** - Comprehensive guide for Multi-Level Self-Trading Strategy:
  - Strategy overview and timing mechanisms
  - Balanced configuration recommendations
  - Price movement and drift analysis (best/worst/realistic scenarios)
  - Refresh triggers (fill-based, Bitget shift change, periodic)
  - Complete timing examples with balanced settings
  - Configuration guide and troubleshooting

## Quick Links

- [Cofinex Connector Documentation](./cofinex/)
- [Trading Strategies](./strategies/)
- [Setup Guides](./setup/)
- [Development Transcripts](./transcripts/)
- [Strategy and Script Loading Guide](./STRATEGY_AND_SCRIPT_LOADING.md)
