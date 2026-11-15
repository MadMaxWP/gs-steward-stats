from datetime import datetime, timedelta, timezone

from stats import db
from stats.stewards import to_iso
from stats.wikimedia import dec, replica

# local admins of one wiki, read live from that wiki's replica when someone
# opens the project page. the api caches the answer for a while

admin_types = ("delete", "block", "protect", "merge", "import", "abusefilter")
extra_groups = ("bureaucrat", "interface-admin", "checkuser", "suppress", "bot")


def stamp(dt):
    return dt.strftime("%Y%m%d%H%M%S")


def newer(a, b):
    return max(x for x in (a, b) if x) if (a or b) else None


def fetch(dbname):
    now = datetime.now(timezone.utc)
    d7, d30, d60, d90 = (stamp(now - timedelta(days=n)) for n in (7, 30, 60, 90))
    types = ", ".join(["%s"] * len(admin_types))
    conn = replica(dbname + "_p")
    try:
        with conn.cursor() as cur:
            # big wikis have a lot of admins, don't let one page hold a replica forever
            cur.execute("SET SESSION max_statement_time = 60")
            cur.execute(
                "SELECT u.user_name, a.actor_id, "
                "(SELECT GROUP_CONCAT(g2.ug_group) FROM user_groups g2 WHERE g2.ug_user = u.user_id "
                " AND (g2.ug_expiry IS NULL OR g2.ug_expiry > %s)) AS grps, "
                "(SELECT rev_timestamp FROM revision_userindex WHERE rev_actor = a.actor_id "
                " ORDER BY rev_timestamp DESC LIMIT 1) AS last_edit, "
                "(SELECT log_timestamp FROM logging_userindex WHERE log_actor = a.actor_id "
                " ORDER BY log_timestamp DESC LIMIT 1) AS last_log, "
                "(SELECT log_timestamp FROM logging_userindex WHERE log_actor = a.actor_id "
                f" AND log_type IN ({types}) ORDER BY log_timestamp DESC LIMIT 1) AS last_admin, "
                "(SELECT COUNT(*) FROM revision_userindex WHERE rev_actor = a.actor_id AND rev_timestamp >= %s) AS edits30, "
                "(SELECT COUNT(*) FROM logging_userindex WHERE log_actor = a.actor_id "
                f" AND log_type IN ({types}) AND log_timestamp >= %s) AS admin30, "
                "(SELECT COUNT(*) FROM logging_userindex WHERE log_actor = a.actor_id "
                f" AND log_type IN ({types}) AND log_timestamp >= %s) AS admin90 "
                "FROM user_groups g JOIN user u ON u.user_id = g.ug_user "
                "LEFT JOIN actor a ON a.actor_user = u.user_id "
                "WHERE g.ug_group = 'sysop' AND (g.ug_expiry IS NULL OR g.ug_expiry > %s)",
                [stamp(now), *admin_types, d30, *admin_types, d30, *admin_types, d90, stamp(now)],
            )
            rows = cur.fetchall()
            # how busy the wiki itself is, from recentchanges (30 days kept there)
            try:
                cur.execute(
                    "SELECT COUNT(*), COUNT(DISTINCT rc_actor) FROM recentchanges "
                    "WHERE rc_timestamp >= %s AND rc_type IN (0, 1) AND rc_bot = 0",
                    [d30],
                )
                edits, editors = cur.fetchone()
            except Exception:
                edits = editors = None
    finally:
        conn.close()

    team = {r["name"]: r["role"] for r in db.rows("SELECT name, role FROM gs_users WHERE is_current = 1")}
    admins = []
    for name, _aid, grps, last_edit, last_log, last_admin, edits30, admin30, admin90 in rows:
        name = dec(name)
        groups = sorted(set(dec(grps or "").split(",")) & set(extra_groups))
        last_edit, last_log, last_admin = dec(last_edit), dec(last_log), dec(last_admin)
        admins.append({
            "name": name,
            "groups": groups,
            "bot": "bot" in groups,
            # sysop with no edits at all is almost always the abuse filter account ;)
            "filter": not last_edit,
            "role": team.get(name),
            "last_edit": to_iso(last_edit),
            "last_log": to_iso(last_log),
            "last_admin": to_iso(last_admin),
            "last_seen": to_iso(newer(last_edit, last_log)),
            "edits30": int(edits30 or 0),
            "admin30": int(admin30 or 0),
            "admin90": int(admin90 or 0),
            "_seen": newer(last_edit, last_log) or "",
            "_log": last_log or "",
        })
    admins.sort(key=lambda a: a["_seen"], reverse=True)

    people = [a for a in admins if not a["bot"] and not a["filter"]]
    count = lambda since, key="_seen": sum(1 for a in people if a[key] >= since)
    summary = {
        "admins": len(people),
        "bots": sum(1 for a in admins if a["bot"]),
        "filter": sum(1 for a in admins if a["filter"] and not a["bot"]),
        "active7": count(d7),
        "active30": count(d30),
        "active90": count(d90),
        "logged60": count(d60, "_log"),
        "admin30": sum(a["admin30"] for a in people),
        "admin90": sum(a["admin90"] for a in people),
        "edits30": int(edits) if edits is not None else None,
        "editors30": int(editors) if editors is not None else None,
    }
    for a in admins:
        a.pop("_seen")
        a.pop("_log")
    return {"admins": admins, "summary": summary}
