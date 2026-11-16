import json
import re
from datetime import datetime, timezone

import pymysql

from stats import cache, db, rights, toolsdb
from stats.cache import cached
from stats.wikimedia import fetch_config

# everything the pages ask gs_actions for. actions by former members are left out
# by the join on gs_users, closed/locked wikis are flagged with lk = 1.
#
# the heavy ones (overview, users, projects) are worked out by backfill.py after
# each sync and kept in gs_summary, so pages just read a row. if that row isn't
# there yet the same thing is worked out live

from_sql = (
    "FROM gs_actions a "
    "JOIN gs_users u ON u.name = a.actor AND u.is_current = 1 "
    "LEFT JOIN gs_wikis w ON w.dbname = a.wiki"
)
locked = "COALESCE(w.is_locked, 0)"

categories = {
    # a few old entries have a blank action, they're plain deletions
    "delete": "a.log_type = 'delete' AND a.log_action IN ('delete', 'delete_redir', 'delete_redir2', '')",
    "undelete": "a.log_type = 'delete' AND a.log_action = 'restore'",
    "revdel": "a.log_type = 'delete' AND a.log_action = 'revision'",
    "logdel": "a.log_type = 'delete' AND a.log_action = 'event'",
    "block": "a.log_type = 'block' AND a.log_action = 'block'",
    "unblock": "a.log_type = 'block' AND a.log_action = 'unblock'",
    "reblock": "a.log_type = 'block' AND a.log_action = 'reblock'",
    "protect": "a.log_type = 'protect' AND a.log_action = 'protect'",
    "unprotect": "a.log_type = 'protect' AND a.log_action = 'unprotect'",
    "protmod": "a.log_type = 'protect' AND a.log_action IN ('modify', 'move_prot')",
    "merge": "a.log_type = 'merge'",
    "import": "a.log_type = 'import'",
    "abusefilter": "a.log_type = 'abusefilter'",
}

date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
filter_keys = ("user", "role", "wiki", "cat", "scope", "q", "from", "to", "sort")


def valid_date(s):
    if not s or not date_re.match(s):
        return None
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return s
    except ValueError:
        return None


def data_version():
    # changes whenever the db is refreshed, so cache keys built with it never outlive a sync.
    # the listener and update job keep it in redis, toolsdb is only asked when it's not there
    def q():
        v = cache.read_version()
        if v:
            return v
        r = db.one("SELECT MAX(v) AS v FROM gs_meta WHERE k IN ('last_backfill', 'last_update', 'last_summary', 'last_live', 'last_recount')")
        v = (r or {}).get("v") or ""
        cache.set_version(v)
        return v
    return cached(("data_version",), 2 if cache.client() else 30, q, shared=False)[0]


def config_users():
    try:
        cfg, _ = cached(("config",), 1800, fetch_config)
        return cfg.get("users") or {}
    except Exception:
        return {}


# ------------------------------------------------------------------ actions

def build_where(f):
    cond, par = [], []
    if f.get("user"):
        cond.append("a.actor = %s")
        par.append(f["user"])
    if f.get("role") in ("steward", "global-sysop"):
        cond.append("u.role = %s")
        par.append(f["role"])
    if f.get("wiki"):
        cond.append("(a.wiki = %s OR w.domain = %s)")
        par += [f["wiki"], f["wiki"]]
    if f.get("cat") in categories:
        cond.append("(" + categories[f["cat"]] + ")")
    scope = f.get("scope") or "open"
    if scope == "locked":
        cond.append(f"{locked} = 1")
    elif scope != "all":
        cond.append(f"{locked} = 0")
    q = (f.get("q") or "").strip()
    if q:
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        cond.append("(a.title LIKE %s OR a.comment LIKE %s)")
        par += [like, like]
    if valid_date(f.get("from")):
        cond.append("a.log_timestamp >= %s")
        par.append(f["from"] + " 00:00:00")
    if valid_date(f.get("to")):
        cond.append("a.log_timestamp < DATE_ADD(%s, INTERVAL 1 DAY)")
        par.append(f["to"])
    return cond, par


def parse_cursor(s):
    # cursor is "<iso time>|<row id>" taken from the last row of the previous chunk
    try:
        ts, rid = s.split("|", 1)
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ"), int(rid)
    except (ValueError, AttributeError):
        return None


