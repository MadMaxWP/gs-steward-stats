import json
import time
from datetime import datetime, timedelta, timezone

from stats import db, pool, queries, settings

# the bits the update job (backfill.py) and the listener (listen.py) both need:
# gs_meta, rebuilding gs_summary, adding live actions to it, and dropping people
# who lost their rights.
#
# the summary has a lock (a mysql GET_LOCK) so a full rebuild and a live update
# never write over each other


def now_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def set_meta(c, key, value=None):
    with c.cursor() as cur:
        cur.execute(
            "INSERT INTO gs_meta (k, v) VALUES (%s, %s) ON DUPLICATE KEY UPDATE v = VALUES(v)",
            (key, str(iso_now() if value is None else value)[:1000]),
        )


def get_meta(key):
    r = db.one("SELECT v FROM gs_meta WHERE k = %s", [key], fresh=True)
    return r["v"] if r else None


def widen_meta():
    # the stream's resume id is longer than the old 255 limit
    r = db.one(
        "SELECT CHARACTER_MAXIMUM_LENGTH AS n FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'gs_meta' AND COLUMN_NAME = 'v'",
        fresh=True,
    )
    if r and (r["n"] or 0) < 1000:
        db.run("ALTER TABLE gs_meta MODIFY v VARCHAR(1000) NOT NULL")


def lock_name():
    return f"{settings.db_name}_summary"[:64]


class summary_lock:
    # holds its own connection for as long as the lock is held
    def __init__(self, wait=600):
        self.wait = wait

    def __enter__(self):
        self.p = pool.writer()
        self.c, self.born = self.p.take()
        try:
            with self.c.cursor() as cur:
                cur.execute("SELECT GET_LOCK(%s, %s)", (lock_name(), self.wait))
                got = cur.fetchone()[0]
        except Exception:
            self.p.give(self.c, self.born, broken=True)
            raise
        if got != 1:
            self.p.give(self.c, self.born)
            raise TimeoutError("summary is busy")
        return self

    def __exit__(self, *exc):
        broken = False
        try:
            with self.c.cursor() as cur:
                cur.execute("SELECT RELEASE_LOCK(%s)", (lock_name(),))
        except Exception:
            broken = True  # closing the connection lets go of the lock too
        self.p.give(self.c, self.born, broken)
        return False


# ------------------------------------------------------------------ full rebuild

def rebuild():
    # the same queries the pages would run, worked out once and stored, so pages
    # load from one row. the queries read from the primary (no read pool in jobs)
    started = time.time()
    with summary_lock():
        details = queries.all_projects()
        found = [("overview", queries.overview_live()), ("projects", queries.project_list(details))]
        found += [("project:" + name, d) for name, d in details.items()]
        now = now_naive()

        def save(c):
            with c.cursor() as cur:
                cur.executemany(
                    "REPLACE INTO gs_summary (k, v, updated_at) VALUES (%s, %s, %s)",
                    [(k, json.dumps(v, ensure_ascii=False), now) for k, v in found],
                )
                # anything not written this time is stale, e.g. a wiki with no actions left
                cur.execute("DELETE FROM gs_summary WHERE updated_at < %s", (now,))
            set_meta(c, "last_summary")
            set_meta(c, "last_recount")
        db.write(save)
    return len(found), time.time() - started


# ------------------------------------------------------------------ live updates

insert_live = (
    "INSERT INTO gs_actions (wiki, log_id, actor, log_type, log_action, log_timestamp, namespace, title, comment, params) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
    # the replica copy from backfill.py wins, the live one never overwrites it
    "ON DUPLICATE KEY UPDATE id = id"
)


def fetch_rows(cur, sql, args=None):
    cur.execute(sql, args)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def save_live(rows, cursor=None):
    # rows are dicts from the listener. one connection, one transaction: the summary
    # lock, the new rows, the summary changes and the stream place (cursor) all go
    # in together, so the place is never ahead of what's saved. returns how many were new
    if not rows:
        return 0

    def go(c):
        with c.cursor() as cur:
            cur.execute("SELECT GET_LOCK(%s, 120)", (lock_name(),))
            if cur.fetchone()[0] != 1:
                raise TimeoutError("summary is busy")
        try:
            c.autocommit(False)
            try:
                n = _save_live(c, rows)
                if cursor:
                    set_meta(c, "live_cursor", cursor)
                c.commit()
                return n
            except BaseException:
                c.rollback()
                raise
            finally:
                c.autocommit(True)
        finally:
            with c.cursor() as cur:
                cur.execute("SELECT RELEASE_LOCK(%s)", (lock_name(),))
    return pool.writer().retry(go)


