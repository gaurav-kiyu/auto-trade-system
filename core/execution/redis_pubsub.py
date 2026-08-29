import json
import logging
from collections.abc import Callable

import redis

_log = logging.getLogger(__name__)

class RedisMarketDataBus:
    """
    Enterprise Pub/Sub Bus for ultra-low latency tick distribution.
    Fails gracefully if Redis is not running locally.
    """
    def __init__(self, host: str = '127.0.0.1', port: int = 6379, db: int = 0):
        self.host = host
        self.port = port
        self.db = db
        self.is_connected = False
        self.client: redis.Redis | None = None
        self.pubsub = None
        self._thread = None
        self._connect()

    def _connect(self):
        try:
            self.client = redis.Redis(
                host=self.host,
                port=self.port,
                db=self.db,
                socket_connect_timeout=0.05,
                socket_timeout=0.05
            )
            # Ping to test connection
            self.client.ping()
            self.is_connected = True
            self.pubsub = self.client.pubsub(ignore_subscribe_messages=True)
            _log.info("Redis Pub/Sub Bus connected successfully.")
        except Exception:
            _log.warning("Redis server not found on 127.0.0.1:6379. Running in Fallback (Disabled) Mode.")
            self.is_connected = False

    def publish_tick(self, symbol: str, tick_data: dict):
        """Publish a tick to the channel"""
        if not self.is_connected or not self.client:
            return
        try:
            payload = json.dumps(tick_data)
            self.client.publish(f"MARKET_DATA::{symbol}", payload)
        except Exception as e:
            _log.error(f"Redis publish error: {e}")

    def subscribe(self, symbol: str, callback: Callable[[dict], None]):
        """Subscribe to a symbol's ticks."""
        if not self.is_connected or not self.pubsub:
            return

        channel = f"MARKET_DATA::{symbol}"

        def _handler(message):
            try:
                data = json.loads(message['data'])
                callback(data)
            except Exception as e:
                _log.error(f"Error parsing Redis message: {e}")

        self.pubsub.subscribe(**{channel: _handler})

        if not self._thread or not self._thread.is_alive():
            self._thread = self.pubsub.run_in_thread(sleep_time=0.001)

    def close(self):
        if self._thread:
            self._thread.stop()
        if self.pubsub:
            self.pubsub.close()
        if self.client:
            self.client.close()

_redis_bus = RedisMarketDataBus()

def get_redis_bus() -> RedisMarketDataBus:
    return _redis_bus
