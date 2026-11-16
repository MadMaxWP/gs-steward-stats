import html
import json
import logging
import random
import socket
import threading
import time
from collections import deque
from datetime import datetime, timezone

import requests

from stats import cache, db, rights, settings, stewards, sync
from stats.logparams import normalize
from stats.wikimedia import fetch_config, fetch_gs_wikis, fetch_members, fetch_private

# the live feed. the listener component (listen.py) runs Listener all the time:
# it reads the wikimedia event stream, keeps the last 3 hours of matching events
# in memory for the live feed page, and hands admin actions to the saver so they
# go into gs_actions and the summary within a few seconds.
#
# the listener puts the feed in redis and the website reads it from there. if
# redis isn't there it asks the listener over the tool's internal network, see
# feed() at the bottom.
#
# the place in the stream is kept in gs_meta (live_cursor) once a batch is saved,
# so a restart or a deploy carries on from there and nothing is missed

log = logging.getLogger("gs.live")

stream_url = "https://stream.wikimedia.org/v2/stream/recentchange"
meta_logs = {"rights", "gblblock", "globalauth", "gblrights", "renameuser", "gblrename"}
admin_types = {"delete", "block", "protect", "merge", "import", "abusefilter"}

keep_events = 500
keep_seconds = 3 * 3600   # same as the update job, older actions are on the other pages by then
feed_key = ("feed",)
publish_every = 2         # the feed goes to redis this often when something changed
heartbeat = 10            # ...and at least this often anyway, so the website knows it's alive
stale_after = 45          # a copy in redis older than this means the listener is gone
resume_max = 3 * 3600     # pick the stream up from the saved place if it's this recent
refresh_every = 30 * 60   # reload who is a steward/gs and which wikis count
retry_every = 60          # ...or this soon if that failed
hang_after = 3 * 60       # no events at all for this long means the stream is stuck


def now_ms():
    return int(time.time() * 1000)


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cut(r):
    # closing a response from another thread doesn't wake up a read that's
    # waiting on the socket, shutting the socket down does
    sock = None
    try:
        sock = r.raw._fp.fp.raw._sock
    except AttributeError:
        sock = getattr(getattr(r.raw, "connection", None), "sock", None)
    if sock is not None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
    try:
        r.close()
    except Exception:
        pass


