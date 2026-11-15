import json
import threading

import requests
import toolforge

from stats import settings

# things we read from wikimedia itself: who holds the rights, which wikis are
# gs wikis, which are closed, and the rights history config on meta


def dec(v):
    return v.decode("utf-8", "replace") if isinstance(v, (bytes, bytearray)) else v


# wiki replica connections are short lived, but a few pages opened at once could
# still pile up. at most 3 at a time per process, the rest wait their turn
replica_slots = threading.BoundedSemaphore(3)


class Replica:
    def __init__(self, conn):
        self.conn = conn

    def __getattr__(self, name):
        return getattr(self.conn, name)

    def close(self):
        if self.conn is None:
            return
        try:
            self.conn.close()
        finally:
            self.conn = None
            replica_slots.release()


def replica(dbname):
    if not replica_slots.acquire(timeout=120):
        raise TimeoutError("too many wiki replica connections open")
    try:
        return Replica(toolforge.connect(dbname))
    except BaseException:
        replica_slots.release()
        raise


def get(url, params=None, timeout=60):
    r = requests.get(url, params=params, headers={"User-Agent": settings.user_agent}, timeout=timeout)
    r.raise_for_status()
    return r


def fetch_members():
    conn = replica("centralauth")
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT gu.gu_name, gug.gug_group
                FROM global_user_groups gug
                JOIN globaluser gu ON gug.gug_user = gu.gu_id
                WHERE gug.gug_group IN ('steward', 'global-sysop')
                AND (gug.gug_expiry IS NULL
                     OR gug.gug_expiry > DATE_FORMAT(UTC_TIMESTAMP(), '%Y%m%d%H%i%s'))
                ORDER BY gu.gu_name
                """
            )
            out = {}
            for name, group in cur.fetchall():
                name, group = dec(name), dec(group)
                if out.get(name) != "steward":
                    out[name] = group
            return out
    finally:
        conn.close()


def fetch_gs_wikis():
    out = set()
    cont = {}
    while True:
        params = {"action": "query", "list": "wikisets", "wsprop": "wikisincluded", "wslimit": "max", "format": "json"}
        params.update(cont)
        data = get("https://meta.wikimedia.org/w/api.php", params).json()
        for ws in data["query"]["wikisets"]:
            if ws["name"] == settings.wikiset_name:
                inc = ws["wikisincluded"]
                out.update(inc.values() if isinstance(inc, dict) else inc)
        if "continue" not in data:
            return out
        cont = data["continue"]


def fetch_closed():
    text = get("https://noc.wikimedia.org/conf/dblists/closed.dblist").text
    return {line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")}


# private wikis, never read these even if they show up as closed
private_wikis = {"transitionteamwiki", "searchcomwiki", "internalwiki", "spcomwiki"}


def fetch_private():
    try:
        text = get("https://noc.wikimedia.org/conf/dblists/private.dblist").text
        found = {line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")}
    except Exception:
        found = set()
    return found | private_wikis


def fetch_config():
    r = get("https://meta.wikimedia.org/w/index.php", {"title": settings.config_page, "action": "raw"})
    return json.loads(r.text)
