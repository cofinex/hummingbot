# Setting Up Hummingbot as a Systemd Service on Ubuntu

This guide will help you run Hummingbot as a background service on Ubuntu that starts automatically on boot and restarts on failure.

## Prerequisites

1. Ubuntu 18.04 or later
2. Root/sudo access
3. Git installed
4. Conda (Anaconda or Miniconda) installed
5. Clipboard utilities (for copy-paste in Hummingbot GUI)

## Step 0: Initial Setup

### Install Prerequisites

If you don't have the required tools installed:

```bash
# Update package list
sudo apt update

# Install Git (if not already installed)
sudo apt install -y git

# Install clipboard utilities (required for copy-paste in Hummingbot GUI)
sudo apt install -y xclip xsel
# Note: If running on a server without X11, you may need to use SSH with X11 forwarding
# or use alternative methods like Shift+Insert for paste

# Install Conda (if not already installed)
# Option 1: Install Miniconda (recommended, smaller)
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh
# Follow the installation prompts
# IMPORTANT: When asked "Do you wish the installer to initialize Miniconda3?", answer YES
# This will automatically add conda to your PATH

# Option 2: Install Anaconda (full distribution)
wget https://repo.anaconda.com/archive/Anaconda3-2024.02-1-Linux-x86_64.sh
bash Anaconda3-2024.02-1-Linux-x86_64.sh
# Follow the installation prompts
# IMPORTANT: When asked "Do you wish the installer to initialize Anaconda3?", answer YES

# After installation, close and reopen your terminal, or run:
source ~/.bashrc
# or if using zsh:
source ~/.zshrc

# Verify conda is installed
conda --version
```

### Checkout Code from Git Repository

1. **Navigate to your desired installation directory:**
   ```bash
   cd ~
   # or
   cd /opt  # if you prefer system-wide installation
   ```

2. **Clone the Hummingbot repository:**
   ```bash
   # If using SSH (recommended if you have SSH keys set up)
   git clone git@github.com:YOUR_USERNAME/hummingbot.git
   # or
   git clone git@github.com:YOUR_ORG/hummingbot.git

   # If using HTTPS
   git clone https://github.com/YOUR_USERNAME/hummingbot.git
   # or
   git clone https://github.com/YOUR_ORG/hummingbot.git

   # Navigate into the directory
   cd hummingbot
   ```

3. **Checkout the desired branch (if not using main/master):**
   ```bash
   # List available branches
   git branch -a

   # Checkout a specific branch (e.g., your feature branch)
   git checkout santosh/cofinex-exchange-bot
   # or
   git checkout main
   ```

### Set Up Conda Environment

1. **If conda command is not found, initialize it:**
   ```bash
   # Find your conda installation (usually in ~/miniconda3 or ~/anaconda3)
   ls -la ~ | grep -E "conda|anaconda|miniconda"

   # Initialize conda for your shell
   # For bash:
   ~/miniconda3/bin/conda init bash
   # or
   ~/anaconda3/bin/conda init bash

   # For zsh:
   ~/miniconda3/bin/conda init zsh
   # or
   ~/anaconda3/bin/conda init zsh

   # Reload your shell configuration
   source ~/.bashrc
   # or
   source ~/.zshrc

   # Verify conda is now available
   conda --version
   ```

2. **Create the conda environment:**
   ```bash
   # Navigate to the hummingbot directory
   cd ~/hummingbot  # or wherever you cloned it

   # Create conda environment (if it doesn't exist)
   conda create -n hummingbot python=3.12 -y
   ```

3. **Activate the environment:**
   ```bash
   conda activate hummingbot
   ```

4. **Verify you're using the conda environment's Python and pip:**
   ```bash
   # Check Python location (should be in conda environment)
   which python
   # Should show: /home/YOUR_USERNAME/miniconda3/envs/hummingbot/bin/python
   # or: /home/YOUR_USERNAME/anaconda3/envs/hummingbot/bin/python

   # Check pip location (should be in conda environment)
   which pip
   # Should show: /home/YOUR_USERNAME/miniconda3/envs/hummingbot/bin/pip
   # or: /home/YOUR_USERNAME/anaconda3/envs/hummingbot/bin/pip

   # If pip shows /usr/bin/pip, use python -m pip instead (recommended):
   python -m pip --version
   # This will always use the conda environment's pip
   ```

