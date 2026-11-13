from datetime import datetime, timedelta, timezone

import toolforge
from flask import Blueprint, jsonify, request

from stats import logparams, rights
from stats.cache import cached
from stats.wikimedia import dec, fetch_config, fetch_members

# steward stats, read live from the metawiki replica. nothing is stored, the
# answers are cached for a bit (15 min summary, 5 min lists). these numbers are
# kept apart from the gs actions in gs_actions

bp = Blueprint("stewards", __name__)

# category -> log_type on meta
log_cats = {
    "gblock": "gblblock",
    "glock": "globalauth",
    "grename": "gblrename",
    "grights": "gblrights",
    "rights": "rights",
    "filter": "abusefilter",
}
type_to_cat = {v: k for k, v in log_cats.items()}
cat_labels = {
    "gblock": "Global blocks",
    "glock": "Global locks",
    "grename": "Global renames",
    "grights": "Global rights",
    "rights": "Rights changes",
    "filter": "AbuseFilter edits",
    "sr": "SR page edits",
}

# steward request pages and noticeboards
sr_pages = [32244, 130130, 164533, 135805, 31937, 84820, 9476, 117752, 167407]
sr_minor_page = 13356

namespaces = {
    0: "", 1: "Talk", 2: "User", 3: "User talk", 4: "Meta", 5: "Meta talk", 6: "File", 7: "File talk",
    8: "MediaWiki", 9: "MediaWiki talk", 10: "Template", 11: "Template talk", 12: "Help", 13: "Help talk",
    14: "Category", 15: "Category talk", 828: "Module", 829: "Module talk",
}


def to_iso(ts):
    s = dec(ts)
    if not s:
        return None
    s = str(s)
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}T{s[8:10]}:{s[10:12]}:{s[12:14]}Z"


def full_title(ns, title):
    t = (dec(title) or "").replace("_", " ")
    ns = int(ns or 0)
    if ns == 0:
        return t
    return f"{namespaces.get(ns, 'ns' + str(ns))}:{t}"


def meta_conn():
    return toolforge.connect("metawiki_p")


def sr_titles():
    # {full title: minor edits count?} for the sr pages. the live feed only gets
    # titles from the event stream, not page ids, so it matches on these
    conn = meta_conn()
    try:
        with conn.cursor() as cur:
            ids = sr_pages + [sr_minor_page]
            cur.execute(
                "SELECT page_id, page_namespace, page_title FROM page WHERE page_id IN (" + ",".join(["%s"] * len(ids)) + ")",
                ids,
            )
            return {full_title(ns, t): int(pid) != sr_minor_page for pid, ns, t in cur.fetchall()}
    finally:
        conn.close()


def steward_periods(cfg, name):
    # steward terms as 14 digit timestamps, [] means we don't know so don't limit
    hist = (((cfg.get("users") or {}).get(name) or {}).get("global_group_history")) or {}
    out = []
    for f, t in rights.periods_for(hist.get("steward")):
        out.append((f.strftime("%Y%m%d%H%M%S"), t.strftime("%Y%m%d%H%M%S") if t else None))
    return out


def period_sql(col, periods):
    if not periods:
        return "1=1", []
    conds, par = [], []
    for f, t in periods:
        if t is None:
            conds.append(f"{col} >= %s")
            par.append(f)
        else:
            conds.append(f"({col} >= %s AND {col} < %s)")
            par += [f, t]
    return "(" + " OR ".join(conds) + ")", par


def actor_id(cur, name):
    cur.execute("SELECT actor_id FROM actor WHERE actor_name = %s", (name,))
    r = cur.fetchone()
    return int(r[0]) if r else None


def rev_filter(prefix, aid, periods):
    # where clause for sr page edits
    ph = ",".join(["%s"] * len(sr_pages))
    pq, ppar = period_sql(f"{prefix}rev_timestamp", periods)
    sql = (
        f"{prefix}rev_actor = %s AND ({prefix}rev_page IN ({ph}) "
        f"OR ({prefix}rev_page = %s AND {prefix}rev_minor_edit = 0)) AND {pq}"
    )
    return sql, [aid, *sr_pages, sr_minor_page, *ppar]


