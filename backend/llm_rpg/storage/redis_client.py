import os
import json
from typing import Any, Dict, List, Optional, Union
from datetime import timedelta

import redis
from redis import Redis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


class RedisClient:
    def __init__(self, redis_url: str = REDIS_URL):
        self._redis: Optional[Redis] = None
        self._redis_url = redis_url

    def connect(self) -> Redis:
        if self._redis is None:
            self._redis = redis.from_url(self._redis_url, decode_responses=True)
        return self._redis

    def disconnect(self):
        if self._redis:
            self._redis.close()
            self._redis = None

    def ping(self) -> bool:
        try:
            return self.connect().ping()
        except redis.ConnectionError:
            return False

    def set(self, key: str, value: Union[str, bytes, int, float], ttl: Optional[int] = None) -> bool:
        r = self.connect()
        if isinstance(value, (dict, list)):
            value = json.dumps(value)
        if ttl:
            return r.setex(key, ttl, value)
        return r.set(key, value)

    def get(self, key: str) -> Optional[str]:
        r = self.connect()
        value = r.get(key)
        return value.decode('utf-8') if isinstance(value, bytes) else value

    def get_json(self, key: str) -> Optional[Any]:
        value = self.get(key)
        if value:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return None

    def delete(self, key: str) -> int:
        return self.connect().delete(key)

    def exists(self, key: str) -> bool:
        return self.connect().exists(key) > 0

    def expire(self, key: str, seconds: int) -> bool:
        return self.connect().expire(key, seconds)

    def ttl(self, key: str) -> int:
        return self.connect().ttl(key)

    def set_session_stream(self, session_id: str, data: Dict[str, Any], ttl: int = 3600) -> bool:
        key = f"session:{session_id}:stream"
        return self.set(key, data, ttl)

    def get_session_stream(self, session_id: str) -> Optional[Dict[str, Any]]:
        key = f"session:{session_id}:stream"
        return self.get_json(key)

    def delete_session_stream(self, session_id: str) -> int:
        key = f"session:{session_id}:stream"
        return self.delete(key)

    def cache_llm_response(self, cache_key: str, response: str, ttl: int = 3600) -> bool:
        key = f"llm:cache:{cache_key}"
        return self.set(key, response, ttl)

    def get_cached_llm_response(self, cache_key: str) -> Optional[str]:
        key = f"llm:cache:{cache_key}"
        return self.get(key)

    def set_turn_lock(self, session_id: str, turn_no: int, ttl: int = 300) -> bool:
        key = f"session:{session_id}:turn:{turn_no}:lock"
        return self.set(key, "1", ttl)

    def release_turn_lock(self, session_id: str, turn_no: int) -> int:
        key = f"session:{session_id}:turn:{turn_no}:lock"
        return self.delete(key)

    def is_turn_locked(self, session_id: str, turn_no: int) -> bool:
        key = f"session:{session_id}:turn:{turn_no}:lock"
        return self.exists(key)

    def publish_event(self, channel: str, message: Dict[str, Any]) -> int:
        r = self.connect()
        return r.publish(channel, json.dumps(message))

    def subscribe(self, channel: str):
        r = self.connect()
        pubsub = r.pubsub()
        pubsub.subscribe(channel)
        return pubsub

    def add_to_queue(self, queue_name: str, item: Dict[str, Any]) -> int:
        r = self.connect()
        return r.lpush(queue_name, json.dumps(item))

    def pop_from_queue(self, queue_name: str, timeout: int = 0) -> Optional[Dict[str, Any]]:
        r = self.connect()
        result = r.brpop(queue_name, timeout=timeout)
        if result:
            _, item = result
            try:
                return json.loads(item)
            except json.JSONDecodeError:
                return {"raw": item}
        return None

    def get_queue_length(self, queue_name: str) -> int:
        return self.connect().llen(queue_name)

    def clear_cache_pattern(self, pattern: str) -> int:
        r = self.connect()
        keys = r.keys(pattern)
        if keys:
            return r.delete(*keys)
        return 0


_redis_client: Optional[RedisClient] = None


def get_redis() -> RedisClient:
    global _redis_client
    if _redis_client is None:
        _redis_client = RedisClient()
    return _redis_client


def init_redis(redis_url: str = REDIS_URL) -> RedisClient:
    global _redis_client
    _redis_client = RedisClient(redis_url)
    return _redis_client