5. **Install dependencies:**
   ```bash
   # RECOMMENDED: Use python -m pip instead of just pip
   # This ensures you're using the conda environment's pip
   # The -e flag installs in editable mode and installs all dependencies from setup.py
   python -m pip install -e .

   # This may take several minutes as it installs all dependencies
   # If you see any errors, note them down for troubleshooting

   # If you get missing module errors, you may need to install build dependencies first:
   # sudo apt update && sudo apt install -y build-essential python3-dev
   ```

6. **Verify installation:**
   ```bash
   # Check Python version
   python --version

   # Test that Hummingbot can be imported
   python -c "import hummingbot; print('Hummingbot installed successfully')"

   # Test that the quickstart script runs (it should show help or version)
   python bin/hummingbot_quickstart.py --help
   ```

### Configure Hummingbot

1. **Run Hummingbot setup (if needed):**
   ```bash
   # This will create necessary directories and config files
   python bin/hummingbot_quickstart.py
   ```

2. **Configure your exchange and strategy:**
   - Edit config files in `conf/` directory
   - Set up API keys in `conf/connectors/`
   - Configure your strategy in `conf/scripts/`

3. **Test that Hummingbot runs:**
   ```bash
   # Test with a simple command
   python bin/hummingbot_quickstart.py --help
   ```

## Step 1: Find Your Paths

First, identify the following paths on your system:

```bash
# Find your username
whoami

# Find conda installation path
which conda
# or
conda info --base

# Find Hummingbot installation path
pwd  # if you're in the hummingbot directory
```

## Step 2: Edit the Service File

1. Copy the service file template:
```bash
sudo cp hummingbot.service /etc/systemd/system/hummingbot.service
```

2. Edit the service file with your actual paths:
```bash
sudo nano /etc/systemd/system/hummingbot.service
```

3. Replace the following placeholders:
   - `YOUR_USERNAME` → Your Ubuntu username
   - `/home/YOUR_USERNAME/hummingbot` → Full path to your Hummingbot directory
   - `/home/YOUR_USERNAME/anaconda3` → Your conda installation path (could be `miniconda3`)
   - `multi_level_self_trading.py` → Your strategy file name (if different)
   - `conf/scripts/conf_multi_level_self_trading.yml` → Your config file path (if different)

4. **Important**: Choose one of the ExecStart options:
   - **Option 1** (Recommended): Uses `conda run` - simpler and more reliable
   - **Option 2**: Uses `conda activate` - alternative if Option 1 doesn't work

## Step 3: Test the Service Command

Before enabling the service, test that the command works manually:

```bash
# Test Option 1 (with --headless flag - required for non-interactive execution)
/home/YOUR_USERNAME/anaconda3/bin/conda run -n hummingbot python bin/hummingbot_quickstart.py --headless -f multi_level_self_trading.py -c conf/scripts/conf_multi_level_self_trading.yml

# Or if you have a config password set:
/home/YOUR_USERNAME/anaconda3/bin/conda run -n hummingbot python bin/hummingbot_quickstart.py --headless -p "your_password" -f multi_level_self_trading.py -c conf/scripts/conf_multi_level_self_trading.yml

# Or test Option 2
source /home/YOUR_USERNAME/anaconda3/etc/profile.d/conda.sh && conda activate hummingbot && python bin/hummingbot_quickstart.py --headless -f multi_level_self_trading.py -c conf/scripts/conf_multi_level_self_trading.yml
```

**Important Notes:**
- The `--headless` flag is **required** when running as a service (no interactive terminal)
  - Without it, you'll get `EOFError` because the login prompt requires a terminal
- When using `-f` and `-c` flags, the strategy **automatically connects** to the exchange specified in the config file
  - No manual `connect` command needed - the strategy's `init_markets` method handles this
