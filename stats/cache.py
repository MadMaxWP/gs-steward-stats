import json
import logging
import threading
import time
from collections import OrderedDict

from stats import settings

try:
    import redis
except ImportError:
    redis = None

# cache in two layers:
#   - a small one in memory, per process, so hot keys don't even leave python
#   - toolforge's shared redis, so the cache outlives deploys and restarts and
#     the website, listener and update job see the same things
#
# redis is shared by every tool, so every key starts with a secret prefix
# (GS_REDIS_PREFIX) and only public data goes in. without a prefix, or when
# redis is down, it's memory only and everything still works

log = logging.getLogger("gs.cache")

max_items = 300
_items = OrderedDict()
_lock = threading.Lock()

_client = None
_client_lock = threading.Lock()
_down_until = 0
_last_warning = 0


def client():
    # one client per process. redis-py keeps a small pool of open connections
    # and reuses them, that's normal for redis (unlike toolsdb)
    global _client
    if redis is None or not settings.redis_prefix or time.time() < _down_until:
        return None
    if _client is None:
        with _client_lock:
            if _client is None:
                pool = redis.BlockingConnectionPool(
                    host=settings.redis_host, port=settings.redis_port,
                    max_connections=settings.redis_connections, timeout=2,
                    socket_timeout=1, socket_connect_timeout=1, socket_keepalive=True,
                    health_check_interval=30, decode_responses=True,
                )
                _client = redis.Redis(connection_pool=pool)
    return _client


def failed(e):
    # skip redis for 30s instead of waiting on a timeout every call. say so once a minute
    global _down_until, _last_warning
    _down_until = time.time() + 30
    if time.time() - _last_warning > 60:
        _last_warning = time.time()
        log.warning("redis unavailable, using memory only for now: %s", e)


def rkey(key):
    return settings.redis_prefix + ":" + json.dumps(list(key) if isinstance(key, tuple) else key, ensure_ascii=False, separators=(",", ":"))


def get(key):
    r = client()
    if r is None:
        return None
    try:
        raw = r.get(rkey(key))
    except Exception as e:
        failed(e)
        return None
    return json.loads(raw) if raw else None


def put(key, value, ttl):
    r = client()
    if r is None:
        return
    try:
        raw = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return  # not plain json, it stays in memory only
    try:
        r.set(rkey(key), raw, ex=max(1, int(ttl)))
    except Exception as e:
        failed(e)


def remember(key, at, value):
    with _lock:
        _items[key] = (at, value)
        _items.move_to_end(key)
        while len(_items) > max_items:
            _items.popitem(last=False)


def cached(key, ttl, fn, force=False, shared=True):
    # returns (value, time it was computed). shared=False keeps it out of redis
    now = time.time()
    if not force:
        with _lock:
            hit = _items.get(key)
            if hit and now - hit[0] < ttl:
                _items.move_to_end(key)
                return hit[1], hit[0]
        found = get(key) if shared else None
        if found and now - found["at"] < ttl:
            remember(key, found["at"], found["v"])
            return found["v"], found["at"]
    value = fn()
    remember(key, now, value)
    if shared:
        put(key, {"at": now, "v": value}, ttl)
    return value, now


# the data version: the newest sync or save time. the listener and update job
# set it right after they write, so the website doesn't need to ask toolsdb

version_key = ("version",)


def bump_version(stamp):
    r = client()
    if r is None:
        return
    try:
        old = r.get(rkey(version_key))
        if not old or stamp > old:
            r.set(rkey(version_key), stamp, ex=86400)
    except Exception as e:
        failed(e)


def read_version():
    r = client()
    if r is None:
        return None
    try:
        return r.get(rkey(version_key))
    except Exception as e:
        failed(e)
        return None


def set_version(stamp):
    r = client()
    if r is None or not stamp:
        return
    try:
        r.set(rkey(version_key), stamp, ex=3600, nx=True)
    except Exception as e:
        failed(e)
