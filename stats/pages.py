import hashlib
import os

from flask import Blueprint, render_template, send_from_directory, url_for

from stats import settings
from stats.auth import oauth_ready

bp = Blueprint("pages", __name__)


js_dir = os.path.join(settings.app_dir, "js")
css_dir = os.path.join(settings.app_dir, "css")


def asset_version():
    # hash of everything in js/ and css/, so browsers pick up new files after a
    # deploy. not mtimes, the build service sets all of them to 1980
    h = hashlib.sha1()
    for top in (js_dir, css_dir):
        for root, dirs, files in os.walk(top):
            dirs.sort()
            for f in sorted(files):
                with open(os.path.join(root, f), "rb") as fh:
                    h.update(fh.read())
    return h.hexdigest()[:10]


version = asset_version()


def page(template, **extra):
    html = render_template(template, assets=settings.assets, v=version, **extra)
    return html, 200, {"Cache-Control": "private, no-store"}


@bp.route("/js/<path:name>")
def js(name):
    return send_from_directory(js_dir, name)


@bp.route("/css/<path:name>")
def css(name):
    return send_from_directory(css_dir, name)


@bp.route("/")
def index():
    return page("index.html")


def login_page():
    return page("login.html", login_url=url_for("auth.login"), login_enabled=oauth_ready())
