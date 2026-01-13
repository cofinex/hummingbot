# Setting Up Hummingbot as a Systemd Service on Ubuntu

This guide will help you run Hummingbot as a background service on Ubuntu that starts automatically on boot and restarts on failure.

## Prerequisites

1. Ubuntu 18.04 or later
2. Hummingbot installed and configured
3. Conda environment set up with `hummingbot` environment
4. Root/sudo access

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
# Test Option 1
/home/YOUR_USERNAME/anaconda3/bin/conda run -n hummingbot python bin/hummingbot_quickstart.py -f multi_level_self_trading.py -c conf/scripts/conf_multi_level_self_trading.yml

# Or test Option 2
source /home/YOUR_USERNAME/anaconda3/etc/profile.d/conda.sh && conda activate hummingbot && python bin/hummingbot_quickstart.py -f multi_level_self_trading.py -c conf/scripts/conf_multi_level_self_trading.yml
```

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
