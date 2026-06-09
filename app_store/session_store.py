from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from typing import Any

import redis

from app_store.config import settings


ACTIVE_SESSIONS_KEY = "active_sessions"
ACTIVE_SESSIONS_READABLE_KEY = "active_sessions:readable"
CLEANUP_COOLDOWN_KEY = "cleanup:last_run"
CLEANUP_COOLDOWN_READABLE_KEY = "cleanup:last_run:readable"
import os

_client: redis.Redis | None = None
_client_pid: int | None = None
_memory_lock = threading.Lock()
_memory: dict[str, tuple[float, str]] = {}
_active_memory: dict[str, float] = {}
_cleanup_due_at = 0.0


def _get_client() -> redis.Redis | None:
    global _client, _client_pid
    if not settings.redis_url:
        return None
    current_pid = os.getpid()
    if _client is None or _client_pid != current_pid:
        _client = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            max_connections=20,
        )
        _client_pid = current_pid
    return _client


def _key(kind: str, session_id: str) -> str:
    return f"{kind}:{session_id}"


def _format_timestamp(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%I:%M %p %d %B %Y")


def _memory_set(key: str, value: str, ttl: int) -> None:
    with _memory_lock:
        _memory[key] = (time.time() + ttl, value)


def _memory_get(key: str) -> str | None:
    with _memory_lock:
        item = _memory.get(key)
        if not item:
            return None
        expires_at, value = item
        if expires_at <= time.time():
            _memory.pop(key, None)
            return None
        return value


def _memory_delete(*keys: str) -> None:
    with _memory_lock:
        for key in keys:
            _memory.pop(key, None)


def touch_session(session_id: str) -> int:
    now = int(time.time())
    expires_at = now + settings.session_ttl_seconds
    payload = json.dumps(
        {
            "last_active_at": now,
            "last_active_at_readable": _format_timestamp(now),
            "expires_at": expires_at,
            "expires_at_readable": _format_timestamp(expires_at),
        }
    )
    client = _get_client()

    if client:
        client.set(_key("session", session_id), payload, ex=settings.session_ttl_seconds)
        client.zadd(ACTIVE_SESSIONS_KEY, {session_id: expires_at})
        client.hset(ACTIVE_SESSIONS_READABLE_KEY, session_id, _format_timestamp(expires_at))
    else:
        _memory_set(_key("session", session_id), payload, settings.session_ttl_seconds)
        with _memory_lock:
            _active_memory[session_id] = expires_at
    return expires_at


def set_json(kind: str, session_id: str, data: Any) -> None:
    touch_session(session_id)
    key = _key(kind, session_id)
    val = json.dumps(data)
    client = _get_client()
    if client:
        client.set(key, val, ex=settings.session_ttl_seconds)
    else:
        _memory_set(key, val, settings.session_ttl_seconds)


def get_json(kind: str, session_id: str) -> Any | None:
    key = _key(kind, session_id)
    client = _get_client()
    if client:
        val = client.get(key)
    else:
        val = _memory_get(key)
    
    if val is None:
        return None
    try:
        return json.loads(val)
    except Exception:
        return None


def append_log(session_id: str, log_line: str) -> None:
    touch_session(session_id)
    key = _key("logs", session_id)
    client = _get_client()
    if client:
        client.rpush(key, log_line)
        client.expire(key, settings.session_ttl_seconds)
    else:
        with _memory_lock:
            existing = _memory_get(key)
            if existing:
                try:
                    lst = json.loads(existing)
                except Exception:
                    lst = []
            else:
                lst = []
            lst.append(log_line)
            _memory_set(key, json.dumps(lst), settings.session_ttl_seconds)


def get_logs(session_id: str) -> list[str]:
    key = _key("logs", session_id)
    client = _get_client()
    if client:
        return client.lrange(key, 0, -1)
    else:
        val = _memory_get(key)
        if not val:
            return []
        try:
            return json.loads(val)
        except Exception:
            return []


def get_expired_sessions(limit: int = 100) -> list[str]:
    now = int(time.time())
    client = _get_client()
    if client:
        return list(
            client.zrangebyscore(
                ACTIVE_SESSIONS_KEY, "-inf", now, start=0, num=limit
            )
        )
    with _memory_lock:
        return [
            sid
            for sid, expires_at in list(_active_memory.items())[:limit]
            if expires_at <= now
        ]


def mark_cleanup_if_due() -> bool:
    global _cleanup_due_at
    client = _get_client()
    if client:
        marked = bool(
            client.set(
                CLEANUP_COOLDOWN_KEY,
                str(int(time.time())),
                ex=settings.cleanup_cooldown_seconds,
                nx=True,
            )
        )
        if marked:
            client.set(
                CLEANUP_COOLDOWN_READABLE_KEY,
                _format_timestamp(int(time.time())),
                ex=settings.cleanup_cooldown_seconds,
            )
        return marked
    with _memory_lock:
        now = time.time()
        if now < _cleanup_due_at:
            return False
        _cleanup_due_at = now + settings.cleanup_cooldown_seconds
        return True


def clear_session(session_id: str) -> None:
    keys = [_key(kind, session_id) for kind in ("session", "transcript", "chat", "result", "logs")]
    client = _get_client()
    if client:
        client.delete(*keys)
        client.zrem(ACTIVE_SESSIONS_KEY, session_id)
        client.hdel(ACTIVE_SESSIONS_READABLE_KEY, session_id)
    else:
        _memory_delete(*keys)
        with _memory_lock:
            _active_memory.pop(session_id, None)
