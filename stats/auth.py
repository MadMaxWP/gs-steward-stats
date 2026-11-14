import mwoauth
from flask import Blueprint, current_app, jsonify, redirect, request, session, url_for

from stats import people

# oauth login against meta. everything except the oauth endpoints needs a
# logged in session. we only keep the username in the session cookie

bp = Blueprint("auth", __name__)

mw_uri = "https://meta.wikimedia.org/w/index.php"
# the login screen needs its js and css before anyone is logged in
public_endpoints = {"auth.login", "auth.oauth_callback", "auth.logout", "pages.js", "pages.css", "healthz"}


def oauth_ready():
    c = current_app.config
    return bool(c.get("SECRET_KEY") and c.get("gs_consumer_key") and c.get("gs_consumer_secret"))


def consumer():
    c = current_app.config
    return mwoauth.ConsumerToken(c["gs_consumer_key"], c["gs_consumer_secret"])


def current_user():
    return session.get("username")


@bp.route("/login")
def login():
    if not oauth_ready():
        return current_app.response_class("Login is not configured (GS_SECRET_KEY, GS_CONSUMER_KEY or GS_CONSUMER_SECRET is missing).", status=503, mimetype="text/plain")
    try:
        target, request_token = mwoauth.initiate(mw_uri, consumer())
    except Exception:
        current_app.logger.exception("mwoauth.initiate failed")
        return redirect(url_for("pages.index"))
    session["request_token"] = dict(zip(request_token._fields, request_token))
    return redirect(target)


@bp.route("/oauth-callback")
def oauth_callback():
    if not oauth_ready() or "request_token" not in session:
        return redirect(url_for("pages.index"))
    try:
        access_token = mwoauth.complete(mw_uri, consumer(), mwoauth.RequestToken(**session.pop("request_token")), request.query_string)
        identity = mwoauth.identify(mw_uri, consumer(), access_token)
    except Exception:
        current_app.logger.exception("oauth handshake failed")
        return redirect(url_for("pages.index"))
    session.clear()
    # browser session cookie, gone when the browser closes. we only need the name,
    # the access token isn't used for anything so it isn't kept
    session.permanent = False
    session["username"] = identity["username"]
    return redirect(url_for("pages.index"))


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("pages.index"))


def require_login():
    if request.endpoint in public_endpoints:
        return None
    if current_user():
        if request.path.startswith("/api/"):
            # any api call counts as being here, for the people page
            try:
                people.seen(current_user())
            except Exception:
                current_app.logger.exception("could not update the people table")
        return None
    if request.path.startswith("/api/"):
        return jsonify({"error": "Login required."}), 401
    from stats.pages import login_page
    return login_page()
