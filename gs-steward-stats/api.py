"""JSON API used by the front end. Every route lives under /api/.

responses are cached in-process; ``?refresh=1`` forces a recompute.
cache keys include ``data_version()`` so a database sync invalidates them.
"""

import csv
import io
import json
import re
import time

from flask import Blueprint, Response, jsonify, request

from . import live
from .cache import cached
from .helpers import force_refresh, int_arg, iso
from .queries import (
    data_version,
    filters_from_request,
    meta_data,
    overview_data,
    query_actions,
    user_detail,
    wikis_data,
)
from .wiki_config import build_periods, load_config, wiki_info

bp = Blueprint("api", __name__, url_prefix="/api")

csv_columns = [
    "timestamp_utc", "wiki", "domain", "user", "role", "log_type", "log_action",
    "title", "locked_wiki", "comment", "params", "log_url",
]


@bp.route("/meta")
def api_meta():
    data, ts = cached(("meta", data_version()), 3600, meta_data, force_refresh())
    return jsonify({**data, "cached_at": iso(ts)})


@bp.route("/overview")
def api_overview():
    version, force = data_version(), force_refresh()
    data, ts = cached(("overview", version), 3600, overview_data, force)
    recent, _ = cached(("recent", version), 3600, lambda: query_actions({}, 1, 15)[1], force)
    return jsonify({**data, "recent": recent, "cached_at": iso(ts)})


@bp.route("/user/<name>")
def api_user(name):
    data, ts = cached(("user", name, data_version()), 3600, lambda: user_detail(name), force_refresh())
    if data is None:
        return jsonify({"error": "user is not a current steward or global sysop"}), 404
    return jsonify({**data, "cached_at": iso(ts)})


@bp.route("/user/<name>/periods")
def api_user_periods(name):
    force = force_refresh()
    cfg, ts = cached(("config",), 1800, load_config, force)
    info, _ = cached(("wikiinfo", data_version()), 3600, wiki_info, force)
    data = build_periods(cfg, info, name)
    return jsonify({**data, "cached_at": iso(ts), "source_generated": cfg.get("generated_at")})


@bp.route("/wikis")
def api_wikis():
    data, ts = cached(("wikis", data_version()), 3600, wikis_data, force_refresh())
    return jsonify({"rows": data, "cached_at": iso(ts)})


def _actions_csv(filters):
    """All matching actions as a CSV download (UTF-8 with BOM for Excel)."""
    _total, rows = query_actions(filters, 1, 100000)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(csv_columns)
    for r in rows:
        writer.writerow([
            r["ts"], r["wiki"], r["domain"], r["actor"], r["role"], r["log_type"], r["log_action"],
            r["title"], "yes" if r["locked"] else "no", r["comment"] or "",
            json.dumps(r["params"], ensure_ascii=False),
            f"https://{r['domain']}/wiki/Special:Redirect/logid/{r['log_id']}" if r["domain"] else "",
        ])
    name = re.sub(r"[^\w-]+", "_", filters.get("user") or "all")
    return Response(
        "﻿" + buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=gs_actions_{name}.csv"},
    )


@bp.route("/actions")
def api_actions():
    filters = filters_from_request()
    if request.args.get("format") == "csv":
        return _actions_csv(filters)

    page = int_arg("page", 1, 1, 100000)
    per = int_arg("per", 50, 1, 1000)
    count = request.args.get("nocount") != "1"
    key = ("actions", tuple(sorted(filters.items())), page, per, count, data_version())

    def compute():
        total, rows = query_actions(filters, page, per, count)
        return {"total": total, "rows": rows, "page": page, "per": per}

    data, ts = cached(key, 1800, compute, force_refresh())
    return jsonify({**data, "cached_at": iso(ts)})


@bp.route("/live")
def api_live():
    live.ensure_started()
    events, status = live.snapshot(int_arg("since", 0, 0, 10 ** 15))
    return jsonify({"events": events, "status": status, "now": int(time.time() * 1000)})