def build_summary(name, periods):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    since = [(now - timedelta(days=d)).strftime("%Y%m%d%H%M%S") for d in (30, 90, 365)]
    types = list(type_to_cat)
    tph = ",".join(["%s"] * len(types))
    lp, lpar = period_sql("log_timestamp", periods)

    counts = {c: 0 for c in cat_labels}
    windows = [0, 0, 0]
    last = None
    monthly = {}

    def add_window(a, b, c):
        windows[0] += int(a or 0)
        windows[1] += int(b or 0)
        windows[2] += int(c or 0)

    conn = meta_conn()
    try:
        with conn.cursor() as cur:
            aid = actor_id(cur, name)
            if aid is not None:
                cur.execute(
                    "SELECT log_type, COUNT(*), MAX(log_timestamp), "
                    "SUM(log_timestamp >= %s), SUM(log_timestamp >= %s), SUM(log_timestamp >= %s) "
                    f"FROM logging_userindex WHERE log_actor = %s AND log_type IN ({tph}) AND {lp} "
                    "GROUP BY log_type",
                    (*since, aid, *types, *lpar),
                )
                for lt, n, mx, a, b, c in cur.fetchall():
                    counts[type_to_cat[dec(lt)]] = int(n)
                    mx = dec(mx)
                    if mx and (last is None or mx > last):
                        last = mx
                    add_window(a, b, c)
                cur.execute(
                    f"SELECT LEFT(log_timestamp, 6), COUNT(*) FROM logging_userindex "
                    f"WHERE log_actor = %s AND log_type IN ({tph}) AND {lp} GROUP BY 1",
                    (aid, *types, *lpar),
                )
                for ym, n in cur.fetchall():
                    monthly[int(dec(ym))] = monthly.get(int(dec(ym)), 0) + int(n)

                rsql, rpar = rev_filter("", aid, periods)
                cur.execute(
                    "SELECT COUNT(*), MAX(rev_timestamp), SUM(rev_timestamp >= %s), "
                    "SUM(rev_timestamp >= %s), SUM(rev_timestamp >= %s) "
                    f"FROM revision_userindex WHERE {rsql}",
                    (*since, *rpar),
                )
                n, mx, a, b, c = cur.fetchone()
                counts["sr"] = int(n or 0)
                mx = dec(mx)
                if mx and (last is None or mx > last):
                    last = mx
                add_window(a, b, c)
                cur.execute(f"SELECT LEFT(rev_timestamp, 6), COUNT(*) FROM revision_userindex WHERE {rsql} GROUP BY 1", rpar)
                for ym, n in cur.fetchall():
                    monthly[int(dec(ym))] = monthly.get(int(dec(ym)), 0) + int(n)
    finally:
        conn.close()

    by_cat = sorted(({"cat": k, "label": cat_labels[k], "n": v} for k, v in counts.items()), key=lambda x: -x["n"])
    return {
        "name": name,
        "total": sum(counts.values()),
        "counts": counts,
        "by_cat": by_cat,
        "last_ts": to_iso(last),
        "c30": windows[0],
        "c90": windows[1],
        "c365": windows[2],
        "monthly": [{"ym": k, "c": monthly[k]} for k in sorted(monthly)],
        "periods_known": bool(periods),
    }