- **For live trading** (`exchange: cofinex`):
  - Credentials must be configured in `conf/connectors/cofinex.yml` (username and password)
  - The credentials are encrypted and stored securely
  - The strategy will automatically use these credentials when connecting
- **For paper trading** (`exchange: cofinex_paper_trade`):
  - No credentials needed - paper trading is simulated
  - Make sure your config file has `exchange: cofinex_paper_trade`
- The exchange connection happens automatically when the strategy starts via `initialize_markets()`

If the command works, press Ctrl+C to stop it.

## Step 4: Reload Systemd and Start the Service

```bash
# Reload systemd to recognize the new service
sudo systemctl daemon-reload

# Start the service
sudo systemctl start hummingbot

# Check status
sudo systemctl status hummingbot

# Enable service to start on boot
sudo systemctl enable hummingbot
```

## Step 5: Useful Commands

### View Service Status
```bash
sudo systemctl status hummingbot
```

### View Logs
```bash
# View recent logs
sudo journalctl -u hummingbot -n 50

# Follow logs in real-time
sudo journalctl -u hummingbot -f

# View logs from today
sudo journalctl -u hummingbot --since today

# View logs from a specific time
sudo journalctl -u hummingbot --since "2026-01-13 10:00:00"
```

### Control the Service
```bash
# Start
sudo systemctl start hummingbot

# Stop
sudo systemctl stop hummingbot

# Restart
sudo systemctl restart hummingbot

# Disable auto-start on boot
sudo systemctl disable hummingbot

# Enable auto-start on boot
sudo systemctl enable hummingbot
```

## Step 6: Running Without a Strategy File

If you want to run Hummingbot interactively (without auto-starting a strategy), modify the ExecStart line:

```ini
# For interactive mode (you'll need to manually start strategies)
ExecStart=/home/YOUR_USERNAME/anaconda3/bin/conda run -n hummingbot python bin/hummingbot_quickstart.py

# Or with a config password
ExecStart=/home/YOUR_USERNAME/anaconda3/bin/conda run -n hummingbot python bin/hummingbot_quickstart.py -p "your_password"
```

## Troubleshooting

### Externally-Managed-Environment Error

If you see `error: externally-managed-environment` when running `pip install`, this means pip is using the system Python instead of the conda environment's Python.

**Solution (Recommended):**

**Use `python -m pip` instead of just `pip`** - This always uses the conda environment's pip:

```bash
# Make sure you're in the conda environment
conda activate hummingbot

# Use python -m pip instead of pip
python -m pip install -e .

# Or for requirements.txt
python -m pip install -r requirements.txt
```

**Alternative Solutions:**

1. **If `which pip` shows `/usr/bin/pip` even after `conda install pip`:**
   ```bash
   # Check if pip exists in conda environment
   ls -la ~/anaconda3/envs/hummingbot/bin/pip
   # or
   ls -la ~/miniconda3/envs/hummingbot/bin/pip

   # Use the full path to conda's pip
   ~/anaconda3/envs/hummingbot/bin/pip install -e .
   ```

2. **Fix PATH to prioritize conda's bin directory:**
   ```bash
   # Add to ~/.bashrc (or ~/.zshrc)
   export PATH="$HOME/anaconda3/envs/hummingbot/bin:$PATH"
   # or
   export PATH="$HOME/miniconda3/envs/hummingbot/bin:$PATH"

   # Reload shell
   source ~/.bashrc
   # or
   source ~/.zshrc

   # Verify
   which pip
   ```

3. **Reinstall pip in conda environment:**
   ```bash
   conda install pip setuptools wheel -y
   # Then use: python -m pip install -e .
   ```

### Missing Module Errors (e.g., ModuleNotFoundError: No module named 'ptpython')

If you see errors like `ModuleNotFoundError: No module named 'ptpython'` or other missing modules:

1. **First, ensure installation completed successfully:**
   ```bash
   # Make sure you're in the conda environment
   conda activate hummingbot

   # Reinstall in editable mode (this installs all dependencies from setup.py)
   python -m pip install -e . --force-reinstall --no-cache-dir
   ```

