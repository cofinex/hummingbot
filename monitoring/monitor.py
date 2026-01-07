#!/usr/bin/env python3
"""
MQTT Monitor for Hummingbot
Monitors MQTT messages and provides dashboard/alerting
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict

import paho.mqtt.client as mqtt
import requests

# Configuration
MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
MQTT_NAMESPACE = os.getenv("MQTT_NAMESPACE", "hbot")

# CloudWatch configuration
CLOUDWATCH_ENABLED = os.getenv("CLOUDWATCH_ENABLED", "false").lower() == "true"
CLOUDWATCH_NAMESPACE = os.getenv("CLOUDWATCH_NAMESPACE", "Hummingbot/Monitoring")

# Slack configuration
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class BotStatus:
    instance_id: str
    status: str
    strategy: str = None
    last_seen: datetime = None
    trades_count: int = 0
    pnl: float = 0.0
    errors: list = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class MQTTMonitor:
    def __init__(self):
        self.client = mqtt.Client()
        self.bots: Dict[str, BotStatus] = {}
        self.setup_mqtt()
        self.setup_cloudwatch()

    def setup_mqtt(self):
        """Setup MQTT client"""
        self.client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect

    def setup_cloudwatch(self):
        """Setup CloudWatch client if enabled"""
        if CLOUDWATCH_ENABLED:
            try:
                import boto3
                self.cloudwatch = boto3.client('cloudwatch')
                logger.info("CloudWatch client initialized")
            except ImportError:
                logger.warning("boto3 not available, CloudWatch disabled")
                self.cloudwatch = None
        else:
            self.cloudwatch = None

    def on_connect(self, client, userdata, flags, rc):
        """MQTT connection callback"""
        if rc == 0:
            logger.info("Connected to MQTT broker")
            # Subscribe to all bot topics
            self.client.subscribe(f"{MQTT_NAMESPACE}/+/commands/+")
            self.client.subscribe(f"{MQTT_NAMESPACE}/+/events/+")
            self.client.subscribe(f"{MQTT_NAMESPACE}/+/logs/+")
            self.client.subscribe(f"{MQTT_NAMESPACE}/+/notify/+")
            self.client.subscribe(f"{MQTT_NAMESPACE}/+/status_updates/+")
            self.client.subscribe(f"{MQTT_NAMESPACE}/+/hb/+")
        else:
            logger.error(f"Failed to connect to MQTT broker: {rc}")

    def on_disconnect(self, client, userdata, rc):
        """MQTT disconnection callback"""
        logger.warning(f"Disconnected from MQTT broker: {rc}")

    def on_message(self, client, userdata, msg):
        """MQTT message callback"""
        try:
            topic_parts = msg.topic.split('/')
            if len(topic_parts) < 3:
                return

            namespace, instance_id, message_type = topic_parts[0], topic_parts[1], topic_parts[2]

            if namespace != MQTT_NAMESPACE:
                return

            # Initialize bot if not exists
            if instance_id not in self.bots:
                self.bots[instance_id] = BotStatus(
                    instance_id=instance_id,
                    status="unknown",
                    last_seen=datetime.now()
                )

            bot = self.bots[instance_id]
            bot.last_seen = datetime.now()

            # Process different message types
            if message_type == "hb":
                self.handle_heartbeat(bot, msg.payload)
            elif message_type == "events":
                self.handle_event(bot, msg.payload)
            elif message_type == "logs":
                self.handle_log(bot, msg.payload)
            elif message_type == "notify":
                self.handle_notification(bot, msg.payload)
            elif message_type == "status_updates":
                self.handle_status_update(bot, msg.payload)

        except Exception as e:
            logger.error(f"Error processing message: {e}")

    def handle_heartbeat(self, bot: BotStatus, payload: bytes):
        """Handle heartbeat messages"""
        try:
            data = json.loads(payload.decode())
            bot.status = "online"
            logger.debug(f"Bot {bot.instance_id} heartbeat received")
        except Exception as e:
            logger.error(f"Error processing heartbeat: {e}")

    def handle_event(self, bot: BotStatus, payload: bytes):
        """Handle trading events"""
        try:
            data = json.loads(payload.decode())
            event_type = data.get('type', 'unknown')

            if event_type == 'OrderFilledEvent':
                bot.trades_count += 1
                # Extract PnL if available
                if 'trade_fee' in data:
                    fee = data['trade_fee']
                    if isinstance(fee, dict) and 'amount' in fee:
                        bot.pnl -= float(fee['amount'])

            logger.info(f"Bot {bot.instance_id} event: {event_type}")

            # Send to CloudWatch
            self.send_to_cloudwatch(bot, "event", event_type)

        except Exception as e:
            logger.error(f"Error processing event: {e}")

    def handle_log(self, bot: BotStatus, payload: bytes):
        """Handle log messages"""
        try:
            data = json.loads(payload.decode())
            log_level = data.get('level_name', 'INFO')
            message = data.get('msg', '')

            # Check for errors
            if log_level in ['ERROR', 'CRITICAL']:
                bot.errors.append({
                    'timestamp': datetime.now().isoformat(),
                    'level': log_level,
                    'message': message
                })
                # Keep only last 10 errors
                bot.errors = bot.errors[-10:]

            logger.debug(f"Bot {bot.instance_id} log [{log_level}]: {message}")

        except Exception as e:
            logger.error(f"Error processing log: {e}")

    def handle_notification(self, bot: BotStatus, payload: bytes):
        """Handle notifications"""
        try:
            data = json.loads(payload.decode())
            message = data.get('msg', '')

            logger.info(f"Bot {bot.instance_id} notification: {message}")

            # Send to Slack if configured
            if SLACK_WEBHOOK_URL:
                self.send_to_slack(f"🤖 Bot {bot.instance_id}: {message}")

        except Exception as e:
            logger.error(f"Error processing notification: {e}")

    def handle_status_update(self, bot: BotStatus, payload: bytes):
        """Handle status updates"""
        try:
            data = json.loads(payload.decode())
            status_type = data.get('type', 'unknown')
            message = data.get('msg', '')

            if status_type == 'strategy_started':
                bot.status = "running"
                bot.strategy = message
            elif status_type == 'strategy_stopped':
                bot.status = "stopped"

            logger.info(f"Bot {bot.instance_id} status update: {status_type} - {message}")

        except Exception as e:
            logger.error(f"Error processing status update: {e}")

    def send_to_cloudwatch(self, bot: BotStatus, metric_name: str, value: Any):
        """Send metrics to CloudWatch"""
        if not self.cloudwatch:
            return

        try:
            self.cloudwatch.put_metric_data(
                Namespace=CLOUDWATCH_NAMESPACE,
                MetricData=[
                    {
                        'MetricName': metric_name,
                        'Dimensions': [
                            {
                                'Name': 'InstanceId',
                                'Value': bot.instance_id
                            }
                        ],
                        'Value': 1 if isinstance(value, str) else value,
                        'Unit': 'Count' if isinstance(value, (int, float)) else 'None',
                        'Timestamp': datetime.now()
                    }
                ]
            )
        except Exception as e:
            logger.error(f"Error sending to CloudWatch: {e}")

    def send_to_slack(self, message: str):
        """Send message to Slack"""
        if not SLACK_WEBHOOK_URL:
            return

        try:
            payload = {
                "text": message,
                "username": "Hummingbot Monitor",
                "icon_emoji": ":robot_face:"
            }

            response = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
            response.raise_for_status()

        except Exception as e:
            logger.error(f"Error sending to Slack: {e}")

    def check_bot_health(self):
        """Check bot health and send alerts"""
        current_time = datetime.now()

        for instance_id, bot in self.bots.items():
            # Check if bot is offline (no heartbeat for 5 minutes)
            if bot.last_seen and (current_time - bot.last_seen).seconds > 300:
                if bot.status != "offline":
                    bot.status = "offline"
                    logger.warning(f"Bot {instance_id} appears offline")
                    self.send_to_slack(f"⚠️ Bot {instance_id} is offline!")

            # Check for recent errors
            if bot.errors:
                recent_errors = [
                    error for error in bot.errors
                    if (current_time - datetime.fromisoformat(error['timestamp'])).seconds < 300
                ]
                if recent_errors:
                    error_msg = f"🚨 Bot {instance_id} has {len(recent_errors)} recent errors!"
                    self.send_to_slack(error_msg)

    def generate_status_report(self) -> Dict[str, Any]:
        """Generate status report"""
        return {
            "timestamp": datetime.now().isoformat(),
            "total_bots": len(self.bots),
            "online_bots": len([b for b in self.bots.values() if b.status == "online"]),
            "running_bots": len([b for b in self.bots.values() if b.status == "running"]),
            "offline_bots": len([b for b in self.bots.values() if b.status == "offline"]),
            "bots": {
                instance_id: {
                    "status": bot.status,
                    "strategy": bot.strategy,
                    "last_seen": bot.last_seen.isoformat() if bot.last_seen else None,
                    "trades_count": bot.trades_count,
                    "pnl": bot.pnl,
                    "recent_errors": len(bot.errors)
                }
                for instance_id, bot in self.bots.items()
            }
        }

    def start_monitoring(self):
        """Start monitoring loop"""
        logger.info("Starting MQTT monitoring...")

        # Connect to MQTT broker
        self.client.connect(MQTT_HOST, MQTT_PORT, 60)
        self.client.loop_start()

        # Start health check loop
        asyncio.create_task(self.health_check_loop())

        # Start status report loop
        asyncio.create_task(self.status_report_loop())

    async def health_check_loop(self):
        """Health check loop"""
        while True:
            self.check_bot_health()
            await asyncio.sleep(60)  # Check every minute

    async def status_report_loop(self):
        """Status report loop"""
        while True:
            report = self.generate_status_report()
            logger.info(f"Status report: {json.dumps(report, indent=2)}")
            await asyncio.sleep(300)  # Report every 5 minutes


def main():
    """Main function"""
    monitor = MQTTMonitor()

    try:
        monitor.start_monitoring()

        # Keep running
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("Shutting down monitor...")
        monitor.client.loop_stop()
        monitor.client.disconnect()


if __name__ == "__main__":
    main()
