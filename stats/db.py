import pymysql

from stats import pool, toolsdb

# every query takes a connection from the pool and gives it straight back.
# reads go to the read only copy of toolsdb (if this process has a read pool),
# writes and anything inside a transaction go to the primary


def _run(c, sql, args):
    with c.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, args)
        return [{k: toolsdb.clean(v) for k, v in r.items()} for r in cur.fetchall()]


def rows(sql, args=None, fresh=False):
    # fresh=True reads from the primary, for things that must see a write just made
    p = pool.writer() if fresh else pool.reader()
    return p.retry(lambda c: _run(c, sql, args))


def one(sql, args=None, fresh=False):
    r = rows(sql, args, fresh)
    return r[0] if r else None


def run(sql, args=None):
    # for writes, returns the affected row count
    def go(c):
        with c.cursor() as cur:
            return cur.execute(sql, args)
    return pool.writer().retry(go) or 0


def write(fn):
    # fn(conn) runs inside one transaction on the primary, retried as a whole
    # on a deadlock or a lost connection
    def go(c):
        c.autocommit(False)
        try:
            out = fn(c)
            c.commit()
            return out
        except BaseException:
            try:
                c.rollback()
            except Exception:
                pass  # the pool drops a broken connection anyway
            raise
        finally:
            try:
                c.autocommit(True)
            except Exception:
                pass
    return pool.writer().retry(go)
