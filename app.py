import os
import tomllib

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from stats import api, auth, pages, pool, settings, stewards

# gunicorn runs `app` from here (see Procfile)

app = Flask(__name__, static_folder=None, template_folder="templates")
# toolforge's front proxy does https, so trust its forwarded headers
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

# on toolforge the secrets are envvars (toolforge envvars create GS_SECRET_KEY ...).
# a config.toml next to this file still works for local runs
config_file = os.path.join(settings.app_dir, "config.toml")
conf = {}
if os.path.exists(config_file):
    with open(config_file, "rb") as f:
        conf = tomllib.load(f)


def setting(name, env):
    return conf.get(name) or conf.get(name.upper()) or os.environ.get(env)


app.config["SECRET_KEY"] = setting("secret_key", "GS_SECRET_KEY")
app.config["gs_consumer_key"] = setting("consumer_key", "GS_CONSUMER_KEY")
app.config["gs_consumer_secret"] = setting("consumer_secret", "GS_CONSUMER_SECRET")

app.register_blueprint(auth.bp)
app.register_blueprint(pages.bp)
app.register_blueprint(api.bp)
app.register_blueprint(stewards.bp)

app.before_request(auth.require_login)


# one gunicorn worker (see Procfile), so these are the only toolsdb connections
# the website ever has: up to 6 reading from the read only copy, and 1 on the
# primary for the "people" page. waiting for a free one gives up after 30s
pool.setup(read=6, write=1, wait=30, busy_wait=5)


@app.route("/healthz")
def healthz():
    # toolforge asks this to know the web component is up
    return "ok", 200, {"Content-Type": "text/plain", "Cache-Control": "no-store"}


@app.errorhandler(Exception)
def on_error(e):
    if isinstance(e, HTTPException):
        if request.path.startswith("/api/"):
            return jsonify({"error": e.description}), e.code
        return e
    if isinstance(e, pool.PoolTimeout):
        app.logger.warning("no free db connection for %s", request.path)
        msg = "The site is busy right now. Please try again in a moment."
        return (jsonify({"error": msg}), 503) if request.path.startswith("/api/") else (msg, 503)
    # log the real thing, don't show sql or hostnames to people
    app.logger.exception("unhandled error on %s", request.path)
    if request.path.startswith("/api/"):
        return jsonify({"error": "Something went wrong on the server. Please try again in a moment."}), 500
    return "Something went wrong on the server.", 500


if __name__ == "__main__":
    app.run()
