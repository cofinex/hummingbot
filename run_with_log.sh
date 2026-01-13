#!/bin/bash
# Script to run Hummingbot and capture console output to a file
# Usage: ./run_with_log.sh

LOG_FILE="console_output_$(date +%Y%m%d_%H%M%S).log"

echo "Starting Hummingbot..."
echo "Console output will be saved to: $LOG_FILE"
echo "Press Ctrl+C to stop"
echo ""

# Change to hummingbot directory
cd /Users/santoshpadhi/hummingbot || exit 1

# Activate conda environment
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate hummingbot

# Run Hummingbot and capture all output (stdout and stderr) using tee
# This allows you to see output on screen AND save it to a file
python bin/hummingbot_quickstart.py 2>&1 | tee "$LOG_FILE"
