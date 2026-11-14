import os
import re

from stats import settings

# which commit is running, for the footer. the build service keeps the .git
# folder in the image, so it's read from there once at startup. GS_COMMIT can
# override it if that ever changes

source_url = os.environ.get("GS_SOURCE_URL", "https://github.com/MadMaxWP/gs-steward-stats")


def from_git():
    git = os.path.join(settings.app_dir, ".git")
    try:
        with open(os.path.join(git, "HEAD"), encoding="utf-8") as f:
            head = f.read().strip()
        # the build checks out the exact commit, so HEAD is usually the hash itself
        if not head.startswith("ref: "):
            return head
        ref = head[5:]
        path = os.path.join(git, ref)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return f.read().strip()
        with open(os.path.join(git, "packed-refs"), encoding="utf-8") as f:
            for line in f:
                if line.strip().endswith(" " + ref):
                    return line.split()[0]
    except OSError:
        pass
    return ""


def find():
    found = (os.environ.get("GS_COMMIT") or "").strip() or from_git()
    return found if re.fullmatch(r"[0-9a-f]{7,40}", found) else ""


_commit = find()


def commit():
    return _commit
