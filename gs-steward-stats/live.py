"""live feed: listens to the Wikimedia EventStreams recentchange stream.

single background thread per worker keeps the latest matching log events in
memory (nothing is stored on disk). It is started lazily the first time
someone opens the live feed.
"""

import html
import json
import re
import threading
import time
from collections import deque
from datetime import datetime, timezone

import requests
import toolforge

from .helpers import in_periods, iso_format, parse_iso
from .settings import settings
from .wiki_config import load_config

# Steward-only log types that are shown when they happen on Meta-Wiki
steward_meta_logs = {"rights", "gblblock", "globalauth", "gblrights", "renameuser", "gblrename"}
# Log types counted as admin actions on GS wikis
admin_types = {"delete", "block", "protect", "merge", "import", "abusefilter"}

context_ttl = 1800  # seconds between context refreshes
key_prefix_re = re.compile(r"^\d+:[\w-]*:")  # "4::target" style keys in legacy log params

state = {
    "lock": threading.Lock(),
    "started": False,
    "events": deque(maxlen=400),
    "seen": set(),
    "stewards": set(),
    "gsysops": set(),
    "gs_wikis": set(),
    "local": {},
    "ctx_updated": None,
    "ctx_at": 0,
    "connected": False,
    "last_event_ms": 0,
    "total_seen": 0,
    "started_at": None,
}


def _text(value):
    return value.decode("utf-8") if isinstance(value, (bytes, bytearray)) else value


