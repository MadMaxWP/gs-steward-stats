import os
import tomllib

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from stats import api, auth, db, pages, settings, stewards

app = Flask(__name__, static_folder=None, template_folder="templates")
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

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
app.teardown_appcontext(db.close)


@app.errorhandler(Exception)
def on_error(e):
    if isinstance(e, HTTPException):
        if request.path.startswith("/api/"):
            return jsonify({"error": e.description}), e.code
        return e
    app.logger.exception("unhandled error on %s", request.path)
    if request.path.startswith("/api/"):
        return jsonify({"error": "Something went wrong on the server. Please try again in a moment."}), 500
    return "Something went wrong on the server.", 500


if __name__ == "__main__":
    app.run()
