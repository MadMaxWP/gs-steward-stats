from flask import g, has_app_context

from stats import toolsdb

# toolsdb connection per request. it is opened on the first query and
# closed by close() once the request is done (app.py hooks that up).
# outside a request (backfill.py) use() hands in a connection to run on

_outside = {"conn": None}


def use(c):
    _outside["conn"] = c


def conn():
    if "db" not in g:
        g.db = toolsdb.connect()
    return g.db


def close(exc=None):
    c = g.pop("db", None)
    if c is not None:
        try:
            c.close()
        except Exception:
            pass


def rows(sql, args=None):
    if not has_app_context():
        if _outside["conn"] is not None:
            return _run(_outside["conn"], sql, args)
        # background threads have no request, so they get a short lived connection
        c = toolsdb.connect()
        try:
            return _run(c, sql, args)
        finally:
            c.close()
    try:
        return _run(conn(), sql, args)
    except Exception:
        # a broken connection shouldn't stick around for the rest of the request
        close()
        raise


def _run(c, sql, args):
    with c.cursor() as cur:
        cur.execute(sql, args)
        return [{k: toolsdb.clean(v) for k, v in r.items()} for r in cur.fetchall()]


def run(sql, args=None):
    # for writes, returns the affected row count
    if not has_app_context() and _outside["conn"] is None:
        c = toolsdb.connect()
        try:
            with c.cursor() as cur:
                return cur.execute(sql, args)
        finally:
            c.close()
    c = _outside["conn"] if not has_app_context() else conn()
    with c.cursor() as cur:
        return cur.execute(sql, args)


def one(sql, args=None):
    r = rows(sql, args)
    return r[0] if r else None
