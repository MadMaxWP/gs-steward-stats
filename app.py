"""WSGI entry point.
"""

from gs_stats import create_app

app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
