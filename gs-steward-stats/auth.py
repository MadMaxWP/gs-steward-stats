from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for

import mwoauth

from .settings import asset_urls, login_configured, settings

bp = Blueprint("auth", __name__)

# Endpoints reachable without a session
public_endpoints = {"auth.login", "auth.oauth_callback", "auth.logout", "static"}


def current_user():
    return session.get("username")


def _consumer_token():
    return mwoauth.ConsumerToken(settings["consumer_key"], settings["consumer_secret"])


@bp.route("/login")
def login():
    """Step 1: get a request token and send the user to Meta-Wiki to approve it."""
    if not login_configured(settings):
        return login_page(), 503
    try:
        target, request_token = mwoauth.initiate(settings["oauth_mwuri"], _consumer_token())
    except Exception:
        current_app.logger.exception("mwoauth.initiate failed")
        return redirect(url_for("pages.index"))
    session["request_token"] = dict(zip(request_token._fields, request_token))
    return redirect(target)


@bp.route("/oauth-callback")
def oauth_callback():
    """Step 2: Meta-Wiki redirects back here; exchange the token and identify the user."""
    if not login_configured(settings) or "request_token" not in session:
        return redirect(url_for("pages.index"))
    try:
        access_token = mwoauth.complete(
            settings["oauth_mwuri"],
            _consumer_token(),
            mwoauth.RequestToken(**session.pop("request_token")),
            request.query_string,
        )
        identity = mwoauth.identify(settings["oauth_mwuri"], _consumer_token(), access_token)
    except Exception:
        current_app.logger.exception("OAuth authentication failed")
        return redirect(url_for("pages.index"))

    session.clear()
    session.permanent = False  # browser-session cookie
    session["username"] = identity["username"]
    session["access_token"] = dict(zip(access_token._fields, access_token))
    return redirect(url_for("pages.index"))


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("pages.index"))


@bp.route("/api/me")
def api_me():
    """Who is logged in (used by the header)."""
    return jsonify({"username": current_user()})


def login_page():
    return render_template(
        "login.html",
        urls=asset_urls(settings),
        client={
            "enabled": login_configured(settings),
            "loginUrl": url_for("auth.login"),
            "logo": settings["logo_url"],
            "maintainer": settings["maintainer"],
        },
    )


def require_login():
    """``before_request`` hook: block everything except the login endpoints."""
    if request.endpoint in public_endpoints or current_user():
        return None
    if request.path.startswith("/api/"):
        return jsonify({"error": "Login required."}), 401
    return login_page(), 200, {"Cache-Control": "no-store"}
