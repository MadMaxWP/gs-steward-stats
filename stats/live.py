import fcntl
import html
import json
import os
import random
import threading
import time
from collections import deque
from datetime import datetime, timezone

import requests

from stats import rights, settings, stewards
from stats.logparams import normalize
from stats.wikimedia import fetch_config, fetch_gs_wikis, fetch_members

# every worker tries to grab a file lock when it starts. whoever gets it listens
# to the wikimedia event stream the whole time and writes matching events to
# live_feed.json in the data dir. every worker just reads that file, so all
# viewers see the same feed.
#
# nothing is stored anywhere else. a deploy starts a fresh container, so the feed
# starts empty again and fills up as things happen. a worker restart inside the
# same container picks the stream up where it stopped (Last-Event-ID).

stream_url = "https://stream.wikimedia.org/v2/stream/recentchange"
meta_logs = {"rights", "gblblock", "globalauth", "gblrights", "renameuser", "gblrename"}
admin_types = {"delete", "block", "protect", "merge", "import", "abusefilter"}

feed_file = os.path.join(settings.data_dir, "live_feed.json")
status_file = os.path.join(settings.data_dir, "live_status.json")
lock_file = os.path.join(settings.data_dir, "live_feed.lock")

keep_events = 500
keep_seconds = 24 * 3600
resume_window = 5 * 60    # pick the stream up where we left off if we stopped this recently
refresh_every = 30 * 60   # reload who is a steward/gs and which wikis count
retry_every = 60          # ...or this soon if that failed
write_every = 2
heartbeat_every = 10
keeper_every = 60         # each worker checks this often that someone is listening

_proc = {"thread": None, "keeper": None, "feed": (None, None), "status": (None, None)}
_proc_lock = threading.Lock()


def now_ms():
    return int(time.time() * 1000)


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_json(path, data):
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def read_json(path, slot):
    # re-read only when the file changed, workers poll this every few seconds
    try:
        mtime = os.stat(path).st_mtime_ns
    except FileNotFoundError:
        return None
    cached_mtime, data = _proc[slot]
    if cached_mtime == mtime:
        return data
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return data
    _proc[slot] = (mtime, data)
    return data


def keeper():
    # if the worker holding the stream dies, another one takes over within a minute
    while True:
        try:
            ensure_listener()
        except Exception:
            pass
        time.sleep(keeper_every)


def start():
    # called once per worker when the app loads
    with _proc_lock:
        if _proc["keeper"]:
            return
        _proc["keeper"] = threading.Thread(target=keeper, name="live-keeper", daemon=True)
        _proc["keeper"].start()


def ensure_listener():
    with _proc_lock:
        t = _proc["thread"]
        if t and t.is_alive():
            return
        fd = open(lock_file, "a")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fd.close()  # another worker is already listening
            return
        t = threading.Thread(target=Listener(fd).run, name="live-feed", daemon=True)
        _proc["thread"] = t
        t.start()


def feed(since):
    ensure_listener()
    data = read_json(feed_file, "feed") or {}
    status = read_json(status_file, "status") or {}
    events = [e for e in data.get("events", []) if e.get("recv", 0) > since]
    alive = time.time() - (status.get("heartbeat") or 0) < 3 * heartbeat_every
    status = {**status, "connected": bool(status.get("connected") and alive)}
    return {"events": events, "status": status, "now": now_ms()}


