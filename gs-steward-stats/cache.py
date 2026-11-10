"""tiny in-process cache with a time-to-live per entry.

each uWSGI worker keeps its own copy. The cache is cleared completely when it
grows past ``max_entries``, which is enough for the small number of distinct
keys tool produces.
"""

import threading
import time

max_entries = 250

_store = {}
_lock = threading.Lock()


def cached(key, ttl, compute, force=False):
    """Return ``(value, computed_at)``.

    stored value is reused while it is younger than ``ttl`` seconds.
    ``force=True`` always recomputes and stores the fresh value.
    """
    now = time.time()
    if not force:
        with _lock:
            hit = _store.get(key)
            if hit and now - hit[0] < ttl:
                return hit[1], hit[0]
    value = compute()
    with _lock:
        if len(_store) > max_entries:
            _store.clear()
        _store[key] = (now, value)
    return value, now
