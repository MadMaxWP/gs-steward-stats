import json
import re

# log_params on the replicas come in three shapes: php serialized arrays,
# json, or old newline separated text. this turns all of them into plain dicts

key_prefix = re.compile(r"^\d+:[\w-]*:")


def php_unserialize(raw):
    data = raw.encode("utf-8") if isinstance(raw, str) else raw
    pos = 0

    def parse():
        nonlocal pos
        t = data[pos:pos + 1]
        if t == b"N":
            pos += 2
            return None
        if t in (b"b", b"i"):
            end = data.index(b";", pos)
            v = data[pos + 2:end]
            pos = end + 1
            return bool(int(v)) if t == b"b" else int(v)
        if t == b"d":
            end = data.index(b";", pos)
            v = float(data[pos + 2:end])
            pos = end + 1
            return v
        if t == b"s":
            colon = data.index(b":", pos + 2)
            n = int(data[pos + 2:colon])
            start = colon + 2
            v = data[start:start + n].decode("utf-8", "replace")
            pos = start + n + 2
            return v
        if t == b"a":
            colon = data.index(b":", pos + 2)
            n = int(data[pos + 2:colon])
            pos = colon + 2
            out = {}
            for _ in range(n):
                k = parse()
                out[k] = parse()
            pos += 1
            return out
        raise ValueError("unsupported php value")

    return parse()


def clean(v):
    # drop the "4::" style prefixes and turn 0..n keyed dicts back into lists
    if isinstance(v, dict):
        keys = list(v.keys())
        if keys and all(isinstance(k, int) for k in keys) and keys == list(range(len(keys))):
            return [clean(v[k]) for k in keys]
        return {key_prefix.sub("", str(k)): clean(x) for k, x in v.items()}
    if isinstance(v, list):
        return [clean(x) for x in v]
    return v


def normalize(raw):
    if raw is None or raw == "" or raw == [] or raw == {}:
        return {}
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    val = raw
    if isinstance(raw, str):
        s = raw.strip()
        if s.startswith("a:"):
            try:
                val = php_unserialize(s)
            except Exception:
                val = {"raw": s}
        elif s.startswith("{") or s.startswith("["):
            try:
                val = json.loads(s)
            except Exception:
                val = {"raw": s}
        else:
            val = {"legacy": s.split("\n")}
    val = clean(val)
    if isinstance(val, list):
        return {"list": val}
    if not isinstance(val, dict):
        return {"raw": str(val)}
    return val


def to_json(raw):
    return json.dumps(normalize(raw), ensure_ascii=False)