action_cols = (
    "SELECT a.id, a.wiki, a.log_id, a.actor, a.log_type, a.log_action, a.log_timestamp AS ts, "
    "a.namespace, a.title, a.comment, a.params, w.domain, u.role AS role, "
    f"{locked} AS locked "
)


def count_actions(f):
    cond, par = build_where(f)
    where = (" WHERE " + " AND ".join(cond)) if cond else ""
    return int(db.one(f"SELECT COUNT(*) AS n {from_sql}{where}", par or None)["n"] or 0)


def find_actions(f, offset=0, limit=50, after=None, tail=False):
    # three ways in, so deep pages stay cheap:
    #   after = cursor  -> keyset paging from the previous chunk, no offset at all
    #   tail = True     -> count from the far end (the client passes offset from the end)
    #   neither         -> plain offset, only used near the start
    cond, par = build_where(f)
    asc = f.get("sort") == "asc"
    if tail:
        asc = not asc
    cur = parse_cursor(after) if after and not tail else None
    if cur:
        op = ">" if asc else "<"
        cond.append(f"(a.log_timestamp {op} %s OR (a.log_timestamp = %s AND a.id {op} %s))")
        par += [cur[0], cur[0], cur[1]]
        offset = 0
    where = (" WHERE " + " AND ".join(cond)) if cond else ""
    order = "ASC" if asc else "DESC"
    found = db.rows(
        f"{action_cols}{from_sql}{where} ORDER BY a.log_timestamp {order}, a.id {order} LIMIT %s OFFSET %s",
        par + [limit, offset],
    )
    for r in found:
        r["params"] = parse_json(r["params"])
        r["domain"] = r["domain"] or ""
    if tail:
        found.reverse()
    return found


def stream_actions(f, cursor):
    # same filters, run on an unbuffered cursor so a big csv never sits in memory
    cond, par = build_where(f)
    where = (" WHERE " + " AND ".join(cond)) if cond else ""
    order = "ASC" if f.get("sort") == "asc" else "DESC"
    cursor.execute(f"{action_cols}{from_sql}{where} ORDER BY a.log_timestamp {order}, a.id {order}", par or None)
    cols = [c[0] for c in cursor.description]
    for raw in cursor:
        yield {k: toolsdb.clean(v) for k, v in zip(cols, raw)}


def parse_json(text):
    if not text:
        return {}
    try:
        return json.loads(text)
    except ValueError:
        return {}


# ------------------------------------------------------------------ stored summaries

def stored(key):
    try:
        r = db.one("SELECT v FROM gs_summary WHERE k = %s", [key])
    except pymysql.err.ProgrammingError:
        return None  # table not made yet, backfill.py hasn't run since the update
    return json.loads(r["v"]) if r else None


def overview():
    return stored("overview") or overview_live()


def projects():
    return stored("projects") or projects_live()


def project_detail(dbname):
    return stored("project:" + dbname) or project_live(dbname)


# ------------------------------------------------------------------ overview and users