def _save_live(c, rows):
    with c.cursor() as cur:
        actors = sorted({r["actor"] for r in rows})
        wikis = sorted({r["wiki"] for r in rows})
        team = {
            r["name"]: r["role"] for r in fetch_rows(
                cur, "SELECT name, role FROM gs_users WHERE is_current = 1 AND name IN (" + ",".join(["%s"] * len(actors)) + ")", actors)
        }
        info = {
            r["dbname"]: r for r in fetch_rows(
                cur, "SELECT dbname, domain, is_gs, is_locked FROM gs_wikis WHERE dbname IN (" + ",".join(["%s"] * len(wikis)) + ")", wikis)
        }
        # new members aren't in gs_users yet, the update job does their whole history.
        # wikis we don't count are left out the same way backfill.py leaves them out
        keep = [
            r for r in rows
            if r["actor"] in team and r["wiki"] in info and (info[r["wiki"]]["is_gs"] or info[r["wiki"]]["is_locked"])
        ]
        if not keep:
            return 0
        conds = " OR ".join(["(wiki = %s AND log_id = %s)"] * len(keep))
        cur.execute(f"SELECT wiki, log_id FROM gs_actions WHERE {conds}", [x for r in keep for x in (r["wiki"], r["log_id"])])
        have = {(w, int(i)) for w, i in cur.fetchall()}
        new = [r for r in keep if (r["wiki"], int(r["log_id"])) not in have]
        cur.executemany(insert_live, [
            (r["wiki"], r["log_id"], r["actor"], r["log_type"], r["log_action"], r["when"], r["namespace"],
             r["title"][:512], r["comment"], r["params"])
            for r in keep
        ])
        if new:
            add_to_summary(cur, new, team, info)
            set_meta(c, "last_live")
    return len(new)


def load_summary(cur, keys):
    found = fetch_rows(cur, "SELECT k, v FROM gs_summary WHERE k IN (" + ",".join(["%s"] * len(keys)) + ") FOR UPDATE", keys)
    return {r["k"]: json.loads(r["v"]) for r in found}


def bump(items, match, make, field="c"):
    for it in items:
        if all(it.get(k) == v for k, v in match.items()):
            it[field] = (it.get(field) or 0) + 1
            return it
    it = {**match, **make, field: 1}
    items.append(it)
    return it


def later(a, b):
    return max(x for x in (a, b) if x) if (a or b) else None


def sooner(a, b):
    return min(x for x in (a, b) if x) if (a or b) else None


def add_to_summary(cur, new, team, info):
    keys = ["overview", "projects"] + ["project:" + w for w in sorted({r["wiki"] for r in new})]
    have = load_summary(cur, keys)
    if "overview" not in have:
        return  # no summary made yet, pages work it out live until the first rebuild
    ov = have["overview"]
    plist = have.get("projects") or []
    users = {u["name"]: u for u in ov.get("users") or []}
    totals = ov.setdefault("totals", {})
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    changed = {"overview", "projects"}

    for r in sorted(new, key=lambda r: r["ts"]):
        w = info[r["wiki"]]
        lk = 1 if w["is_locked"] else 0
        age = now - r["when"]
        ym = int(r["when"].strftime("%Y%m"))
        role = team[r["actor"]]

        # the wiki's own page
        key = "project:" + r["wiki"]
        pr = have.get(key)
        if pr is None:
            pr = have[key] = {
                "dbname": r["wiki"], "domain": w["domain"] or "", "is_gs": 1 if (w["is_gs"] or w["is_locked"]) else 0,
                "is_locked": lk, "summary": {"total": 0, "last_ts": None, "first_ts": None, "users": 0, "c30": 0, "c90": 0, "c365": 0},
                "users": [], "by_type": [], "monthly": [],
            }
        changed.add(key)
        first_here = not any(u["actor"] == r["actor"] for u in pr["users"])
        s = pr["summary"]
        s["total"] = (s.get("total") or 0) + 1
        s["last_ts"] = later(s.get("last_ts"), r["ts"])
        s["first_ts"] = sooner(s.get("first_ts"), r["ts"])
        for k, days in (("c30", 30), ("c90", 90), ("c365", 365)):
            if age <= timedelta(days=days):
                s[k] = (s.get(k) or 0) + 1
        pu = bump(pr["users"], {"actor": r["actor"]}, {"role": role, "last_ts": None}, "n")
        pu["role"] = role
        pu["last_ts"] = later(pu.get("last_ts"), r["ts"])
        s["users"] = len(pr["users"])
        pr["users"].sort(key=lambda u: (-u["n"], u["actor"]))
        bump(pr["by_type"], {"log_type": r["log_type"], "log_action": r["log_action"]}, {}, "n")
        pr["by_type"].sort(key=lambda t: (-t["n"], t["log_type"], t["log_action"]))
        bump(pr["monthly"], {"ym": ym}, {})
        pr["monthly"].sort(key=lambda m: m["ym"])

        # the projects list
        row = next((p for p in plist if p["dbname"] == r["wiki"]), None)
        if row is None:
            row = {"dbname": r["wiki"], "domain": w["domain"] or "", "is_gs": pr["is_gs"], "is_locked": lk, "total": 0, "users": 0, "last_ts": None}
            plist.append(row)
            plist.sort(key=lambda p: p["dbname"])
        row["total"] = s["total"]
        row["users"] = s["users"]
        row["last_ts"] = s["last_ts"]

        # the overview
        totals["last_ts"] = later(totals.get("last_ts"), r["ts"])
        u = users.get(r["actor"])
        if lk:
            totals["locked"] = (totals.get("locked") or 0) + 1
        else:
            totals["total"] = (totals.get("total") or 0) + 1
            for k, days in (("d1", 1), ("d7", 7), ("d30", 30)):
                if age <= timedelta(days=days):
                    totals[k] = (totals.get(k) or 0) + 1
            bump(ov.setdefault("monthly", []), {"ym": ym}, {})
            ov["monthly"].sort(key=lambda m: m["ym"])
        if u is not None:
            if lk:
                u["locked"] = (u.get("locked") or 0) + 1
            else:
                u["total"] = (u.get("total") or 0) + 1
                for k, days in (("c30", 30), ("c90", 90)):
                    if age <= timedelta(days=days):
                        u[k] = (u.get(k) or 0) + 1
                if first_here:
                    u["wikis"] = (u.get("wikis") or 0) + 1
            if not u.get("last_ts") or r["ts"] >= u["last_ts"]:
                u["last_ts"] = r["ts"]
                u["last"] = {
                    "wiki": r["wiki"], "domain": w["domain"] or "", "log_type": r["log_type"],
                    "log_action": r["log_action"], "title": r["title"], "ts": r["ts"],
                }

    have["projects"] = plist
    stamp = now_naive()
    cur.executemany(
        "REPLACE INTO gs_summary (k, v, updated_at) VALUES (%s, %s, %s)",
        [(k, json.dumps(have[k], ensure_ascii=False), stamp) for k in changed],
    )


