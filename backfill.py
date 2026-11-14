"""fills and maintains the gs_actions database on toolsdb.

commands (python3 backfill.py <command> --help for the options):

  init       create the database and tables
  sync       refresh the list of current stewards/global sysops and the gs/closed wikis
  backfill   read admin logs from the wiki replicas into gs_actions
  prune      drop rows that shouldn't be counted (former members, non-gs or private wikis,
             outside rights periods, while a local admin)
  update     sync + backfill of the last few days + prune. the scheduled job in toolforge.yaml runs this
  all        init + sync + full backfill + prune, for a fresh setup
  summary    work out the overview, users and project numbers into gs_summary

sync, backfill, prune, update and all finish with the summary step on their own,
so the web pages pick up the new numbers straight away.

on toolforge it runs from the built image, e.g. a one off job:
  toolforge jobs run --image tool-gs-steward-stats/tool-gs-steward-stats:latest \
      --command "backfill summary" --wait gs-summary
"""
import argparse
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import pymysql
import toolforge

from stats import logparams, people, rights, toolsdb, wikimedia
from stats.wikimedia import dec

# log types we keep. revision/log deletion and undeletion are actions under "delete"
admin_types = ("delete", "block", "protect", "merge", "import", "abusefilter")

# numbers the pages show, worked out once per sync. k is "overview",
# "projects" or "project:<dbname>", v is json
summary_table = """
    CREATE TABLE IF NOT EXISTS gs_summary (
        k VARCHAR(80) NOT NULL PRIMARY KEY,
        v LONGTEXT NOT NULL,
        updated_at DATETIME NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """

# namespace names per wiki domain, so each wiki's api is only asked once.
# used to be a json file in the home folder, the build service has no home folder
namespace_table = """
    CREATE TABLE IF NOT EXISTS gs_namespaces (
        domain VARCHAR(255) NOT NULL PRIMARY KEY,
        names MEDIUMTEXT NOT NULL,
        updated_at DATETIME NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """

schema = [
    """
    CREATE TABLE IF NOT EXISTS gs_users (
        name VARCHAR(255) NOT NULL PRIMARY KEY,
        first_granted DATETIME NULL,
        is_current TINYINT(1) NOT NULL DEFAULT 1,
        role VARCHAR(16) NOT NULL DEFAULT 'global-sysop',
        updated_at DATETIME NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS gs_wikis (
        dbname VARCHAR(64) NOT NULL PRIMARY KEY,
        domain VARCHAR(255) NOT NULL DEFAULT '',
        is_gs TINYINT(1) NOT NULL DEFAULT 0,
        is_locked TINYINT(1) NOT NULL DEFAULT 0,
        updated_at DATETIME NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS gs_actions (
        id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        wiki VARCHAR(64) NOT NULL,
        log_id BIGINT NOT NULL,
        actor VARCHAR(255) NOT NULL,
        log_type VARCHAR(32) NOT NULL,
        log_action VARCHAR(32) NOT NULL,
        log_timestamp DATETIME NOT NULL,
        namespace INT NOT NULL DEFAULT 0,
        title VARCHAR(512) NOT NULL DEFAULT '',
        comment TEXT NULL,
        params MEDIUMTEXT NULL,
        UNIQUE KEY uq_wiki_log (wiki, log_id),
        KEY idx_actor_ts (actor, log_timestamp),
        KEY idx_ts (log_timestamp),
        KEY idx_wiki_ts (wiki, log_timestamp),
        KEY idx_type (log_type)
    ) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS gs_meta (
        k VARCHAR(64) NOT NULL PRIMARY KEY,
        v VARCHAR(255) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    summary_table,
    namespace_table,
    people.table,
    # leftovers from older versions
    "DROP TABLE IF EXISTS gs_local_sysop",
    "DROP TABLE IF EXISTS gs_group_periods",
    "DROP TABLE IF EXISTS gs_local_periods",
]

insert_action = (
    "INSERT IGNORE INTO gs_actions "
    "(wiki, log_id, actor, log_type, log_action, log_timestamp, namespace, title, comment, params) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)


def now_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def init_schema(conn):
    with conn.cursor() as cur:
        for stmt in schema:
            cur.execute(stmt)
        try:  # tables from before roles were tracked
            cur.execute("ALTER TABLE gs_users ADD COLUMN role VARCHAR(16) NOT NULL DEFAULT 'global-sysop'")
        except pymysql.err.OperationalError:
            pass  # already there


def set_meta(conn, key, value=None):
    if value is None:
        value = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO gs_meta (k, v) VALUES (%s, %s) ON DUPLICATE KEY UPDATE v = VALUES(v)",
            (key, str(value)[:255]),
        )


def parse_ts(value):
    if not value:
        return None
    digits = re.sub(r"\D", "", str(value))[:14]
    if len(digits) < 8:
        return None
    try:
        return datetime.strptime(digits.ljust(14, "0"), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def allowed(rules, actor, wiki, when):
    # keep it only if made as steward/gs, and not while a local admin on that wiki
    r = rules.get(actor)
    if not r:
        return True
    if r["groups"] and not rights.in_periods(r["groups"], when):
        return False
    return not rights.in_periods(r["local"].get(wiki, []), when)


# ------------------------------------------------------------------ sync

def sync_wikis(conn):
    private = wikimedia.fetch_private()
    gs = wikimedia.fetch_gs_wikis() - private
    closed = wikimedia.fetch_closed() - private
    meta = toolforge.connect("meta")
    try:
        with meta.cursor() as cur:
            cur.execute("SELECT dbname, url FROM wiki")
            found = cur.fetchall()
    finally:
        meta.close()
    now = now_naive()
    seen = set()
    data = []
    for dbname, url in found:
        dbname = dec(dbname)
        seen.add(dbname)
        if dbname in private:
            continue
        domain = re.sub(r"^https?://", "", dec(url) or "").strip("/")
        data.append((dbname, domain, 1 if dbname in gs else 0, 1 if dbname in closed else 0, now))
    seen |= private
    for dbname in gs - seen:
        data.append((dbname, "", 1, 1 if dbname in closed else 0, now))
    for dbname in closed - seen - gs:
        data.append((dbname, "", 0, 1, now))
    with conn.cursor() as cur:
        # drop private wikis we might have saved before, prune then clears their rows
        cur.execute("DELETE FROM gs_wikis WHERE dbname IN (" + ", ".join(["%s"] * len(private)) + ")", sorted(private))
        cur.executemany(
            "INSERT INTO gs_wikis (dbname, domain, is_gs, is_locked, updated_at) VALUES (%s, %s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE domain = VALUES(domain), is_gs = VALUES(is_gs), "
            "is_locked = VALUES(is_locked), updated_at = VALUES(updated_at)",
            data,
        )
    set_meta(conn, "last_wiki_sync")


def sync_users(conn):
    # returns the names that weren't current before, they need a full backfill
    members = wikimedia.fetch_members()
    current = sorted(members)
    rules = rights.user_rules(wikimedia.fetch_config().get("users", {}), current)
    now = now_naive()
    with conn.cursor() as cur:
        cur.execute("SELECT name FROM gs_users WHERE is_current = 1")
        known = {r[0] for r in cur.fetchall()}
    conn.autocommit(False)
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE gs_users SET is_current = 0")
            for name in current:
                firsts = [f for f, _ in rules[name]["groups"]]
                cur.execute(
                    "INSERT INTO gs_users (name, first_granted, is_current, role, updated_at) VALUES (%s, %s, 1, %s, %s) "
                    "ON DUPLICATE KEY UPDATE first_granted = VALUES(first_granted), is_current = 1, "
                    "role = VALUES(role), updated_at = VALUES(updated_at)",
                    (name, min(firsts) if firsts else None, members[name], now),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.autocommit(True)
    set_meta(conn, "last_user_sync")
    return sorted(set(current) - known)


# ------------------------------------------------------------------ backfill

_ns_cache = {}
_ns_new = set()
_ns_lock = threading.Lock()


def load_ns(conn):
    # everything we already know, read once before the wikis are fetched
    with conn.cursor() as cur:
        cur.execute(namespace_table)  # for setups made before this table existed
        cur.execute("SELECT domain, names FROM gs_namespaces")
        rows = cur.fetchall()
    with _ns_lock:
        for domain, names in rows:
            try:
                _ns_cache[domain] = json.loads(names)
            except ValueError:
                pass


def save_ns(conn):
    # only the domains we had to ask the api about this run
    with _ns_lock:
        found = [(d, json.dumps(_ns_cache[d], ensure_ascii=False)) for d in _ns_new if d in _ns_cache]
        _ns_new.clear()
    if not found:
        return
    now = now_naive().replace(microsecond=0)
    with conn.cursor() as cur:
        cur.executemany(
            "REPLACE INTO gs_namespaces (domain, names, updated_at) VALUES (%s, %s, %s)",
            [(d, names, now) for d, names in found],
        )


def ns_names(domain):
    # worker threads call this, so it only touches memory. load_ns and
    # save_ns do the db part
    if not domain:
        return {}
    with _ns_lock:
        hit = _ns_cache.get(domain)
    if hit:
        return {int(k): v for k, v in hit.items()}
    try:
        data = wikimedia.get(
            f"https://{domain}/w/api.php",
            {"action": "query", "meta": "siteinfo", "siprop": "namespaces", "format": "json", "formatversion": 2},
            timeout=15,
        ).json()["query"]["namespaces"]
        items = data.values() if isinstance(data, dict) else data
        out = {int(n["id"]): n.get("name", "") for n in items}
    except Exception:
        return {}
    with _ns_lock:
        _ns_cache[domain] = {str(k): v for k, v in out.items()}
        _ns_new.add(domain)
    return out


def full_title(ns, title, names):
    t = (title or "").replace("_", " ")
    if ns == 0:
        return t
    prefix = names.get(ns)
    return f"{prefix if prefix is not None else 'ns' + str(ns)}:{t}"


def fetch_wiki(dbname, domain, rules, since):
    started = time.time()
    names = list(rules)
    type_ph = ",".join(["%s"] * len(admin_types))
    conn = toolforge.connect(dbname + "_p")
    try:
        with conn.cursor() as cur:
            # actor ids first, so the logging query can use the log_actor index
            cur.execute("SELECT actor_id, actor_name FROM actor WHERE actor_name IN (" + ",".join(["%s"] * len(names)) + ")", tuple(names))
            actors = {int(i): dec(n) for i, n in cur.fetchall()}
            if not actors:
                return [], time.time() - started
            id_ph = ",".join(["%s"] * len(actors))
            cur.execute(
                f"""
                SELECT l.log_id, l.log_actor, l.log_type, l.log_action, l.log_timestamp,
                       l.log_namespace, l.log_title, c.comment_text, l.log_params
                FROM logging_userindex l
                LEFT JOIN comment_logging c ON c.comment_id = l.log_comment_id
                WHERE l.log_actor IN ({id_ph})
                AND l.log_type IN ({type_ph})
                AND l.log_timestamp >= %s
                """,
                tuple(actors) + admin_types + (since,),
            )
            raw = cur.fetchall()
    finally:
        conn.close()  # closed before this worker moves on to the next wiki
    keep = []
    for log_id, actor_id, ltype, laction, lts, ns, title, comment, params in raw:
        actor = actors.get(int(actor_id))
        ts = parse_ts(dec(lts))
        if actor is None or ts is None or not allowed(rules, actor, dbname, ts):
            continue
        keep.append((log_id, actor, ltype, laction, ts, int(ns or 0), title, comment, params))
    # only ask the api for namespace names when a title actually needs a prefix
    names = ns_names(domain) if any(k[5] != 0 for k in keep) else {}
    out = [
        (dbname, int(log_id), actor, dec(ltype), dec(laction), ts, ns,
         full_title(ns, dec(title), names)[:512], dec(comment), logparams.to_json(params))
        for log_id, actor, ltype, laction, ts, ns, title, comment, params in keep
    ]
    return out, time.time() - started


def backfill(conn, only_users=None, only_wikis=None, since=None, workers=4, resume=False, after=None, locked_only=False):
    with conn.cursor() as cur:
        cur.execute("SELECT name FROM gs_users WHERE is_current = 1")
        users = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT dbname, domain, is_locked FROM gs_wikis WHERE is_gs = 1 OR is_locked = 1 ORDER BY dbname")
        wiki_rows = cur.fetchall()
        cur.execute("SELECT k FROM gs_meta WHERE k LIKE 'bf:%'")
        finished = {r[0][3:] for r in cur.fetchall()}
    names = [n for n in users if not only_users or n in only_users]
    rules = rights.user_rules(wikimedia.fetch_config().get("users", {}), names)
    wikis = [(d, dom) for d, dom, lk in wiki_rows if (not only_wikis or d in only_wikis) and (lk or not locked_only)]

    # the bf:<wiki> markers are only for resuming a full backfill of everyone.
    # partial or incremental runs neither use nor touch them
    full_run = since is None and not only_users
    if resume:
        wikis = [(d, dom) for d, dom in wikis if d not in finished]
    elif full_run and not only_wikis:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM gs_meta WHERE k LIKE 'bf:%'")
    if after:
        wikis = [(d, dom) for d, dom in wikis if d > after]
    if not rules or not wikis:
        print("Nothing to do")
        return 0

    if not since:
        # from the earliest grant we know of, or everything if someone has no history
        firsts = [min(f for f, _ in r["groups"]) for r in rules.values() if r["groups"]]
        since = "20010101000000" if len(firsts) < len(rules) else min(firsts).strftime("%Y%m%d%H%M%S")

    load_ns(conn)
    total = done = 0
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        jobs = {pool.submit(fetch_wiki, d, dom, rules, since): d for d, dom in wikis}
        for job in as_completed(jobs):
            dbname = jobs[job]
            done += 1
            try:
                found, secs = job.result()
            except Exception as e:
                print(f"[{done}/{len(wikis)}] {dbname} skipped: {str(e)[:90]}", file=sys.stderr)
                continue
            t1 = time.time()
            with conn.cursor() as cur:
                for i in range(0, len(found), 1000):
                    cur.executemany(insert_action, found[i:i + 1000])
            if full_run:
                set_meta(conn, "bf:" + dbname)
            total += len(found)
            print(f"[{done}/{len(wikis)}] {dbname}: {len(found)} rows (fetch {secs:.1f}s, insert {time.time() - t1:.1f}s)", flush=True)
    except KeyboardInterrupt:
        print(f"\nStopped after {done} wikis. Finished wikis are saved, carry on with: backfill --resume", flush=True)
        save_ns(conn)
        pool.shutdown(wait=False, cancel_futures=True)
        os._exit(130)  # workers may be stuck in a db call, don't wait for them
    pool.shutdown(wait=True)
    save_ns(conn)
    set_meta(conn, "last_backfill")
    print(f"Fetched {total} rows")
    return total


# ------------------------------------------------------------------ prune

def prune(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT name FROM gs_users WHERE is_current = 1")
        names = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT COUNT(*) FROM gs_wikis")
        have_wikis = cur.fetchone()[0] > 0
    if not names:
        print("No current users, run sync first")
        return
    rules = rights.user_rules(wikimedia.fetch_config().get("users", {}), names)
    gone = offwiki = outside = local = 0
    with conn.cursor() as cur:
        cur.execute(
            "DELETE a FROM gs_actions a LEFT JOIN gs_users u ON u.name = a.actor AND u.is_current = 1 WHERE u.name IS NULL"
        )
        gone = cur.rowcount
        if have_wikis:
            cur.execute(
                "DELETE a FROM gs_actions a LEFT JOIN gs_wikis w ON w.dbname = a.wiki "
                "WHERE COALESCE(w.is_gs, 0) = 0 AND COALESCE(w.is_locked, 0) = 0"
            )
            offwiki = cur.rowcount
        for name, r in rules.items():
            if r["groups"]:
                conds, par = [], [name]
                for f, t in r["groups"]:
                    if t is None:
                        conds.append("log_timestamp >= %s")
                        par.append(f)
                    else:
                        conds.append("(log_timestamp >= %s AND log_timestamp < %s)")
                        par += [f, t]
                cur.execute("DELETE FROM gs_actions WHERE actor = %s AND NOT (" + " OR ".join(conds) + ")", par)
                outside += cur.rowcount
            for wiki, periods in r["local"].items():
                for f, t in periods:
                    if t is None:
                        cur.execute("DELETE FROM gs_actions WHERE actor = %s AND wiki = %s AND log_timestamp >= %s", (name, wiki, f))
                    else:
                        cur.execute(
                            "DELETE FROM gs_actions WHERE actor = %s AND wiki = %s AND log_timestamp >= %s AND log_timestamp < %s",
                            (name, wiki, f, t),
                        )
                    local += cur.rowcount
    print(f"Pruned {gone} rows of former users, {offwiki} on non-gs wikis, {outside} outside rights periods, {local} as local admin")


# ------------------------------------------------------------------ summary

def summarize():
    # same queries the web app would run, done once here and stored, so pages load
    # from one row and every worker sees the same numbers
    from stats import db, queries
    started = time.time()
    conn = toolsdb.connect()
    db.use(conn)
    try:
        with conn.cursor() as cur:
            cur.execute(summary_table)  # for setups made before this table existed
        details = queries.all_projects()
        found = [("overview", queries.overview_live()), ("projects", queries.project_list(details))]
        found += [("project:" + name, d) for name, d in details.items()]
        now = now_naive().replace(microsecond=0)  # the column has no fractions, so compare like for like
        with conn.cursor() as cur:
            cur.executemany(
                "REPLACE INTO gs_summary (k, v, updated_at) VALUES (%s, %s, %s)",
                [(k, json.dumps(v, ensure_ascii=False), now) for k, v in found],
            )
            # anything not written this time is stale, e.g. a wiki with no actions left
            cur.execute("DELETE FROM gs_summary WHERE updated_at < %s", (now,))
        set_meta(conn, "last_summary")
        print(f"Summary written: {len(found)} rows in {time.time() - started:.1f}s")
    finally:
        db.use(None)
        conn.close()


# ------------------------------------------------------------------ cli

def days_ago(n):
    return (datetime.now(timezone.utc) - timedelta(days=n)).strftime("%Y%m%d%H%M%S")


def main():
    p = argparse.ArgumentParser(description="keeps the gs_actions database on toolsdb filled", epilog="see the readme for examples")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="create the database and tables")
    sub.add_parser("sync", help="refresh current stewards/global sysops and the wiki list")
    sub.add_parser("prune", help="drop rows that shouldn't be counted")
    b = sub.add_parser("backfill", help="read admin logs from the replicas into gs_actions")
    b.add_argument("--user", action="append", help="only this user (can be given more than once)")
    b.add_argument("--wiki", action="append", help="only this wiki dbname (can be given more than once)")
    b.add_argument("--since", help="only actions from this date on, e.g. 2024-01-01")
    b.add_argument("--days", type=int, help="only actions from the last N days")
    b.add_argument("--workers", type=int, default=4, help="wikis read at the same time (default 4)")
    b.add_argument("--resume", action="store_true", help="skip wikis an earlier full backfill already finished")
    b.add_argument("--after", help="only wikis whose dbname sorts after this one")
    b.add_argument("--locked-only", action="store_true", help="only closed/locked wikis")
    u = sub.add_parser("update", help="sync, backfill the last few days, prune. run this from cron")
    u.add_argument("--days", type=int, default=3, help="how far back to look (default 3)")
    u.add_argument("--workers", type=int, default=4, help="wikis read at the same time (default 4)")
    sub.add_parser("all", help="init, sync, full backfill and prune, for a fresh setup")
    sub.add_parser("summary", help="work out the page numbers into gs_summary (the other commands do this at the end)")
    args = p.parse_args()

    if args.cmd in ("init", "all"):
        conn = toolsdb.connect(dict_rows=False, create=True)
        init_schema(conn)
        conn.close()
        print("Schema ready")
    conn = toolsdb.connect(dict_rows=False)
    try:
        if args.cmd in ("sync", "all"):
            new = sync_users(conn)
            sync_wikis(conn)
            print(f"Synced users and wikis, new users: {', '.join(new) or '(none)'}")
        if args.cmd == "backfill":
            since = None
            if args.since:
                since = re.sub(r"\D", "", args.since).ljust(14, "0")[:14]
            elif args.days:
                since = days_ago(args.days)
            backfill(
                conn,
                only_users=set(args.user) if args.user else None,
                only_wikis=set(args.wiki) if args.wiki else None,
                since=since,
                workers=args.workers,
                resume=args.resume,
                after=args.after,
                locked_only=args.locked_only,
            )
        if args.cmd == "all":
            backfill(conn)
        if args.cmd == "update":
            new = sync_users(conn)
            sync_wikis(conn)
            if new:
                print("New users, full backfill for:", ", ".join(new))
                backfill(conn, only_users=set(new), workers=args.workers)
            backfill(conn, since=days_ago(args.days), workers=args.workers)
            prune(conn)
            set_meta(conn, "last_update")
        if args.cmd in ("prune", "all"):
            prune(conn)
    finally:
        conn.close()
    if args.cmd != "init":
        summarize()


if __name__ == "__main__":
    main()