def overview_live():
    sub = f"(SELECT a.actor, a.wiki, a.log_timestamp AS ts, {locked} AS lk {from_sql}) x"
    totals = db.one(
        "SELECT SUM(lk = 0) AS total, SUM(lk = 1) AS locked, MAX(ts) AS last_ts, "
        "SUM(lk = 0 AND ts >= UTC_TIMESTAMP() - INTERVAL 1 DAY) AS d1, "
        "SUM(lk = 0 AND ts >= UTC_TIMESTAMP() - INTERVAL 7 DAY) AS d7, "
        f"SUM(lk = 0 AND ts >= UTC_TIMESTAMP() - INTERVAL 30 DAY) AS d30 FROM {sub}"
    )
    per_user = db.rows(
        "SELECT actor, SUM(lk = 0) AS total, SUM(lk = 1) AS locked, "
        "SUM(lk = 0 AND ts >= UTC_TIMESTAMP() - INTERVAL 30 DAY) AS c30, "
        "SUM(lk = 0 AND ts >= UTC_TIMESTAMP() - INTERVAL 90 DAY) AS c90, "
        "MAX(ts) AS last_ts, "
        f"COUNT(DISTINCT CASE WHEN lk = 0 THEN wiki END) AS wikis FROM {sub} GROUP BY actor"
    )
    members = db.rows("SELECT name, first_granted, role FROM gs_users WHERE is_current = 1 ORDER BY name")
    last_rows = db.rows(
        "SELECT a.actor, a.wiki, a.log_type, a.log_action, a.title, a.log_timestamp AS ts, w.domain "
        "FROM gs_actions a JOIN (SELECT actor, MAX(log_timestamp) AS mt FROM gs_actions GROUP BY actor) m "
        "ON m.actor = a.actor AND m.mt = a.log_timestamp LEFT JOIN gs_wikis w ON w.dbname = a.wiki"
    )
    # whole calendar months, starting 23 months back, so the chart always covers 2 years.
    # months with no actions don't come back from sql, the browser fills those in
    monthly = db.rows(
        f"SELECT EXTRACT(YEAR_MONTH FROM ts) AS ym, COUNT(*) AS c FROM {sub} "
        "WHERE lk = 0 AND ts >= DATE_FORMAT(UTC_TIMESTAMP() - INTERVAL 23 MONTH, '%Y-%m-01') "
        "GROUP BY ym ORDER BY ym"
    )
    cfg_users = config_users()
    last = {}
    for r in last_rows:
        last.setdefault(r["actor"], r)
    stats = {r["actor"]: r for r in per_user}
    users = []
    for m in members:
        s = stats.get(m["name"], {})
        lr = last.get(m["name"])
        users.append({
            "name": m["name"],
            "role": m["role"],
            "first_granted": m["first_granted"],
            "role_since": rights.role_since(cfg_users, m["name"], m["role"]) or m["first_granted"],
            "total": s.get("total") or 0,
            "locked": s.get("locked") or 0,
            "c30": s.get("c30") or 0,
            "c90": s.get("c90") or 0,
            "last_ts": s.get("last_ts"),
            "wikis": s.get("wikis") or 0,
            "last": {
                "wiki": lr["wiki"], "domain": lr["domain"] or "", "log_type": lr["log_type"],
                "log_action": lr["log_action"], "title": lr["title"], "ts": lr["ts"],
            } if lr else None,
        })
    return {"totals": totals, "users": users, "monthly": monthly}


def period(start, end):
    # counts for a custom date range. both ends are inclusive days
    start = valid_date(start) or "2001-01-01"
    end = valid_date(end) or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sub = (
        f"(SELECT a.actor, a.log_timestamp AS ts, {locked} AS lk {from_sql} "
        "WHERE a.log_timestamp >= %s AND a.log_timestamp < DATE_ADD(%s, INTERVAL 1 DAY)) x"
    )
    args = [start + " 00:00:00", end]
    per_user = db.rows(f"SELECT actor, SUM(lk = 0) AS n, SUM(lk = 1) AS locked FROM {sub} GROUP BY actor", args)
    monthly = db.rows(f"SELECT EXTRACT(YEAR_MONTH FROM ts) AS ym, COUNT(*) AS c FROM {sub} WHERE lk = 0 GROUP BY ym ORDER BY ym", args)
    return {
        "from": start,
        "to": end,
        "total": sum(int(r["n"] or 0) for r in per_user),
        "locked": sum(int(r["locked"] or 0) for r in per_user),
        "users": {r["actor"]: int(r["n"] or 0) for r in per_user},
        "monthly": monthly,
    }


