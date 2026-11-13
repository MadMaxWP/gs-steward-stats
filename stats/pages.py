import os

from flask import Blueprint, render_template, send_from_directory, url_for

from stats import settings
from stats.auth import oauth_ready

bp = Blueprint("pages", __name__)


js_dir = os.path.join(settings.app_dir, "js")
css_dir = os.path.join(settings.app_dir, "css")


def asset_version():
    # newest mtime in js/ and css/, so browsers pick up new files after a deploy
    newest = 0
    for top in (js_dir, css_dir):
        for root, _, files in os.walk(top):
            for f in files:
                newest = max(newest, int(os.path.getmtime(os.path.join(root, f))))
    return str(newest)


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