# ------------------------------------------------------------------ rolling windows

def recount():
    # the "last 30 days" style numbers go down as time passes, nothing new has to
    # happen for that. this works them out again from the last year of actions only
    # (uses the timestamp index), and leaves everything else in the summary alone
    with summary_lock():
        if not db.one("SELECT k FROM gs_summary WHERE k = 'overview'", fresh=True):
            return 0
        win = queries.window_counts()
        return db.write(lambda c: _recount(c, win))


def _recount(c, win):
    with c.cursor() as cur:
        cur.execute("SELECT k FROM gs_summary WHERE k LIKE 'project:%'")
        keys = [r[0] for r in cur.fetchall()]
        have = load_summary(cur, ["overview"] + keys)
        ov = have["overview"]
        ov.setdefault("totals", {}).update(win["totals"])
        for u in ov.get("users") or []:
            got = win["users"].get(u["name"], {})
            u["c30"], u["c90"] = got.get("c30", 0), got.get("c90", 0)
        # the chart keeps 24 whole months
        first = int((datetime.now(timezone.utc).replace(day=1) - timedelta(days=700)).strftime("%Y%m"))
        ov["monthly"] = [m for m in ov.get("monthly") or [] if m["ym"] >= first]
        for k in keys:
            got = win["projects"].get(k[8:], {})
            have[k].setdefault("summary", {}).update({n: got.get(n, 0) for n in ("c30", "c90", "c365")})
        stamp = now_naive()
        cur.executemany(
            "UPDATE gs_summary SET v = %s, updated_at = %s WHERE k = %s",
            [(json.dumps(v, ensure_ascii=False), stamp, k) for k, v in have.items()],
        )
    set_meta(c, "last_recount")
    return len(have)


# ------------------------------------------------------------------ people who left

def drop_users(names):
    # someone lost steward/gs: stop counting them straight away. if they come back
    # the update job sees them as new and reads their whole history again
    if not names:
        return 0
    ph = ",".join(["%s"] * len(names))
    # the pages leave them out as soon as this is done
    db.run(f"UPDATE gs_users SET is_current = 0 WHERE name IN ({ph})", names)
    gone = 0
    while True:
        # in chunks, someone with a long history can have a lot of rows
        n = db.run(f"DELETE FROM gs_actions WHERE actor IN ({ph}) LIMIT 5000", names)
        gone += n
        if n < 5000:
            break
    rebuild()
    return gone
