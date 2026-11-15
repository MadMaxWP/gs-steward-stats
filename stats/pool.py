import logging
import random
import threading
import time
from contextlib import contextmanager

import pymysql

from stats import toolsdb

# small toolsdb connection pools:
#   - no connections kept when nothing is going on (min 0, idle ones closed after 1s)
#   - idle_transaction_timeout=2 so a stuck transaction never holds locks for long
#   - a connection is pinged when it's taken out and thrown away after a few minutes
#   - every connection always goes back (rolled back on error, closed if broken)
#
# toolsdb allows ~10 connections per tool per server, so each process gets a
# fixed number and waits for a free one instead of opening more

log = logging.getLogger("gs.pool")

idle_timeout = 1
max_life = 5 * 60
busy_codes = (1203, 1040, 1226)      # too many connections / user limit
io_codes = (2006, 2013, 2003, 2055)  # server gone, lost connection, can't connect
lock_codes = (1213, 1205)            # deadlock, lock wait timeout
dup_code = 1062


class PoolTimeout(Exception):
    pass


class Pool:
    def __init__(self, name, host, size, wait, busy_wait=50):
        self.name = name
        self.host = host
        self.size = size
        self.wait = wait            # how long a caller waits for a free connection
        self.busy_wait = busy_wait  # how long to back off when toolsdb says it's full
        self.slots = threading.BoundedSemaphore(size)
        self.idle = []              # (conn, born, last_used)
        self.lock = threading.Lock()
        self.open = 0
        self.closed = False
        threading.Thread(target=self.reaper, name=f"pool-{name}-reaper", daemon=True).start()

    # ---- connections

    def new(self):
        c = toolsdb.connect(host=self.host)
        try:
            with c.cursor() as cur:
                cur.execute("SET SESSION idle_transaction_timeout = 2")
        except pymysql.err.MySQLError:
            pass  # older servers don't have it, not worth failing over
        with self.lock:
            self.open += 1
        return c

    def drop(self, c):
        try:
            c.close()
        except Exception:
            pass
        with self.lock:
            self.open -= 1

    def take(self):
        if self.closed:
            raise PoolTimeout(f"{self.name} pool is shut down")
        if not self.slots.acquire(timeout=self.wait):
            raise PoolTimeout(f"no free {self.name} connection after {self.wait}s")
        try:
            while True:
                with self.lock:
                    item = self.idle.pop() if self.idle else None
                if item is None:
                    return self.new(), time.time()
                c, born = item[0], item[1]
                if time.time() - born > max_life:
                    self.drop(c)
                    continue
                try:
                    c.ping(reconnect=False)
                    return c, born
                except Exception:
                    self.drop(c)
        except Exception:
            self.slots.release()
            raise

    def give(self, c, born, broken=False):
        try:
            if not broken:
                try:
                    if c.get_autocommit() is False:
                        c.rollback()
                        c.autocommit(True)
                except Exception:
                    broken = True
            if broken or self.closed or time.time() - born > max_life:
                self.drop(c)
            else:
                with self.lock:
                    self.idle.append((c, born, time.time()))
        finally:
            self.slots.release()

    @contextmanager
    def conn(self):
        c, born = self.take()
        broken = False
        try:
            yield c
        except pymysql.err.OperationalError as e:
            broken = code(e) in io_codes or code(e) in busy_codes
            raise
        except pymysql.err.InterfaceError:
            broken = True
            raise
        except BaseException:
            try:
                c.rollback()
            except Exception:
                broken = True
            raise
        finally:
            self.give(c, born, broken)

    def reaper(self):
        while not self.closed:
            time.sleep(0.5)
            now = time.time()
            old = []
            with self.lock:
                keep = []
                for item in self.idle:
                    if now - item[2] > idle_timeout or now - item[1] > max_life:
                        old.append(item[0])
                    else:
                        keep.append(item)
                self.idle = keep
            for c in old:
                self.drop(c)

    def shutdown(self):
        self.closed = True
        with self.lock:
            old = [i[0] for i in self.idle]
            self.idle = []
        for c in old:
            self.drop(c)

    def stats(self):
        with self.lock:
            return {"open": self.open, "idle": len(self.idle), "size": self.size}

    # ---- running things with retries

    def retry(self, fn, dup_ok=False):
        # fn gets a connection. same retry rules as xlinks' with_retry.
        # dup_ok: a duplicate key means it's already saved, so that's fine. only for
        # single writes, inside a transaction it would quietly lose the rest of it
        io_tries = lock_tries = busy_tries = 0
        while True:
            try:
                with self.conn() as c:
                    return fn(c)
            except pymysql.err.MySQLError as e:
                n = code(e)
                if n == dup_code and dup_ok:
                    return None
                if n in busy_codes and busy_tries < 3:
                    busy_tries += 1
                    log.warning("%s: toolsdb is full (%s), waiting %ss", self.name, n, self.busy_wait)
                    time.sleep(self.busy_wait)
                    continue
                if (n in io_codes or isinstance(e, pymysql.err.InterfaceError)) and io_tries < 3:
                    io_tries += 1
                    time.sleep(random.uniform(0.5, 2) * io_tries)
                    continue
                if n in lock_codes and lock_tries < 5:
                    lock_tries += 1
                    time.sleep(random.uniform(0.05, 0.5) * lock_tries)
                    continue
                raise


def code(e):
    try:
        return int(e.args[0])
    except (IndexError, TypeError, ValueError):
        return 0


# one set of pools per process, made by whoever starts it (app.py, listen.py, backfill.py)
pools = {"read": None, "write": None}


def setup(read=0, write=1, wait=30, busy_wait=50):
    from stats import settings
    shutdown()  # if it's called twice, don't leave the old pools and their threads around
    if write:
        pools["write"] = Pool("write", settings.db_host, write, wait, busy_wait)
    if read:
        pools["read"] = Pool("read", settings.db_read_host or settings.db_host, read, wait, busy_wait)


def reader():
    # no read pool in this process means reads go to the primary as well
    return pools["read"] or writer()


def writer():
    if pools["write"] is None:
        setup()
    return pools["write"]


def shutdown():
    for k, p in pools.items():
        if p:
            p.shutdown()
            pools[k] = None