def user_detail(name):
    prof = db.one("SELECT name, first_granted, role FROM gs_users WHERE name = %s AND is_current = 1", [name])
    if not prof:
        return None
    base = f"(SELECT a.wiki, a.log_type, a.log_action, a.log_timestamp AS ts, {locked} AS lk {from_sql} WHERE a.actor = %s) x"
    summary = db.one(
        "SELECT SUM(lk = 0) AS total, SUM(lk = 1) AS locked, "
        "MAX(ts) AS last_ts, MIN(CASE WHEN lk = 0 THEN ts END) AS first_ts, "
        "SUM(lk = 0 AND ts >= UTC_TIMESTAMP() - INTERVAL 30 DAY) AS c30, "
        "SUM(lk = 0 AND ts >= UTC_TIMESTAMP() - INTERVAL 90 DAY) AS c90, "
        "SUM(lk = 0 AND ts >= UTC_TIMESTAMP() - INTERVAL 365 DAY) AS c365 "
        f"FROM {base}",
        [name],
    )
    by_type = db.rows(f"SELECT log_type, log_action, COUNT(*) AS n FROM {base} WHERE lk = 0 GROUP BY log_type, log_action ORDER BY n DESC", [name])
    by_wiki = db.rows(
        "SELECT x.wiki, w.domain, w.is_gs, x.lk, x.n, x.last_ts FROM "
        f"(SELECT wiki, lk, COUNT(*) AS n, MAX(ts) AS last_ts FROM {base} GROUP BY wiki, lk) x "
        "LEFT JOIN gs_wikis w ON w.dbname = x.wiki ORDER BY x.n DESC",
        [name],
    )
    monthly = db.rows(f"SELECT EXTRACT(YEAR_MONTH FROM ts) AS ym, COUNT(*) AS c FROM {base} WHERE lk = 0 GROUP BY ym ORDER BY ym", [name])
    heat = db.rows(f"SELECT DAYOFWEEK(ts) AS d, HOUR(ts) AS h, COUNT(*) AS n FROM {base} WHERE lk = 0 GROUP BY d, h", [name])
    for w in by_wiki:
        w["domain"] = w["domain"] or ""
    return {
        "name": name,
        "role": prof["role"],
        "first_granted": prof["first_granted"],
        "role_since": rights.role_since(config_users(), name, prof["role"]) or prof["first_granted"],
        "summary": summary,
        "by_type": by_type,
        "by_wiki": by_wiki,
        "monthly": monthly,
        "heat": heat,
    }


# ------------------------------------------------------------------ projects

def wiki_info():
    return {
        r["dbname"]: {"is_gs": int(r["is_gs"] or 0), "is_locked": int(r["is_locked"] or 0), "domain": r["domain"] or ""}
        for r in db.rows("SELECT dbname, domain, is_gs, is_locked FROM gs_wikis")
    }


def projects_live():
    stats = {
        r["wiki"]: r
        for r in db.rows(
            "SELECT a.wiki, COUNT(*) AS total, COUNT(DISTINCT a.actor) AS users, MAX(a.log_timestamp) AS last_ts "
            "FROM gs_actions a JOIN gs_users u ON u.name = a.actor AND u.is_current = 1 GROUP BY a.wiki"
        )
    }
    out = []
    for w in db.rows(
        "SELECT dbname, domain, is_gs, is_locked FROM gs_wikis "
        "WHERE is_gs = 1 OR dbname IN (SELECT DISTINCT wiki FROM gs_actions) ORDER BY dbname"
    ):
        s = stats.get(w["dbname"], {})
        out.append({
            "dbname": w["dbname"],
            "domain": w["domain"],
            # closed wikis drop out of the wikiset but they were gs wikis
            "is_gs": 1 if (w["is_gs"] or w["is_locked"]) else 0,
            "is_locked": w["is_locked"],
            "total": s.get("total") or 0,
            "users": s.get("users") or 0,
            "last_ts": s.get("last_ts"),
        })
    return out


def project_live(dbname):
    w = db.one("SELECT dbname, domain, is_gs, is_locked FROM gs_wikis WHERE dbname = %s", [dbname])
    if not w:
        return None
    base = f"(SELECT a.actor, u.role, a.log_type, a.log_action, a.log_timestamp AS ts {from_sql} WHERE a.wiki = %s) x"
    summary = db.one(
        "SELECT COUNT(*) AS total, MAX(ts) AS last_ts, MIN(ts) AS first_ts, COUNT(DISTINCT actor) AS users, "
        "SUM(ts >= UTC_TIMESTAMP() - INTERVAL 30 DAY) AS c30, "
        "SUM(ts >= UTC_TIMESTAMP() - INTERVAL 90 DAY) AS c90, "
        f"SUM(ts >= UTC_TIMESTAMP() - INTERVAL 365 DAY) AS c365 FROM {base}",
        [dbname],
    )
    users = db.rows(f"SELECT actor, MAX(role) AS role, COUNT(*) AS n, MAX(ts) AS last_ts FROM {base} GROUP BY actor ORDER BY n DESC, actor", [dbname])
    by_type = db.rows(f"SELECT log_type, log_action, COUNT(*) AS n FROM {base} GROUP BY log_type, log_action ORDER BY n DESC, log_type, log_action", [dbname])
    monthly = db.rows(f"SELECT EXTRACT(YEAR_MONTH FROM ts) AS ym, COUNT(*) AS c FROM {base} GROUP BY ym ORDER BY ym", [dbname])
    return {
        "dbname": w["dbname"],
        "domain": w["domain"] or "",
        "is_gs": 1 if (w["is_gs"] or w["is_locked"]) else 0,
        "is_locked": w["is_locked"],
        "summary": summary,
        "users": users,
        "by_type": by_type,
        "monthly": monthly,
    }


