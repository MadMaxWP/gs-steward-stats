"""the listener component: reads the wikimedia event stream all the time.

- keeps the live feed in memory and hands it to the website (GET /feed on port 8000)
- saves steward/gs admin actions into gs_actions within a few seconds and adds
  them to the summary, so the other pages are up to date without waiting for
  the update job
- remembers its place in the stream, so a restart carries on where it stopped
- drops people from the stats as soon as they lose steward/gs

run with: python listen.py (the Procfile's "listener")
"""
import json
import logging
import signal
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from stats import db, live, pool, sync

save_every = 5            # seconds between batches
recount_every = 3600      # rolling "last n days" numbers
stats_every = 10 * 60
max_queue = 2000          # if toolsdb is down this long the update job fills the gap

log = logging.getLogger("gs.listen")


class Saver:
    def __init__(self):
        self.queue = deque()
        self.lock = threading.Lock()
        self.pending = []
        self.dropped = 0
        self.saved = 0
        self.failed = 0
        self.listener = None
        self.stop = threading.Event()
        self.cursor = None
        # first recount a while after start, then hourly. the update job's rebuild
        # every 3 hours counts as one too
        self.next_recount = time.time() + 600

    def add(self, row):
        with self.lock:
            if len(self.queue) + len(self.pending) >= max_queue:
                self.queue.popleft()
                self.dropped += 1
            self.queue.append(row)

    def check_members(self, members):
        # who toolsdb still has as current but centralauth doesn't any more
        if not members:
            return
        current = {r["name"] for r in db.rows("SELECT name FROM gs_users WHERE is_current = 1", fresh=True)}
        gone = sorted(current - set(members))
        if not gone:
            return
        if len(gone) > 10:
            # more likely a bad answer than ten people leaving at once, the update job checks again
            log.warning("%s members missing from centralauth, leaving it to the update job", len(gone))
            return
        n = sync.drop_users(gone)
        log.info("dropped %s (%s rows)", ", ".join(gone), n)

    def cursor_value(self, mark):
        return json.dumps({"id": mark, "at": int(time.time())})

    def batch(self):
        # nothing to save means no connection at all. the place in the stream is
        # read before the queue is emptied: every event up to it has already put
        # its row in the queue, so it's saved in the same transaction as those rows
        mark = self.listener.last_id if self.listener else None
        with self.lock:
            self.pending.extend(self.queue)
            self.queue.clear()
        if not self.pending:
            return
        try:
            self.saved += sync.save_live(self.pending, self.cursor_value(mark) if mark else None)
            self.pending = []
            self.cursor = mark
        except Exception:
            self.failed += 1
            log.exception("saving %s actions failed, trying again next round", len(self.pending))

    def recount(self):
        # timed in memory, toolsdb is only asked when it's actually due
        if time.time() < self.next_recount:
            return
        self.next_recount = time.time() + recount_every
        try:
            n = sync.recount()
            log.info("recounted rolling numbers for %s summary rows", n)
        except Exception:
            self.next_recount = time.time() + 600
            log.exception("recount failed, trying again in 10 minutes")

    def run(self):
        last_stats = time.time()
        while not self.stop.wait(save_every):
            try:
                self.batch()
                self.recount()
                if time.time() - last_stats >= stats_every:
                    last_stats = time.time()
                    self.log_stats()
            except Exception:
                log.exception("saver round failed")

    def log_stats(self):
        c = self.listener.counts if self.listener else {}
        log.info(
            "events %s, shown %s, queued %s, saved %s, waiting %s, dropped %s, failed batches %s, reconnects %s, db %s",
            c.get("events"), c.get("shown"), c.get("queued"), self.saved, len(self.queue) + len(self.pending),
            self.dropped, self.failed, c.get("reconnects"), pool.writer().stats(),
        )

    def flush(self):
        # on shutdown: save what's waiting, and keep the newest place in the stream
        # even if nothing matched since the last save (one short connection)
        self.stop.set()
        try:
            self.batch()
            mark = self.listener.last_id if self.listener else None
            if mark and mark != self.cursor and not self.pending:
                db.run(
                    "INSERT INTO gs_meta (k, v) VALUES ('live_cursor', %s) ON DUPLICATE KEY UPDATE v = VALUES(v)",
                    [self.cursor_value(mark)],
                )
        except Exception:
            log.exception("final save failed")


def serve(listener):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/feed"):
                body = json.dumps(listener.feed(), ensure_ascii=False).encode("utf-8")
                ctype = "application/json"
            elif self.path.startswith("/healthz"):
                body, ctype = b"ok", "text/plain"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass  # the website polls every few seconds, no need to log each one

    server = ThreadingHTTPServer(("0.0.0.0", 8000), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, name="feed-http", daemon=True).start()
    return server


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s", stream=sys.stdout)
    # all writes happen here, 3 connections at most, and waiting is fine
    pool.setup(read=0, write=3, wait=300)
    for tries in range(10):
        try:
            sync.widen_meta()
            break
        except Exception:
            log.exception("toolsdb not reachable yet")
            time.sleep(30)

    saver = Saver()
    listener = live.Listener(saver)
    saver.listener = listener
    server = serve(listener)
    threading.Thread(target=saver.run, name="saver", daemon=True).start()

    def stop(signum, frame):
        log.info("stopping")
        listener.stop.set()
        r = listener.response
        if r is not None:
            live.cut(r)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        listener.run()
    finally:
        # everything handled so far is saved and the place in the stream kept
        saver.flush()
        server.shutdown()
        pool.shutdown()
        log.info("stopped")


if __name__ == "__main__":
    main()
