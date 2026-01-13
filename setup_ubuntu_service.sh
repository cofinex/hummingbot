#!/bin/bash
# Quick setup script for Hummingbot systemd service on Ubuntu
# Usage: ./setup_ubuntu_service.sh

set -e

echo "=========================================="
echo "Hummingbot Systemd Service Setup"
echo "=========================================="
echo ""

# Get current user
CURRENT_USER=$(whoami)
echo "Current user: $CURRENT_USER"

# Find conda installation
if [ -d "$HOME/anaconda3" ]; then
    CONDA_PATH="$HOME/anaconda3"
elif [ -d "$HOME/miniconda3" ]; then
    CONDA_PATH="$HOME/miniconda3"
else
    echo "Error: Could not find conda installation in $HOME/anaconda3 or $HOME/miniconda3"
    echo "Please specify your conda path:"
    read -p "Conda path: " CONDA_PATH
fi

echo "Conda path: $CONDA_PATH"

# Get Hummingbot directory
if [ -f "bin/hummingbot_quickstart.py" ]; then
    HB_DIR=$(pwd)
    echo "Found Hummingbot in: $HB_DIR"
else
    echo "Please specify your Hummingbot directory:"
    read -p "Hummingbot path: " HB_DIR
    if [ ! -f "$HB_DIR/bin/hummingbot_quickstart.py" ]; then
        echo "Error: Could not find bin/hummingbot_quickstart.py in $HB_DIR"
        exit 1
    fi
fi

# Get strategy file
echo ""
echo "Strategy file (leave empty for interactive mode):"
read -p "Strategy file (e.g., multi_level_self_trading.py): " STRATEGY_FILE

# Get config file
if [ ! -z "$STRATEGY_FILE" ]; then
    echo "Config file:"
    read -p "Config file (e.g., conf/scripts/conf_multi_level_self_trading.yml): " CONFIG_FILE
fi

# Build command
if [ ! -z "$STRATEGY_FILE" ] && [ ! -z "$CONFIG_FILE" ]; then
    CMD="$CONDA_PATH/bin/conda run -n hummingbot python bin/hummingbot_quickstart.py -f $STRATEGY_FILE -c $CONFIG_FILE"
else
    CMD="$CONDA_PATH/bin/conda run -n hummingbot python bin/hummingbot_quickstart.py"
fi

# Create service file
SERVICE_FILE="/tmp/hummingbot.service"
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Hummingbot Trading Bot
Documentation=https://docs.hummingbot.org/
After=network.target
Wants=network.target

[Service]
Type=simple
User=$CURRENT_USER
Group=$CURRENT_USER
WorkingDirectory=$HB_DIR
Environment="PATH=$CONDA_PATH/bin:/usr/local/bin:/usr/bin:/bin"
Environment="CONDA_DEFAULT_ENV=hummingbot"
ExecStart=$CMD
ExecStop=/bin/kill -TERM \$MAINPID
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=hummingbot
NoNewPrivileges=true
PrivateTmp=true
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF

echo ""
echo "Service file created at: $SERVICE_FILE"
echo ""
echo "Service configuration:"
echo "  User: $CURRENT_USER"
echo "  Working Directory: $HB_DIR"
echo "  Conda Path: $CONDA_PATH"
if [ ! -z "$STRATEGY_FILE" ]; then
    echo "  Strategy: $STRATEGY_FILE"
    echo "  Config: $CONFIG_FILE"
else
    echo "  Mode: Interactive (no auto-start strategy)"
fi
echo ""
read -p "Install this service? (y/n): " INSTALL

if [ "$INSTALL" != "y" ] && [ "$INSTALL" != "Y" ]; then
    echo "Installation cancelled."
    echo "Service file saved at: $SERVICE_FILE"
    echo "You can review and install it manually later."
    exit 0
fi

# Copy service file
echo "Copying service file to /etc/systemd/system/..."
sudo cp "$SERVICE_FILE" /etc/systemd/system/hummingbot.service

# Reload systemd
echo "Reloading systemd..."
sudo systemctl daemon-reload

# Test the service
echo ""
echo "Testing service configuration..."
sudo systemctl show hummingbot | grep -E "(User|WorkingDirectory|ExecStart)" || true

echo ""
echo "=========================================="
echo "Service installed successfully!"
echo "=========================================="
echo ""
echo "Useful commands:"
echo "  Start service:    sudo systemctl start hummingbot"
echo "  Stop service:     sudo systemctl stop hummingbot"
echo "  Restart service:  sudo systemctl restart hummingbot"
echo "  View status:      sudo systemctl status hummingbot"
echo "  View logs:        sudo journalctl -u hummingbot -f"
echo "  Enable on boot:   sudo systemctl enable hummingbot"
echo "  Disable on boot:  sudo systemctl disable hummingbot"
echo ""
read -p "Start the service now? (y/n): " START_NOW

if [ "$START_NOW" == "y" ] || [ "$START_NOW" == "Y" ]; then
    echo "Starting service..."
    sudo systemctl start hummingbot
    sleep 2
    sudo systemctl status hummingbot
    echo ""
    echo "Service started! View logs with: sudo journalctl -u hummingbot -f"
fi

echo ""
read -p "Enable service to start on boot? (y/n): " ENABLE_BOOT

if [ "$ENABLE_BOOT" == "y" ] || [ "$ENABLE_BOOT" == "Y" ]; then
    sudo systemctl enable hummingbot
    echo "Service enabled to start on boot."
fi

echo ""
echo "Setup complete!"
