import threading
import time
from collections import OrderedDict

# small in memory cache, one per worker. when it's full the oldest entries go,
# not the whole thing, so a burst of explorer pages can't push out the overview

max_items = 300
_items = OrderedDict()
_lock = threading.Lock()


def cached(key, ttl, fn, force=False):
    # returns (value, time it was computed)
    now = time.time()
    if not force:
        with _lock:
            hit = _items.get(key)
            if hit and now - hit[0] < ttl:
                _items.move_to_end(key)
                return hit[1], hit[0]
    value = fn()
    with _lock:
        _items[key] = (now, value)
        _items.move_to_end(key)
        while len(_items) > max_items:
            _items.popitem(last=False)
    return value, now