def all_projects():
    # every project page in four grouped queries, for backfill.py's summary step.
    # returns {dbname: same shape as project_live}, only for wikis with actions
    base = f"(SELECT a.wiki, a.actor, u.role, a.log_type, a.log_action, a.log_timestamp AS ts {from_sql}) x"
    out = {}
    for w in db.rows(
        "SELECT x.wiki, w.domain, w.is_gs, w.is_locked, COUNT(*) AS total, MAX(ts) AS last_ts, MIN(ts) AS first_ts, "
        "COUNT(DISTINCT actor) AS users, SUM(ts >= UTC_TIMESTAMP() - INTERVAL 30 DAY) AS c30, "
        "SUM(ts >= UTC_TIMESTAMP() - INTERVAL 90 DAY) AS c90, SUM(ts >= UTC_TIMESTAMP() - INTERVAL 365 DAY) AS c365 "
        f"FROM {base} LEFT JOIN gs_wikis w ON w.dbname = x.wiki GROUP BY x.wiki, w.domain, w.is_gs, w.is_locked"
    ):
        out[w["wiki"]] = {
            "dbname": w["wiki"],
            "domain": w["domain"] or "",
            "is_gs": 1 if (w["is_gs"] or w["is_locked"]) else 0,
            "is_locked": w["is_locked"] or 0,
            "summary": {k: w[k] for k in ("total", "last_ts", "first_ts", "users", "c30", "c90", "c365")},
            "users": [], "by_type": [], "monthly": [],
        }
    for r in db.rows(f"SELECT wiki, actor, MAX(role) AS role, COUNT(*) AS n, MAX(ts) AS last_ts FROM {base} GROUP BY wiki, actor ORDER BY wiki, n DESC, actor"):
        out[r.pop("wiki")]["users"].append(r)
    for r in db.rows(f"SELECT wiki, log_type, log_action, COUNT(*) AS n FROM {base} GROUP BY wiki, log_type, log_action ORDER BY wiki, n DESC, log_type, log_action"):
        out[r.pop("wiki")]["by_type"].append(r)
    for r in db.rows(f"SELECT wiki, EXTRACT(YEAR_MONTH FROM ts) AS ym, COUNT(*) AS c FROM {base} GROUP BY wiki, ym ORDER BY wiki, ym"):
        out[r.pop("wiki")]["monthly"].append(r)
    return out


def window_counts():
    # just the rolling "last n days" numbers, for the listener's hourly recount.
    # only reads the last year, so it stays on the timestamp index
    base = f"(SELECT a.wiki, a.actor, a.log_timestamp AS ts, {locked} AS lk {from_sql} WHERE a.log_timestamp >= UTC_TIMESTAMP() - INTERVAL 365 DAY) x"
    totals = db.one(
        "SELECT COALESCE(SUM(lk = 0 AND ts >= UTC_TIMESTAMP() - INTERVAL 1 DAY), 0) AS d1, "
        "COALESCE(SUM(lk = 0 AND ts >= UTC_TIMESTAMP() - INTERVAL 7 DAY), 0) AS d7, "
        f"COALESCE(SUM(lk = 0 AND ts >= UTC_TIMESTAMP() - INTERVAL 30 DAY), 0) AS d30 FROM {base}"
    )
    users = db.rows(
        "SELECT actor, SUM(lk = 0 AND ts >= UTC_TIMESTAMP() - INTERVAL 30 DAY) AS c30, "
        f"SUM(lk = 0 AND ts >= UTC_TIMESTAMP() - INTERVAL 90 DAY) AS c90 FROM {base} GROUP BY actor"
    )
    projects = db.rows(
        "SELECT wiki, SUM(ts >= UTC_TIMESTAMP() - INTERVAL 30 DAY) AS c30, "
        f"SUM(ts >= UTC_TIMESTAMP() - INTERVAL 90 DAY) AS c90, COUNT(*) AS c365 FROM {base} GROUP BY wiki"
    )
    return {
        "totals": totals,
        "users": {r.pop("actor"): r for r in users},
        "projects": {r.pop("wiki"): r for r in projects},
    }


