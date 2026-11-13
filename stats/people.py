import threading
import time

import pymysql

from stats import db

# who has used the tool lately, kept in the `people` table on toolsdb.
# on purpose this keeps as little as possible: a username and the minute they
# were last here, overwritten each time. no login history, no counts, no ids,
# and anyone gone for 30 days is deleted. only a rough "x ago" is ever sent out

online_window = 5 * 60
forget_days = 30
write_gap = 60   # a worker writes the same user at most once a minute

table = """
CREATE TABLE IF NOT EXISTS people (
    name VARCHAR(255) NOT NULL PRIMARY KEY,
    last_seen DATETIME NOT NULL,
    KEY idx_last_seen (last_seen)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

_written = {}
_state = {"table": False}
_lock = threading.Lock()


def ensure_table():
    # made on first use, so an existing setup doesn't need backfill.py init again
    if not _state["table"]:
        db.run(table)
        _state["table"] = True


def seen(name):
    if not name:
        return
    now = time.time()
    with _lock:
        if now - _written.get(name, 0) < write_gap:
            return
        _written[name] = now
    ensure_table()
    db.run(
        "INSERT INTO people (name, last_seen) VALUES (%s, DATE_FORMAT(UTC_TIMESTAMP(), '%%Y-%%m-%%d %%H:%%i:00')) "
        "ON DUPLICATE KEY UPDATE last_seen = VALUES(last_seen)",
        [name],
    )
    db.run(f"DELETE FROM people WHERE last_seen < UTC_TIMESTAMP() - INTERVAL {forget_days} DAY")


def ago(seconds):
    m = seconds / 60
    if m < 60:
        return f"{max(1, int(m))} min ago"
    h = m / 60
    if h < 24:
        return f"{int(h)} h ago"
    return f"{int(h / 24)} d ago"


def everyone():
    try:
        found = db.rows(
            "SELECT name, TIMESTAMPDIFF(SECOND, last_seen, UTC_TIMESTAMP()) AS age FROM people "
            f"WHERE last_seen >= UTC_TIMESTAMP() - INTERVAL {forget_days} DAY ORDER BY last_seen DESC, name"
        )
    except pymysql.err.ProgrammingError:
        return []  # nobody has been seen since the table would have been made
    return [{"name": r["name"], "online": r["age"] < online_window, "ago": ago(r["age"])} for r in found]