def build_rows(name, periods, cat, page, per):
    offset = (page - 1) * per
    limit = offset + per  # each side of the union only needs this many newest rows
    branches, params = [], []
    conn = meta_conn()
    try:
        with conn.cursor() as cur:
            aid = actor_id(cur, name)
            if aid is None:
                return []
            if cat == "all" or cat in log_cats:
                types = list(log_cats.values()) if cat == "all" else [log_cats[cat]]
                ph = ",".join(["%s"] * len(types))
                lp, lpar = period_sql("l.log_timestamp", periods)
                branches.append(
                    "(SELECT 'log' AS src, l.log_id AS sid, l.log_type AS ltype, l.log_action AS laction, "
                    "l.log_timestamp AS ts, l.log_namespace AS ns, l.log_title AS title, "
                    "c.comment_text AS cmt, l.log_params AS params "
                    "FROM logging_userindex l LEFT JOIN comment_logging c ON c.comment_id = l.log_comment_id "
                    f"WHERE l.log_actor = %s AND l.log_type IN ({ph}) AND {lp} "
                    "ORDER BY l.log_timestamp DESC LIMIT %s)"
                )
                params += [aid, *types, *lpar, limit]
            if cat in ("all", "sr"):
                rsql, rpar = rev_filter("r.", aid, periods)
                branches.append(
                    "(SELECT 'rev' AS src, r.rev_id AS sid, CAST('sr' AS BINARY) AS ltype, "
                    "CAST('edit' AS BINARY) AS laction, r.rev_timestamp AS ts, p.page_namespace AS ns, "
                    "p.page_title AS title, c.comment_text AS cmt, NULL AS params "
                    "FROM revision_userindex r JOIN page p ON p.page_id = r.rev_page "
                    "LEFT JOIN comment_revision c ON c.comment_id = r.rev_comment_id "
                    f"WHERE {rsql} ORDER BY r.rev_timestamp DESC LIMIT %s)"
                )
                params += [*rpar, limit]
            if not branches:
                return []
            cur.execute(" UNION ALL ".join(branches) + " ORDER BY ts DESC LIMIT %s OFFSET %s", (*params, per, offset))
            raw = cur.fetchall()
    finally:
        conn.close()

    out = []
    for src, sid, ltype, laction, ts, ns, title, cmt, params_raw in raw:
        src = dec(src)
        out.append({
            "key": f"{src}:{sid}",
            "wiki": "metawiki",
            "domain": "meta.wikimedia.org",
            "log_id": int(sid),
            "actor": name,
            "role": "steward",
            "log_type": dec(ltype),
            "log_action": dec(laction),
            "ts": to_iso(ts),
            "namespace": int(ns or 0),
            "title": full_title(ns, title),
            "comment": (dec(cmt) or "").replace("\n", " ").strip()[:1000],
            "params": logparams.normalize(params_raw) if src == "log" else {},
            "locked": 0,
        })
    return out


# ------------------------------------------------------------------ routes

def stamp(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def force():
    return request.args.get("refresh") == "1"


def all_time():
    # ?all=1 counts everything they ever did in these logs
    # the default only counts what they did while a steward
    return request.args.get("all") == "1"


def gate(name, fresh):
    members, _ = cached(("members",), 3600, fetch_members, fresh)
    if members.get(name) != "steward":
        return None
    cfg, _ = cached(("config",), 1800, fetch_config, fresh)
    return steward_periods(cfg, name)


def summary_for(name, periods, every, fresh):
    eff = [] if every else periods
    return cached(("steward", name, every), 900, lambda: build_summary(name, eff), fresh)


@bp.route("/api/steward/<name>")
def api_steward(name):
    fresh = force()
    periods = gate(name, fresh)
    if periods is None:
        return jsonify({"error": "User is not a current steward"}), 404
    every = all_time()
    data, ts = summary_for(name, periods, every, fresh)
    return jsonify({**data, "all_time": every, "cached_at": stamp(ts)})


@bp.route("/api/steward/<name>/actions")
def api_steward_actions(name):
    fresh = force()
    periods = gate(name, fresh)
    if periods is None:
        return jsonify({"error": "User is not a current steward"}), 404
    cat = request.args.get("cat", "all")
    if cat not in log_cats and cat != "sr":
        cat = "all"
    try:
        page = max(1, min(100000, int(request.args.get("page", 1))))
        per = max(1, min(200, int(request.args.get("per", 50))))
    except ValueError:
        page, per = 1, 50
    every = all_time()
    summary, _ = summary_for(name, periods, every, False)
    total = summary["total"] if cat == "all" else summary["counts"].get(cat, 0)
    rows, ts = cached(
        ("steward_rows", name, every, cat, page, per), 300,
        lambda: build_rows(name, [] if every else periods, cat, page, per), fresh,
    )
    return jsonify({"total": total, "rows": rows, "page": page, "per": per, "cached_at": stamp(ts)})