def clean_params(value):
    """Strip legacy "4::" prefixes from log parameter keys, recursively."""
    if isinstance(value, dict):
        return {key_prefix_re.sub("", str(k)): clean_params(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean_params(v) for v in value]
    return value


def norm_params(raw):
    """Log params from the stream can be a dict, list or string; always return a dict."""
    if raw in (None, "", [], {}):
        return {}
    if isinstance(raw, dict):
        return clean_params(raw)
    if isinstance(raw, list):
        return {"list": clean_params(raw)}
    return {"raw": str(raw)}


def _load_members():
    """Current stewards and global sysops from CentralAuth."""
    stewards, gsysops = set(), set()
    conn = toolforge.connect("centralauth")
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT gu.gu_name, gug.gug_group
                FROM global_user_groups gug
                JOIN globaluser gu ON gug.gug_user = gu.gu_id
                WHERE gug.gug_group IN ('steward', 'global-sysop')
                AND (
                    gug.gug_expiry IS NULL
                    OR gug.gug_expiry > DATE_FORMAT(UTC_TIMESTAMP(), '%Y%m%d%H%i%s')
                )
                """
            )
            for name, group in cur.fetchall():
                (stewards if _text(group) == "steward" else gsysops).add(_text(name))
    finally:
        conn.close()
    return stewards, gsysops


def _load_gs_wikis():
    """Wikis in the global sysop wikiset, via the Meta API."""
    wikis, cont = set(), {}
    while True:
        params = {"action": "query", "list": "wikisets", "wsprop": "wikisincluded", "wslimit": "max", "format": "json"}
        params.update(cont)
        r = requests.get("https://meta.wikimedia.org/w/api.php", params=params,
                         headers={"User-Agent": settings["user_agent"]}, timeout=60)
        data = r.json()
        for ws in data["query"]["wikisets"]:
            if ws["name"] == settings["wikiset_name"]:
                included = ws["wikisincluded"]
                wikis.update(included.values() if isinstance(included, dict) else included)
        if "continue" not in data:
            return wikis
        cont = data["continue"]


def _load_local_periods():
    """user -> wiki -> [(from, to)] local admin periods from the config page."""
    cfg = load_config()
    return {
        user: {
            wiki: [(parse_iso(p.get("from")), parse_iso(p.get("to"))) for p in periods]
            for wiki, periods in data.get("local_sysop_wikis", {}).items()
        }
        for user, data in cfg.get("users", {}).items()
    }


def refresh_context():
    """Reload members, wikis and local periods. Each part fails independently."""
    try:
        stewards, gsysops = _load_members()
        with state["lock"]:
            state["stewards"], state["gsysops"] = stewards, gsysops
    except Exception:
        pass
    try:
        wikis = _load_gs_wikis()
        if wikis:
            with state["lock"]:
                state["gs_wikis"] = wikis
    except Exception:
        pass
    try:
        local = _load_local_periods()
        with state["lock"]:
            state["local"] = local
    except Exception:
        pass
    with state["lock"]:
        state["ctx_updated"] = datetime.now(timezone.utc).strftime(iso_format)
        state["ctx_at"] = time.time()


def process_change(change):
    """Keep one stream event if it is a relevant log action by a steward or global sysop."""
    if change.get("type") != "log":
        return
    domain = (change.get("meta") or {}).get("domain") or ""
    if domain == "canary":
        return
    wiki, user = change.get("wiki"), change.get("user")
    if not wiki or not user:
        return
    user = user.split("@")[0].split("~")[0]

    with state["lock"]:
        is_steward = user in state["stewards"]
        is_gsysop = user in state["gsysops"]
        gs_wikis = state["gs_wikis"]
        local = state["local"].get(user, {})
    if not (is_steward or is_gsysop):
        return

    log_type, log_action = change.get("log_type"), change.get("log_action")
    if wiki == "metawiki":
        # On Meta only steward-only logs (rights, global blocks, locks, renames)
        if not is_steward or log_type not in steward_meta_logs:
            return
    elif wiki not in gs_wikis or log_type not in admin_types:
        return

    log_id = change.get("log_id")
    if not log_id:
        return
    ts = change.get("timestamp") or int(time.time())
    when = datetime.fromtimestamp(ts, timezone.utc).replace(tzinfo=None)
    if wiki != "metawiki" and in_periods(local.get(wiki, []), when):
        return  # the user was a local admin there at that time

    comment = html.unescape(change.get("comment") or "").replace("\n", " ").strip()[:1000]
    key = f"{wiki}:{log_id}"
    with state["lock"]:
        if key in state["seen"]:
            return
        state["seen"].add(key)
        if len(state["seen"]) > 6000:
            state["seen"].clear()
        row = {
            "key": key,
            "wiki": wiki,
            "domain": domain,
            "log_id": log_id,
            "actor": user,
            "role": "steward" if is_steward else "global-sysop",
            "log_type": log_type,
            "log_action": log_action,
            "title": change.get("title") or "",
            "comment": comment,
            "params": norm_params(change.get("log_params")),
            "ts": datetime.fromtimestamp(ts, timezone.utc).strftime(iso_format),
            "recv": int(time.time() * 1000),
        }
        state["events"].append(row)
        state["total_seen"] += 1
        state["last_event_ms"] = row["recv"]


def run_stream():
    """Read the SSE stream forever, reconnecting with exponential backoff."""
    state["started_at"] = datetime.now(timezone.utc).strftime(iso_format)
    refresh_context()
    last_id, backoff = None, 1
    while True:
        headers = {"User-Agent": settings["user_agent"], "Accept": "text/event-stream"}
        if last_id:
            headers["Last-Event-ID"] = last_id
        try:
            with requests.get(settings["stream_url"], headers=headers, stream=True, timeout=(15, 120)) as r:
                r.raise_for_status()
                r.encoding = "utf-8"
                state["connected"] = True
                backoff = 1
                for line in r.iter_lines(decode_unicode=True):
                    if time.time() - state["ctx_at"] > context_ttl:
                        refresh_context()
                    if not line:
                        continue
                    if line.startswith("id:"):
                        last_id = line[3:].strip()
                        continue
                    if not line.startswith("data:"):
                        continue
                    try:
                        process_change(json.loads(line[5:]))
                    except Exception:
                        continue
            state["connected"] = False
            time.sleep(2)
        except Exception:
            state["connected"] = False
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)


def ensure_started():
    """Start the stream thread once per worker."""
    if state["started"]:
        return
    with state["lock"]:
        if state["started"]:
            return
        state["started"] = True
    threading.Thread(target=run_stream, daemon=True, name="live-stream").start()


def snapshot(since_ms):
    """Events received after ``since_ms`` plus the stream status."""
    with state["lock"]:
        events = [e for e in state["events"] if e["recv"] > since_ms]
        status = {
            "connected": state["connected"],
            "last_event_ms": state["last_event_ms"],
            "total_seen": state["total_seen"],
            "kept": len(state["events"]),
            "stewards": len(state["stewards"]),
            "global_sysops": len(state["gsysops"]),
            "wikis": len(state["gs_wikis"]),
            "context_updated": state["ctx_updated"],
            "started_at": state["started_at"],
        }
    return events, status