2. **If specific modules are still missing, install them manually:**
   ```bash
   # Install missing modules individually
   python -m pip install ptpython

   # Or install common missing dependencies
   python -m pip install ptpython ipython prompt-toolkit
   ```

3. **Check if installation was successful:**
   ```bash
   # Test imports
   python -c "import ptpython; print('ptpython installed')"
   python -c "import hummingbot; print('hummingbot installed')"

   # Test quickstart
   python bin/hummingbot_quickstart.py --help
   ```

4. **If installation keeps failing, check for build dependencies:**
   ```bash
   # Install build tools
   sudo apt update
   sudo apt install -y build-essential python3-dev

   # Then retry installation
   python -m pip install -e .
   ```

### Paper Trade Connector Not Showing

If you don't see `cofinex_paper_trade` in the list of available connectors:

1. **Verify `cofinex` is in the paper_trade_exchanges list:**
   ```bash
   # Check the config file
   grep -A 5 "paper_trade_exchanges" conf/conf_client.yml
   # Should show 'cofinex' in the list
   ```

2. **Restart Hummingbot** - Paper trade connectors are initialized when Hummingbot starts:
   ```bash
   # Exit Hummingbot if running
   # Then restart it
   python bin/hummingbot_quickstart.py
   ```

3. **Check available connectors:**
   ```bash
   # In Hummingbot CLI, type:
   connect
   # This will show all available connectors, including paper trade ones
   ```

4. **Connect to paper trade directly:**
   ```bash
   # In Hummingbot CLI, type:
   connect cofinex_paper_trade
   # This should work even if it doesn't show in the list
   ```

5. **Verify paper trade connector is registered:**
   ```bash
   # Run the discovery test script
   python test_cofinex_discovery.py
   # This will show if cofinex_paper_trade is available
   ```

6. **If still not working, manually add to config:**
   ```yaml
   # Edit conf/conf_client.yml
   paper_trade:
     paper_trade_exchanges:
     - binance
     - kucoin
     - kraken
     - gate_io
     - cofinex  # Make sure this line exists
   ```

### Copy-Paste Not Working in Hummingbot GUI

If copy-paste (Ctrl+C/Ctrl+V) doesn't work in the Hummingbot GUI:

**Solution 1: Install Clipboard Utilities (Recommended)**

```bash
# Install xclip (most common)
sudo apt update
sudo apt install -y xclip

# Or install xsel (alternative)
sudo apt install -y xsel

# Verify installation
which xclip
# or
which xsel
```

**Solution 2: Use Alternative Paste Methods**

On Linux terminals, you can use:
- **Shift+Insert** - Standard Linux terminal paste (works in most terminals)
- **Middle mouse button click** - Paste from primary selection (X11)
- **Right-click → Paste** - If your terminal supports it

**Solution 3: For SSH Sessions**

If you're connecting via SSH and copy-paste doesn't work:

1. **Enable X11 forwarding:**
   ```bash
   # Connect with X11 forwarding
   ssh -X username@server
   # or
   ssh -Y username@server
   ```

2. **Install xclip on the server:**
   ```bash
   sudo apt install -y xclip
   ```

3. **Test clipboard:**
   ```bash
   echo "test" | xclip -selection clipboard
   xclip -selection clipboard -o
   ```

**Solution 4: Use Headless Mode**

If GUI copy-paste continues to be problematic, you can run Hummingbot in headless mode and control it via MQTT or API:

```bash
python bin/hummingbot_quickstart.py --headless
```

**Note:** Hummingbot uses `pyperclip` which requires `xclip` or `xsel` on Linux. Without these, clipboard operations won't work, but you can still use **Shift+Insert** or **middle mouse button** to paste.

### Conda Command Not Found

If you see `conda: command not found`, follow these steps:

1. **Find your conda installation:**
   ```bash
   # Check common locations
   ls -la ~/miniconda3/bin/conda
   ls -la ~/anaconda3/bin/conda
   ls -la /opt/conda/bin/conda
   ```

