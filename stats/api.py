import csv
import io
import json
import re
import threading
import time
from datetime import datetime, timezone

import pymysql
from flask import Blueprint, Response, jsonify, request, stream_with_context

from stats import auth, db, live, localadmins, people, queries, rights, toolsdb
from stats.cache import cached
from stats.wikimedia import fetch_config

bp = Blueprint("api", __name__, url_prefix="/api")

# csv exports stream straight from the db. one at a time per user, and capped
export_cap = 500000
export_gap = 20
_exports = {}
_exports_lock = threading.Lock()


def stamp(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def force():
    return request.args.get("refresh") == "1"


def int_arg(name, default, lo, hi):
    try:
        v = int(request.args.get(name, default))
    except ValueError:
        v = default
    return max(lo, min(hi, v))


def filters():
    return {k: request.args.get(k, "").strip() for k in queries.filter_keys}


@bp.after_request
def no_store(resp):
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/me")
def me():
    return jsonify({"username": auth.current_user(), "login_enabled": auth.oauth_ready()})


@bp.route("/people")
def people_list():
    # who's been here lately. only names and a rough "x ago", see people.py
    return jsonify({"users": people.everyone(), "online_minutes": people.online_window // 60, "forget_days": people.forget_days})


@bp.route("/meta")
def meta():
    data, ts = cached(("meta", queries.data_version()), 3600, queries.meta, force())
    return jsonify({**data, "cached_at": stamp(ts)})


@bp.route("/overview")
def overview():
    ver, fresh = queries.data_version(), force()
    data, ts = cached(("overview", ver), 3600, queries.overview, fresh)
    recent, _ = cached(("recent", ver), 3600, lambda: queries.find_actions({}, 0, 15), fresh)
    return jsonify({**data, "recent": recent, "cached_at": stamp(ts)})


@bp.route("/period")
def period():
    start = queries.valid_date(request.args.get("from", ""))
    end = queries.valid_date(request.args.get("to", ""))
    key = ("period", start, end, queries.data_version())
    data, ts = cached(key, 3600, lambda: queries.period(start, end), force())
    return jsonify({**data, "cached_at": stamp(ts)})


@bp.route("/year")
def year():
    this_year = datetime.now(timezone.utc).year
    first = cached(("first_year", queries.data_version()), 3600, queries.first_year)[0]
    y = int_arg("year", this_year, first, this_year)
    name = request.args.get("user", "").strip() or None
    key = ("year", y, name, queries.data_version())
    data, ts = cached(key, 3600, lambda: queries.year_review(y, name), force())
    if data is None:
        return jsonify({"error": "User is not a current steward or global sysop"}), 404
    return jsonify({**data, "years": list(range(this_year, first - 1, -1)), "cached_at": stamp(ts)})


@bp.route("/user/<name>")
def user(name):
    data, ts = cached(("user", name, queries.data_version()), 3600, lambda: queries.user_detail(name), force())
    if data is None:
        return jsonify({"error": "User is not a current steward or global sysop"}), 404
    return jsonify({**data, "cached_at": stamp(ts)})


@bp.route("/user/<name>/periods")
def user_periods(name):
    fresh = force()
    cfg, ts = cached(("config",), 1800, fetch_config, fresh)
    wikis, _ = cached(("wikiinfo", queries.data_version()), 3600, queries.wiki_info, fresh)
    data = rights.history(cfg, wikis, name)
    return jsonify({**data, "cached_at": stamp(ts), "source_generated": cfg.get("generated_at")})


@bp.route("/projects")
def projects():
    data, ts = cached(("projects", queries.data_version()), 3600, queries.projects, force())
    return jsonify({"rows": data, "cached_at": stamp(ts)})


@bp.route("/project/<dbname>")
def project(dbname):
    data, ts = cached(("project", dbname, queries.data_version()), 3600, lambda: queries.project_detail(dbname), force())
    if data is None:
        return jsonify({"error": "Unknown project"}), 404
    return jsonify({**data, "cached_at": stamp(ts)})


@bp.route("/project/<dbname>/admins")
def project_admins(dbname):
    # live from the wiki's own replica, so keep it for half an hour
    if not db.one("SELECT dbname FROM gs_wikis WHERE dbname = %s", [dbname]):
        return jsonify({"error": "Unknown project"}), 404
    data, ts = cached(("admins", dbname), 1800, lambda: localadmins.fetch(dbname), force())
    return jsonify({**data, "cached_at": stamp(ts)})


@bp.route("/actions")
def actions():
    f = filters()
    if request.args.get("format") == "csv":
        return export(f)
    offset = int_arg("offset", 0, 0, 10 ** 9)
    limit = int_arg("limit", 50, 1, 2000)
    after = request.args.get("after") or None
    tail = request.args.get("tail") == "1"
    count = request.args.get("nocount") != "1"
    key = ("actions", tuple(sorted(f.items())), offset, limit, after, tail, count, queries.data_version())

    def run():
        total = queries.count_actions(f) if count else -1
        return {"total": total, "rows": queries.find_actions(f, offset, limit, after, tail)}

    data, ts = cached(key, 1800, run, force())
    return jsonify({**data, "cached_at": stamp(ts)})


def export(f):
    who = auth.current_user() or request.remote_addr
    with _exports_lock:
        if time.time() - _exports.get(who, 0) < export_gap:
            return jsonify({"error": "An export was started a moment ago. Please wait a few seconds."}), 429
        _exports[who] = time.time()

    head = ["timestamp_utc", "wiki", "domain", "user", "role", "log_type", "log_action", "title", "locked_wiki", "comment", "params", "log_url"]

    def generate():
        # its own unbuffered connection, rows go out as they come in
        conn = toolsdb.connect(cursor=pymysql.cursors.SSCursor)
        try:
            buf = io.StringIO()
            w = csv.writer(buf)
            buf.write("﻿")
            w.writerow(head)
            n = 0
            with conn.cursor() as cur:
                for r in queries.stream_actions(f, cur):
                    params = queries.parse_json(r["params"])
                    domain = r["domain"] or ""
                    w.writerow([
                        r["ts"], r["wiki"], domain, r["actor"], r["role"], r["log_type"], r["log_action"], r["title"],
                        "yes" if r["locked"] else "no", r["comment"] or "", json.dumps(params, ensure_ascii=False),
                        f"https://{domain}/wiki/Special:Redirect/logid/{r['log_id']}" if domain else "",
                    ])
                    n += 1
                    if n % 500 == 0:
                        yield buf.getvalue()
                        buf.seek(0)
                        buf.truncate()
                    if n >= export_cap:
                        break
            yield buf.getvalue()
        finally:
            conn.close()
            with _exports_lock:
                _exports.pop(who, None)

    name = re.sub(r"[^\w-]+", "_", f.get("user") or f.get("wiki") or "all")
    return Response(
        stream_with_context(generate()),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=gs_actions_{name}.csv"},
    )


@bp.route("/live")
def live_feed():
    return jsonify(live.feed(int_arg("since", 0, 0, 10 ** 15)))
