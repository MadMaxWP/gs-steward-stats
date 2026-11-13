from datetime import datetime, timedelta, timezone

# working with the rights periods from the meta config.
# a period is a (from, to) pair of naive utc datetimes, to=None means still going

# terms of the same role closer than this count as one long term
role_gap = timedelta(days=7)


def parse_iso(s):
    if not s or s == "present":
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def in_periods(periods, when):
    return any((f is None or f <= when) and (t is None or when < t) for f, t in periods)


def periods_for(entries):
    out = []
    for p in entries or []:
        f = parse_iso(p.get("from"))
        if f:
            out.append((f, parse_iso(p.get("to"))))
    return out


def user_rules(users_cfg, names):
    # per user: steward/gs periods, and local admin periods per wiki
    rules = {}
    for n in names:
        d = users_cfg.get(n) or {}
        hist = d.get("global_group_history") or {}
        groups = periods_for(hist.get("global-sysop")) + periods_for(hist.get("steward"))
        local = {}
        for wiki, ps in (d.get("local_sysop_wikis") or {}).items():
            got = periods_for(ps)
            if got:
                local[wiki] = got
        rules[n] = {"groups": groups, "local": local}
    return rules


def role_since(users_cfg, name, role):
    # start of the current run in this role. earlier terms that touch it (gap <= role_gap)
    # are merged in, so a steward renewed every year shows when the run began.
    # time in the other role breaks the run
    terms = sorted(periods_for(((users_cfg.get(name) or {}).get("global_group_history") or {}).get(role)))
    if not terms:
        return None
    now = utc_now()
    cur = len(terms) - 1
    for i in range(len(terms) - 1, -1, -1):
        if terms[i][1] is None or terms[i][1] > now:
            cur = i
            break
    start = terms[cur][0]
    for i in range(cur - 1, -1, -1):
        f, t = terms[i]
        if t is None or start - t <= role_gap:
            start = min(start, f)
        else:
            break
    return start.strftime("%Y-%m-%dT%H:%M:%SZ")


def history(cfg, wikis, name):
    # what the rights history tab shows
    u = (cfg.get("users") or {}).get(name)
    if not u:
        return {"found": False, "groups": [], "local": []}
    now = utc_now()

    def is_current(p):
        t = p.get("to")
        if not t or t == "present":
            return True
        d = parse_iso(t)
        return bool(d and d > now)

    groups = []
    for g, ps in (u.get("global_group_history") or {}).items():
        for p in ps:
            groups.append({"group": g, "from": p.get("from"), "to": p.get("to") or "present", "current": is_current(p), "log": p.get("log")})
    groups.sort(key=lambda x: x["from"] or "", reverse=True)

    local = []
    for wiki, ps in (u.get("local_sysop_wikis") or {}).items():
        w = wikis.get(wiki) or {}
        periods = sorted(
            ({"from": p.get("from"), "to": p.get("to") or "present", "note": p.get("note"), "log": p.get("log")} for p in ps),
            key=lambda x: x["from"] or "",
        )
        local.append({
            "wiki": wiki,
            "periods": periods,
            "current": any(is_current(p) for p in ps),
            "is_gs": bool(w.get("is_gs") or w.get("is_locked")),
            "is_locked": bool(w.get("is_locked")),
            "domain": w.get("domain", ""),
        })
    local.sort(key=lambda r: (not r["current"], r["wiki"]))
    return {"found": True, "groups": groups, "local": local}