2. **Initialize conda for your shell:**
   ```bash
   # Replace ~/miniconda3 with your actual conda path
   ~/miniconda3/bin/conda init bash
   # or for zsh:
   ~/miniconda3/bin/conda init zsh
   ```

3. **Reload your shell:**
   ```bash
   source ~/.bashrc
   # or
   source ~/.zshrc
   ```

4. **Alternative: Add conda to PATH manually:**
   ```bash
   # Add to ~/.bashrc or ~/.zshrc
   export PATH="$HOME/miniconda3/bin:$PATH"
   # or
   export PATH="$HOME/anaconda3/bin:$PATH"

   # Then reload
   source ~/.bashrc
   ```

5. **Verify conda works:**
   ```bash
   conda --version
   conda info
   ```

### Service Fails to Start

1. **Check the service status:**
   ```bash
   sudo systemctl status hummingbot
   ```

2. **Check logs for errors:**
   ```bash
   sudo journalctl -u hummingbot -n 100
   ```

3. **Common issues:**
   - **Wrong paths**: Verify all paths in the service file are correct
   - **Conda not found**: Check conda installation path
   - **Permission issues**: Ensure the user has access to all directories
   - **Strategy file not found**: Verify the strategy file path

### Service Runs But Bot Doesn't Start

1. **Check if conda environment is correct:**
   ```bash
   conda env list
   ```

2. **Test the command manually** (see Step 3)

3. **Check Hummingbot logs:**
   ```bash
   tail -f /home/YOUR_USERNAME/hummingbot/logs/logs_conf_multi_level_self_trading.log
   ```

### Permission Denied Errors

If you see permission errors, you may need to:

1. **Fix file permissions:**
   ```bash
   sudo chown -R YOUR_USERNAME:YOUR_USERNAME /home/YOUR_USERNAME/hummingbot
   ```

2. **Ensure user can access conda:**
   ```bash
   sudo chown -R YOUR_USERNAME:YOUR_USERNAME /home/YOUR_USERNAME/anaconda3
   ```

### Service Keeps Restarting

If the service keeps restarting, it means Hummingbot is crashing. Check logs:

```bash
sudo journalctl -u hummingbot -n 200 --no-pager
```

Look for error messages and fix the underlying issue.

## Advanced Configuration

### Running Multiple Instances

To run multiple Hummingbot instances, create additional service files:

```bash
sudo cp /etc/systemd/system/hummingbot.service /etc/systemd/system/hummingbot-strategy2.service
```

Then edit the new file to use different:
- Working directories
- Strategy files
- Config files
- Service names

### Environment Variables

Create an environment file:

```bash
nano /home/YOUR_USERNAME/hummingbot/.env
```

Add variables:
```
CONFIG_PASSWORD=your_password
LOG_LEVEL=INFO
```

Then uncomment the `EnvironmentFile` line in the service file.

### Resource Limits

You can add resource limits to the service file:

```ini
# Memory limit (e.g., 2GB)
MemoryLimit=2G

# CPU limit (e.g., 50% of one CPU)
CPUQuota=50%
```

## Security Considerations

1. **Run as non-root user**: The service file uses `User=YOUR_USERNAME` to run as a regular user
2. **File permissions**: Ensure only the user can read/write sensitive config files
3. **API keys**: Store API keys securely in config files with proper permissions (600)

## Example Complete Service File

Here's an example with all paths filled in (replace with your actual values):

```ini
[Unit]
Description=Hummingbot Trading Bot
After=network.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/hummingbot
Environment="PATH=/home/ubuntu/anaconda3/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/home/ubuntu/anaconda3/bin/conda run -n hummingbot python bin/hummingbot_quickstart.py -f multi_level_self_trading.py -c conf/scripts/conf_multi_level_self_trading.yml
ExecStop=/bin/kill -TERM $MAINPID
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=hummingbot

[Install]
WantedBy=multi-user.target
```

## Support

For issues specific to Hummingbot, check:
- Hummingbot documentation: https://docs.hummingbot.org/
- Hummingbot Discord: https://discord.gg/hummingbot
- GitHub Issues: https://github.com/hummingbot/hummingbot/issues