class Listener:
    def __init__(self, lock_fd):
        self.lock_fd = lock_fd
        self.stop = threading.Event()
        self.ctx_lock = threading.Lock()
        self.ctx = {"stewards": set(), "gsysops": set(), "gs_wikis": set(), "local": {}, "sr": {}}
        self.status = {
            "connected": False, "started_at": iso(time.time()), "last_event_ms": 0, "total_seen": 0,
            "stewards": 0, "global_sysops": 0, "wikis": 0, "context_updated": None, "context_ok": False,
        }
        # a restarted worker in the same container still has the files
        old = {"events": self.load(feed_file).get("events", []), **{
            k: v for k, v in self.load(status_file).items() if k in ("heartbeat", "last_id")}}
        cutoff = now_ms() - keep_seconds * 1000
        self.events = deque((e for e in old.get("events", []) if e.get("recv", 0) > cutoff), maxlen=keep_events)
        self.keys = {e["key"] for e in self.events}
        recent = time.time() - (old.get("heartbeat") or 0) < resume_window
        self.last_id = old.get("last_id") if recent else None
        self.dirty = bool(self.events)  # write what we loaded so viewers see it straight away
        self.wrote = 0
        self.beat = 0

    # ---- bookkeeping

    def load(self, path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def save(self, force=False):
        now = time.time()
        if self.dirty and (force or now - self.wrote >= write_every):
            cutoff = now_ms() - keep_seconds * 1000
            while self.events and self.events[0].get("recv", 0) < cutoff:
                self.keys.discard(self.events.popleft()["key"])
            write_json(feed_file, {"events": list(self.events)})
            self.dirty = False
            self.wrote = now
        if force or now - self.beat >= heartbeat_every:
            # last_id rides along so a listener started soon after can resume from it
            write_json(status_file, {**self.status, "heartbeat": now, "last_id": self.last_id})
            self.beat = now

    def refresh(self):
        ok = True
        try:
            members = fetch_members()
            with self.ctx_lock:
                self.ctx["stewards"] = {n for n, r in members.items() if r == "steward"}
                self.ctx["gsysops"] = {n for n, r in members.items() if r != "steward"}
        except Exception:
            ok = False
        try:
            wikis = fetch_gs_wikis()
            if wikis:
                with self.ctx_lock:
                    self.ctx["gs_wikis"] = wikis
        except Exception:
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
            ok = False
        try:
            titles = stewards.sr_titles()
            with self.ctx_lock:
                self.ctx["sr"] = titles
        except Exception:
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
            ok = self.refresh()

    # ---- the stream

    def run(self):
        backoff = 1
        try:
            # load the lists first so the opening seconds of the stream aren't thrown away
            ok = self.refresh()
            threading.Thread(target=self.refresher, args=(ok,), name="live-refresh", daemon=True).start()
            while not self.stop.is_set():
                try:
                    self.listen()
                    backoff = 1
                    time.sleep(1)
                except Exception:
                    self.status["connected"] = False
                    self.save(force=True)
                    # back off with a bit of jitter, like the eventstreams docs ask
                    time.sleep(backoff + random.random())
                    backoff = min(backoff * 2, 60)
        finally:
            self.stop.set()
            self.status["connected"] = False
            try:
                self.save(force=True)
            except OSError:
                pass
            fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
            self.lock_fd.close()

    def listen(self):
        headers = {"User-Agent": settings.user_agent, "Accept": "text/event-stream"}
        if self.last_id:
            headers["Last-Event-ID"] = self.last_id
        with requests.get(stream_url, headers=headers, stream=True, timeout=(15, 60)) as r:
            r.raise_for_status()
            r.encoding = "utf-8"
            self.status["connected"] = True
            self.save(force=True)
            pending = None
            for line in r.iter_lines(decode_unicode=True):
                self.save()
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
                    try:
                        self.handle(json.loads(line[5:]))
                    except Exception:
                        continue
        self.status["connected"] = False

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
            local = self.ctx["local"].get(user, {})
            sr = self.ctx["sr"]
        if not (is_st or is_gs):
            return
        ts = change.get("timestamp") or int(time.time())

        if kind != "log":
            # edits only count on the steward request pages on meta, by stewards
            title = change.get("title") or ""
            if wiki != "metawiki" or not is_st or title not in sr:
                return
            if change.get("minor") and not sr[title]:
                return
            rev = (change.get("revision") or {}).get("new")
            if not rev:
                return
            self.add({
                "key": f"metawiki:rev:{rev}", "wiki": wiki, "domain": domain, "log_id": rev, "actor": user,
                "role": "steward", "log_type": "sr", "log_action": "edit", "title": title,
                "comment": self.comment(change), "params": {}, "ts": iso(ts),
            })
            return

        lt = change.get("log_type")
        if wiki == "metawiki":
            # on meta only the steward logs (rights, global blocks, locks, renames)
            if not is_st or lt not in meta_logs:
                return
        elif wiki not in gs_wikis or lt not in admin_types:
            return
        log_id = change.get("log_id")
        if not log_id:
            return
        when = datetime.fromtimestamp(ts, timezone.utc).replace(tzinfo=None)
        if wiki != "metawiki" and rights.in_periods(local.get(wiki, []), when):
            return  # they were a local admin there at the time
        self.add({
            "key": f"{wiki}:{log_id}", "wiki": wiki, "domain": domain, "log_id": log_id, "actor": user,
            "role": "steward" if is_st else "global-sysop", "log_type": lt, "log_action": change.get("log_action"),
            "title": change.get("title") or "", "comment": self.comment(change),
            "params": normalize(change.get("log_params")), "ts": iso(ts),
        })

    def comment(self, change):
        return html.unescape(change.get("comment") or "").replace("\n", " ").strip()[:1000]

    def add(self, row):
        if row["key"] in self.keys:
            return
        row["recv"] = now_ms()
        if len(self.events) == self.events.maxlen:
            self.keys.discard(self.events[0]["key"])
        self.events.append(row)
        self.keys.add(row["key"])
        self.status["total_seen"] += 1
        self.status["last_event_ms"] = row["recv"]
        self.dirty = True