class Listener:
    def __init__(self, saver):
        self.saver = saver
        self.stop = threading.Event()
        self.ctx_lock = threading.Lock()
        self.ctx = {"stewards": set(), "gsysops": set(), "gs_wikis": set(), "save_wikis": set(), "local": {}, "sr": {}}
        self.status = {
            "connected": False, "started_at": iso(time.time()), "last_event_ms": 0, "total_seen": 0,
            "stewards": 0, "global_sysops": 0, "wikis": 0, "context_updated": None, "context_ok": False,
        }
        self.events = deque(maxlen=keep_events)
        self.keys = set()
        self.feed_lock = threading.Lock()
        self.last_id = None       # last event fully handled
        self.last_seen = time.time()
        self.response = None
        self.counts = {"events": 0, "shown": 0, "queued": 0, "reconnects": 0}
        self.changed = True
        self.load_cursor()

    # ---- where we were in the stream

    def load_cursor(self):
        try:
            raw = sync.get_meta("live_cursor")
            saved = json.loads(raw) if raw else {}
        except Exception:
            log.exception("could not read the saved stream position")
            saved = {}
        if saved.get("id") and time.time() - (saved.get("at") or 0) < resume_max:
            self.last_id = saved["id"]
            log.info("resuming the stream from %s", iso(saved["at"]))
        else:
            log.info("starting the stream from now")

    # ---- who and what counts

    def refresh(self):
        ok = True
        try:
            members = fetch_members()
            with self.ctx_lock:
                self.ctx["stewards"] = {n for n, r in members.items() if r == "steward"}
                self.ctx["gsysops"] = {n for n, r in members.items() if r != "steward"}
        except Exception:
            log.exception("member refresh failed")
            members = None
            ok = False
        if members:
            try:
                self.saver.check_members(members)
            except Exception:
                log.exception("could not drop former members")
        try:
            wikis = fetch_gs_wikis() - fetch_private()
            if wikis:
                with self.ctx_lock:
                    self.ctx["gs_wikis"] = wikis
        except Exception:
            log.exception("gs wiki refresh failed")
            ok = False
        try:
            # gs wikis plus closed ones, the same list backfill.py reads
            found = {r["dbname"] for r in db.rows("SELECT dbname FROM gs_wikis WHERE is_gs = 1 OR is_locked = 1")}
            with self.ctx_lock:
                self.ctx["save_wikis"] = found
        except Exception:
            log.exception("could not load the wiki list from toolsdb")
            ok = False
        try:
            cfg = fetch_config()
            local = {
                u: {w: rights.periods_for(ps) for w, ps in (d.get("local_sysop_wikis") or {}).items()}
                for u, d in (cfg.get("users") or {}).items()
            }
            with self.ctx_lock:
                self.ctx["local"] = local
        except Exception:
            log.exception("config refresh failed")
            ok = False
        try:
            titles = stewards.sr_titles()
            with self.ctx_lock:
                self.ctx["sr"] = titles
        except Exception:
            log.exception("sr page refresh failed")
            ok = False
        with self.ctx_lock:
            ok = ok and bool(self.ctx["stewards"]) and bool(self.ctx["gs_wikis"])
            self.status.update({
                "stewards": len(self.ctx["stewards"]),
                "global_sysops": len(self.ctx["gsysops"]),
                "wikis": len(self.ctx["gs_wikis"]),
                "context_updated": iso(time.time()),
                "context_ok": ok,
            })
        return ok

    def refresher(self, ok):
        while not self.stop.wait(refresh_every if ok else retry_every):
            try:
                ok = self.refresh()
            except Exception:
                log.exception("refresh failed")
                ok = False

    def watchdog(self):
        # the stream sometimes goes quiet without closing. recentchange never has
        # 3 minutes without a single event, so cut it and connect again
        while not self.stop.wait(15):
            if self.status["connected"] and time.time() - self.last_seen > hang_after:
                log.warning("no events for %ss, reconnecting", hang_after)
                r = self.response
                if r is not None:
                    cut(r)
                self.last_seen = time.time()

    # ---- the stream

    def run(self):
        backoff = 1
        # load the lists first so the opening seconds of the stream aren't thrown away
        try:
            ok = self.refresh()
        except Exception:
            log.exception("first refresh failed")
            ok = False
        threading.Thread(target=self.refresher, args=(ok,), name="live-refresh", daemon=True).start()
        threading.Thread(target=self.watchdog, name="live-watchdog", daemon=True).start()
        threading.Thread(target=self.publisher, name="live-publish", daemon=True).start()
        while not self.stop.is_set():
            try:
                self.listen()
                backoff = 1
            except Exception as e:
                if self.stop.is_set():
                    break
                log.warning("stream dropped: %s", str(e)[:200])
                # back off with a bit of jitter, like the eventstreams docs ask
                self.stop.wait(backoff + random.random())
                backoff = min(backoff * 2, 60)
            finally:
                self.status["connected"] = False
                self.response = None
            self.counts["reconnects"] += 1

    def listen(self):
        headers = {"User-Agent": settings.user_agent, "Accept": "text/event-stream"}
        if self.last_id:
            headers["Last-Event-ID"] = self.last_id
        with requests.get(stream_url, headers=headers, stream=True, timeout=(15, 60)) as r:
            r.raise_for_status()
            r.encoding = "utf-8"
            self.response = r
            self.status["connected"] = True
            self.last_seen = time.time()
            pending = None
            for line in r.iter_lines(decode_unicode=True):
                if self.stop.is_set():
                    return
                if not line:
                    # end of one event. only now move the resume point, so a cut
                    # connection never skips an event we didn't handle yet
                    if pending:
                        self.last_id = pending
                        pending = None
                    continue
                if line.startswith("id:"):
                    pending = line[3:].strip()
                    continue
                if line.startswith("data:"):
                    self.last_seen = time.time()
                    self.counts["events"] += 1
                    try:
                        self.handle(json.loads(line[5:]))
                    except Exception:
                        continue

    def handle(self, change):
        kind = change.get("type")
        if kind not in ("log", "edit", "new"):
            return
        domain = (change.get("meta") or {}).get("domain") or ""
        wiki = change.get("wiki")
        user = change.get("user")
        if domain == "canary" or not wiki or not user:
            return
        user = user.split("@")[0].split("~")[0]
        with self.ctx_lock:
            is_st = user in self.ctx["stewards"]
            is_gs = user in self.ctx["gsysops"]
            gs_wikis = self.ctx["gs_wikis"]
            save_wikis = self.ctx["save_wikis"]
            local = self.ctx["local"].get(user, {})
            sr = self.ctx["sr"]
        if not (is_st or is_gs):
            return
        ts = change.get("timestamp") or int(time.time())

        if kind != "log":
            # edits only count on the steward request pages on meta, by stewards.
            # these are only shown, they aren't admin actions
            title = change.get("title") or ""
            if wiki != "metawiki" or not is_st or title not in sr:
                return
            if change.get("minor") and not sr[title]:
                return
            rev = (change.get("revision") or {}).get("new")
            if not rev:
                return
            self.show({
                "key": f"metawiki:rev:{rev}", "wiki": wiki, "domain": domain, "log_id": rev, "actor": user,
                "role": "steward", "log_type": "sr", "log_action": "edit", "title": title,
                "comment": self.comment(change), "params": {}, "ts": iso(ts),
            })
            return

        lt = change.get("log_type")
        log_id = change.get("log_id")
        if not log_id:
            return
        when = datetime.fromtimestamp(ts, timezone.utc).replace(tzinfo=None)
        if wiki == "metawiki":
            # on meta only the steward logs (rights, global blocks, locks, renames), shown only
            if is_st and lt in meta_logs:
                self.show(self.row(change, wiki, domain, user, is_st, lt, ts))
            return
        if lt not in admin_types or rights.in_periods(local.get(wiki, []), when):
            return  # not an admin action, or they were a local admin there at the time
        row = self.row(change, wiki, domain, user, is_st, lt, ts)
        if wiki in gs_wikis:
            self.show(row)
        if wiki in save_wikis:
            self.counts["queued"] += 1
            self.saver.add({
                "wiki": wiki, "log_id": int(log_id), "actor": user, "log_type": lt,
                "log_action": change.get("log_action") or "", "when": when, "ts": iso(ts),
                "namespace": int(change.get("namespace") or 0), "title": change.get("title") or "",
                "comment": html.unescape(change.get("comment") or ""),
                "params": json.dumps(row["params"], ensure_ascii=False),
            })

    def row(self, change, wiki, domain, user, is_st, lt, ts):
        return {
            "key": f"{wiki}:{change.get('log_id')}", "wiki": wiki, "domain": domain, "log_id": change.get("log_id"),
            "actor": user, "role": "steward" if is_st else "global-sysop", "log_type": lt,
            "log_action": change.get("log_action"), "title": change.get("title") or "", "comment": self.comment(change),
            "params": normalize(change.get("log_params")), "ts": iso(ts),
        }

    def comment(self, change):
        return html.unescape(change.get("comment") or "").replace("\n", " ").strip()[:1000]

    def show(self, row):
        with self.feed_lock:
            if row["key"] in self.keys:
                return
            # an old event (replayed after a restart) gets its own time, so open pages
            # don't treat it as new and alert for it again
            when = datetime.strptime(row["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
            row["recv"] = now_ms() if time.time() - when < 600 else int(when * 1000)
            if len(self.events) == self.events.maxlen:
                self.keys.discard(self.events[0]["key"])
            self.events.append(row)
            self.keys.add(row["key"])
            self.status["total_seen"] += 1
            self.status["last_event_ms"] = row["recv"]
            self.counts["shown"] += 1
            self.changed = True

    def publisher(self):
        # puts the feed in redis for the website. nothing new means it only goes
        # out as a heartbeat, so the website can tell the listener is still there
        last, was_connected = 0, None
        while not self.stop.wait(publish_every):
            connected = self.status["connected"]
            if not (self.changed or connected != was_connected or time.time() - last >= heartbeat):
                continue
            self.changed, was_connected, last = False, connected, time.time()
            cache.put(feed_key, self.feed(), 3600)

    def feed(self):
        cutoff = now_ms() - keep_seconds * 1000
        with self.feed_lock:
            while self.events and self.events[0].get("recv", 0) < cutoff:
                self.keys.discard(self.events.popleft()["key"])
            events = list(self.events)
        return {"events": events, "status": dict(self.status), "now": now_ms()}


# ------------------------------------------------------------------ the website side

_web = {"at": 0, "data": None}
_web_lock = threading.Lock()
web_cache = 2  # seconds, every open tab polls, the listener is only asked this often


def feed(since):
    # from redis, where the listener keeps it. if redis has nothing fresh (redis
    # down, or no prefix set) ask the listener directly instead
    with _web_lock:
        if time.time() - _web["at"] >= web_cache:
            data = cache.get(feed_key)
            if not data or now_ms() - data.get("now", 0) > stale_after * 1000:
                try:
                    r = requests.get(settings.listener_url + "/feed", timeout=5)
                    r.raise_for_status()
                    data = r.json()
                except Exception:
                    # listener restarting or down, keep the last copy but show it as disconnected
                    old = _web["data"] or {"events": [], "status": {}}
                    data = {**old, "status": {**old.get("status", {}), "connected": False}}
            _web["data"], _web["at"] = data, time.time()
        data = _web["data"]
    events = [e for e in data.get("events", []) if e.get("recv", 0) > since]
    return {"events": events, "status": data.get("status") or {"connected": False}, "now": now_ms()}