def project_list(details):
    # the projects page list, from all_projects() plus gs wikis with no actions yet
    out = []
    for w in db.rows(
        "SELECT dbname, domain, is_gs, is_locked FROM gs_wikis "
        "WHERE is_gs = 1 OR dbname IN (SELECT DISTINCT wiki FROM gs_actions) ORDER BY dbname"
    ):
        s = (details.get(w["dbname"]) or {}).get("summary") or {}
        out.append({
            "dbname": w["dbname"],
            "domain": w["domain"],
            "is_gs": 1 if (w["is_gs"] or w["is_locked"]) else 0,
            "is_locked": w["is_locked"],
            "total": s.get("total") or 0,
            "users": s.get("users") or 0,
            "last_ts": s.get("last_ts"),
        })
    return out


# ------------------------------------------------------------------ year in review

def first_year():
    r = db.one("SELECT YEAR(MIN(log_timestamp)) AS y FROM gs_actions")
    return int(r["y"]) if r and r["y"] else datetime.now(timezone.utc).year


def year_review(year, name=None):
    # one calendar year, for the whole team or one person. closed/locked wikis are
    # counted on the side, like everywhere else
    if name and not db.one("SELECT name FROM gs_users WHERE name = %s AND is_current = 1", [name]):
        return None
    where = "WHERE a.log_timestamp >= %s AND a.log_timestamp < %s" + (" AND a.actor = %s" if name else "")
    args = [f"{year}-01-01", f"{year + 1}-01-01"] + ([name] if name else [])
    base = f"(SELECT a.actor, u.role, a.wiki, a.log_type, a.log_action, a.log_timestamp AS ts, {locked} AS lk {from_sql} {where}) x"
    totals = db.one(
        "SELECT SUM(lk = 0) AS total, SUM(lk = 1) AS locked, "
        "COUNT(DISTINCT CASE WHEN lk = 0 THEN DATE(ts) END) AS days, "
        "COUNT(DISTINCT CASE WHEN lk = 0 THEN wiki END) AS wikis, "
        f"COUNT(DISTINCT CASE WHEN lk = 0 THEN actor END) AS users FROM {base}",
        args,
    )
    monthly = db.rows(f"SELECT EXTRACT(YEAR_MONTH FROM ts) AS ym, COUNT(*) AS c FROM {base} WHERE lk = 0 GROUP BY ym ORDER BY ym", args)
    biggest = db.one(f"SELECT DATE(ts) AS day, COUNT(*) AS n FROM {base} WHERE lk = 0 GROUP BY day ORDER BY n DESC, day LIMIT 1", args)
    wikis = db.rows(f"SELECT wiki, COUNT(*) AS n FROM {base} WHERE lk = 0 GROUP BY wiki ORDER BY n DESC, wiki LIMIT 10", args)
    by_type = db.rows(f"SELECT log_type, log_action, COUNT(*) AS n FROM {base} WHERE lk = 0 GROUP BY log_type, log_action ORDER BY n DESC, log_type, log_action", args)
    people = [] if name else db.rows(
        f"SELECT actor, MAX(role) AS role, COUNT(*) AS n FROM {base} WHERE lk = 0 GROUP BY actor ORDER BY n DESC, actor", args
    )
    if biggest and biggest.get("day"):
        biggest["day"] = str(biggest["day"])[:10]
    return {
        "year": year, "name": name, "totals": totals, "monthly": monthly, "biggest_day": biggest,
        "wikis": wikis, "by_type": by_type, "people": people,
    }


def meta():
    members = db.rows("SELECT name, role FROM gs_users WHERE is_current = 1 ORDER BY name")
    wikis = db.rows(
        "SELECT dbname, domain, is_locked FROM gs_wikis "
        "WHERE is_gs = 1 OR dbname IN (SELECT DISTINCT wiki FROM gs_actions) ORDER BY domain"
    )
    updated = {r["k"]: r["v"] for r in db.rows("SELECT k, v FROM gs_meta WHERE k NOT LIKE 'bf:%' AND k <> 'live_cursor'")}
    return {"users": members, "wikis": wikis, "updated": updated}
