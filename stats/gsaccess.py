from stats.logparams import php_unserialize
from stats.stewards import to_iso
from stats.wikimedia import dec, replica

# when each wiki was opted in or out of global sysops. the "Opted-out of global
# sysop wikis" wiki set (WikiSets/7 on meta) is an opt out list: a wiki added
# to it is opted out, a wiki removed from it is opted in.
#
# logs from 2022 on keep their params php serialized. older ones are plain
# text: set name, added wikis, removed wikis, one per line, wikis comma separated.
# the first log (march 2010) is when the set became an opt out list, it sets
# the starting state for every wiki in it

query = """
SELECT l.log_id, l.log_timestamp, l.log_params, a.actor_name, c.comment_text
FROM logging_logindex AS l
JOIN actor_logging AS a ON a.actor_id = l.log_actor
LEFT JOIN comment_logging AS c ON c.comment_id = l.log_comment_id
WHERE l.log_type = 'gblrights' AND l.log_action = 'setchange'
  AND l.log_namespace = -1 AND l.log_title = 'WikiSets/7'
ORDER BY l.log_timestamp, l.log_id
"""


def wikis(text):
    return [w.strip() for w in (text or "").split(",") if w.strip()]


def changes(raw):
    # (added, removed) out of one log's params
    raw = dec(raw) or ""
    if raw.startswith("a:"):
        p = php_unserialize(raw) or {}
        added, removed = p.get("added") or {}, p.get("removed") or {}
        return (list(added.values()) if isinstance(added, dict) else list(added),
                list(removed.values()) if isinstance(removed, dict) else list(removed))
    lines = raw.split("\n")
    return wikis(lines[1] if len(lines) > 1 else ""), wikis(lines[2] if len(lines) > 2 else "")


def fetch():
    conn = replica("metawiki_p")
    try:
        with conn.cursor() as cur:
            cur.execute(query)
            found = cur.fetchall()
    finally:
        conn.close()

    out = set()  # wikis in the opt out set as we go
    timeline = {}
    for i, (log_id, ts, params, actor, comment) in enumerate(found):
        added, removed = changes(params)
        for change, names in (("out", added), ("in", removed)):
            for w in names:
                if change == "out":
                    out.add(w)
                else:
                    out.discard(w)
                timeline.setdefault(w, []).append({
                    "log_id": int(log_id), "ts": to_iso(dec(ts)), "change": change, "initial": i == 0,
                    "actor": dec(actor), "comment": dec(comment) or "",
                })
    return {"wikis": timeline, "opted_out": sorted(out)}
